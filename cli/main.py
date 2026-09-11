from typing import Optional
import datetime
import typer
from pathlib import Path
from functools import wraps
from rich.console import Console
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
load_dotenv(".env.enterprise", override=False)
from rich.panel import Panel
from rich.spinner import Spinner
from rich.live import Live
from rich.columns import Columns
from rich.markdown import Markdown
from rich.layout import Layout
from rich.text import Text
from rich.table import Table
from collections import deque
import time
from rich.tree import Tree
from rich import box
from rich.align import Align
from rich.rule import Rule

from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
from cli.models import AnalystType
from cli.utils import *
from cli.announcements import fetch_announcements, display_announcements
from cli.stats_handler import StatsCallbackHandler

console = Console()

app = typer.Typer(
    name="TradingAgents",
    help="TradingAgents CLI: Multi-Agents LLM Financial Trading Framework",
    add_completion=True,  # Enable shell completion
    # Never dump local variables into tracebacks: broker configs and API
    # payloads carry credentials.
    pretty_exceptions_show_locals=False,
)


# Create a deque to store recent messages with a maximum length
class MessageBuffer:
    # Fixed teams that always run (not user-selectable)
    FIXED_AGENTS = {
        "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "Trading Team": ["Trader"],
        "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    # Analyst name mapping
    ANALYST_MAPPING = {
        "market": "Market Analyst",
        "social": "Social Analyst",
        "news": "News Analyst",
        "fundamentals": "Fundamentals Analyst",
    }

    # Report section mapping: section -> (analyst_key for filtering, finalizing_agent)
    # analyst_key: which analyst selection controls this section (None = always included)
    # finalizing_agent: which agent must be "completed" for this report to count as done
    REPORT_SECTIONS = {
        "market_report": ("market", "Market Analyst"),
        "sentiment_report": ("social", "Social Analyst"),
        "news_report": ("news", "News Analyst"),
        "fundamentals_report": ("fundamentals", "Fundamentals Analyst"),
        "investment_plan": (None, "Research Manager"),
        "trader_investment_plan": (None, "Trader"),
        "final_trade_decision": (None, "Portfolio Manager"),
    }

    def __init__(self, max_length=100):
        self.messages = deque(maxlen=max_length)
        self.tool_calls = deque(maxlen=max_length)
        self.current_report = None
        self.final_report = None  # Store the complete final report
        self.agent_status = {}
        self.current_agent = None
        self.report_sections = {}
        self.selected_analysts = []
        self._processed_message_ids = set()

    def init_for_analysis(self, selected_analysts):
        """Initialize agent status and report sections based on selected analysts.

        Args:
            selected_analysts: List of analyst type strings (e.g., ["market", "news"])
        """
        self.selected_analysts = [a.lower() for a in selected_analysts]

        # Build agent_status dynamically
        self.agent_status = {}

        # Add selected analysts
        for analyst_key in self.selected_analysts:
            if analyst_key in self.ANALYST_MAPPING:
                self.agent_status[self.ANALYST_MAPPING[analyst_key]] = "pending"

        # Add fixed teams
        for team_agents in self.FIXED_AGENTS.values():
            for agent in team_agents:
                self.agent_status[agent] = "pending"

        # Build report_sections dynamically
        self.report_sections = {}
        for section, (analyst_key, _) in self.REPORT_SECTIONS.items():
            if analyst_key is None or analyst_key in self.selected_analysts:
                self.report_sections[section] = None

        # Reset other state
        self.current_report = None
        self.final_report = None
        self.current_agent = None
        self.messages.clear()
        self.tool_calls.clear()
        self._processed_message_ids.clear()

    def get_completed_reports_count(self):
        """Count reports that are finalized (their finalizing agent is completed).

        A report is considered complete when:
        1. The report section has content (not None), AND
        2. The agent responsible for finalizing that report has status "completed"

        This prevents interim updates (like debate rounds) from counting as completed.
        """
        count = 0
        for section in self.report_sections:
            if section not in self.REPORT_SECTIONS:
                continue
            _, finalizing_agent = self.REPORT_SECTIONS[section]
            # Report is complete if it has content AND its finalizing agent is done
            has_content = self.report_sections.get(section) is not None
            agent_done = self.agent_status.get(finalizing_agent) == "completed"
            if has_content and agent_done:
                count += 1
        return count

    def add_message(self, message_type, content):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.messages.append((timestamp, message_type, content))

    def add_tool_call(self, tool_name, args):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        self.tool_calls.append((timestamp, tool_name, args))

    def update_agent_status(self, agent, status):
        if agent in self.agent_status:
            self.agent_status[agent] = status
            self.current_agent = agent

    def update_report_section(self, section_name, content):
        if section_name in self.report_sections:
            self.report_sections[section_name] = content
            self._update_current_report()

    def _update_current_report(self):
        # For the panel display, only show the most recently updated section
        latest_section = None
        latest_content = None

        # Find the most recently updated section
        for section, content in self.report_sections.items():
            if content is not None:
                latest_section = section
                latest_content = content
               
        if latest_section and latest_content:
            # Format the current section for display
            section_titles = {
                "market_report": "Market Analysis",
                "sentiment_report": "Social Sentiment",
                "news_report": "News Analysis",
                "fundamentals_report": "Fundamentals Analysis",
                "investment_plan": "Research Team Decision",
                "trader_investment_plan": "Trading Team Plan",
                "final_trade_decision": "Portfolio Management Decision",
            }
            self.current_report = (
                f"### {section_titles[latest_section]}\n{latest_content}"
            )

        # Update the final complete report
        self._update_final_report()

    def _update_final_report(self):
        report_parts = []

        # Analyst Team Reports - use .get() to handle missing sections
        analyst_sections = ["market_report", "sentiment_report", "news_report", "fundamentals_report"]
        if any(self.report_sections.get(section) for section in analyst_sections):
            report_parts.append("## Analyst Team Reports")
            if self.report_sections.get("market_report"):
                report_parts.append(
                    f"### Market Analysis\n{self.report_sections['market_report']}"
                )
            if self.report_sections.get("sentiment_report"):
                report_parts.append(
                    f"### Social Sentiment\n{self.report_sections['sentiment_report']}"
                )
            if self.report_sections.get("news_report"):
                report_parts.append(
                    f"### News Analysis\n{self.report_sections['news_report']}"
                )
            if self.report_sections.get("fundamentals_report"):
                report_parts.append(
                    f"### Fundamentals Analysis\n{self.report_sections['fundamentals_report']}"
                )

        # Research Team Reports
        if self.report_sections.get("investment_plan"):
            report_parts.append("## Research Team Decision")
            report_parts.append(f"{self.report_sections['investment_plan']}")

        # Trading Team Reports
        if self.report_sections.get("trader_investment_plan"):
            report_parts.append("## Trading Team Plan")
            report_parts.append(f"{self.report_sections['trader_investment_plan']}")

        # Portfolio Management Decision
        if self.report_sections.get("final_trade_decision"):
            report_parts.append("## Portfolio Management Decision")
            report_parts.append(f"{self.report_sections['final_trade_decision']}")

        self.final_report = "\n\n".join(report_parts) if report_parts else None


message_buffer = MessageBuffer()


def create_layout():
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main"),
        Layout(name="footer", size=3),
    )
    layout["main"].split_column(
        Layout(name="upper", ratio=3), Layout(name="analysis", ratio=5)
    )
    layout["upper"].split_row(
        Layout(name="progress", ratio=2), Layout(name="messages", ratio=3)
    )
    return layout


def format_tokens(n):
    """Format token count for display."""
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def update_display(layout, spinner_text=None, stats_handler=None, start_time=None):
    # Header with welcome message
    layout["header"].update(
        Panel(
            "[bold green]Welcome to TradingAgents CLI[/bold green]\n"
            "[dim]© [Tauric Research](https://github.com/TauricResearch)[/dim]",
            title="Welcome to TradingAgents",
            border_style="green",
            padding=(1, 2),
            expand=True,
        )
    )

    # Progress panel showing agent status
    progress_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        box=box.SIMPLE_HEAD,  # Use simple header with horizontal lines
        title=None,  # Remove the redundant Progress title
        padding=(0, 2),  # Add horizontal padding
        expand=True,  # Make table expand to fill available space
    )
    progress_table.add_column("Team", style="cyan", justify="center", width=20)
    progress_table.add_column("Agent", style="green", justify="center", width=20)
    progress_table.add_column("Status", style="yellow", justify="center", width=20)

    # Group agents by team - filter to only include agents in agent_status
    all_teams = {
        "Analyst Team": [
            "Market Analyst",
            "Social Analyst",
            "News Analyst",
            "Fundamentals Analyst",
        ],
        "Research Team": ["Bull Researcher", "Bear Researcher", "Research Manager"],
        "Trading Team": ["Trader"],
        "Risk Management": ["Aggressive Analyst", "Neutral Analyst", "Conservative Analyst"],
        "Portfolio Management": ["Portfolio Manager"],
    }

    # Filter teams to only include agents that are in agent_status
    teams = {}
    for team, agents in all_teams.items():
        active_agents = [a for a in agents if a in message_buffer.agent_status]
        if active_agents:
            teams[team] = active_agents

    for team, agents in teams.items():
        # Add first agent with team name
        first_agent = agents[0]
        status = message_buffer.agent_status.get(first_agent, "pending")
        if status == "in_progress":
            spinner = Spinner(
                "dots", text="[blue]in_progress[/blue]", style="bold cyan"
            )
            status_cell = spinner
        else:
            status_color = {
                "pending": "yellow",
                "completed": "green",
                "error": "red",
            }.get(status, "white")
            status_cell = f"[{status_color}]{status}[/{status_color}]"
        progress_table.add_row(team, first_agent, status_cell)

        # Add remaining agents in team
        for agent in agents[1:]:
            status = message_buffer.agent_status.get(agent, "pending")
            if status == "in_progress":
                spinner = Spinner(
                    "dots", text="[blue]in_progress[/blue]", style="bold cyan"
                )
                status_cell = spinner
            else:
                status_color = {
                    "pending": "yellow",
                    "completed": "green",
                    "error": "red",
                }.get(status, "white")
                status_cell = f"[{status_color}]{status}[/{status_color}]"
            progress_table.add_row("", agent, status_cell)

        # Add horizontal line after each team
        progress_table.add_row("─" * 20, "─" * 20, "─" * 20, style="dim")

    layout["progress"].update(
        Panel(progress_table, title="Progress", border_style="cyan", padding=(1, 2))
    )

    # Messages panel showing recent messages and tool calls
    messages_table = Table(
        show_header=True,
        header_style="bold magenta",
        show_footer=False,
        expand=True,  # Make table expand to fill available space
        box=box.MINIMAL,  # Use minimal box style for a lighter look
        show_lines=True,  # Keep horizontal lines
        padding=(0, 1),  # Add some padding between columns
    )
    messages_table.add_column("Time", style="cyan", width=8, justify="center")
    messages_table.add_column("Type", style="green", width=10, justify="center")
    messages_table.add_column(
        "Content", style="white", no_wrap=False, ratio=1
    )  # Make content column expand

    # Combine tool calls and messages
    all_messages = []

    # Add tool calls
    for timestamp, tool_name, args in message_buffer.tool_calls:
        formatted_args = format_tool_args(args)
        all_messages.append((timestamp, "Tool", f"{tool_name}: {formatted_args}"))

    # Add regular messages
    for timestamp, msg_type, content in message_buffer.messages:
        content_str = str(content) if content else ""
        if len(content_str) > 200:
            content_str = content_str[:197] + "..."
        all_messages.append((timestamp, msg_type, content_str))

    # Sort by timestamp descending (newest first)
    all_messages.sort(key=lambda x: x[0], reverse=True)

    # Calculate how many messages we can show based on available space
    max_messages = 12

    # Get the first N messages (newest ones)
    recent_messages = all_messages[:max_messages]

    # Add messages to table (already in newest-first order)
    for timestamp, msg_type, content in recent_messages:
        # Format content with word wrapping
        wrapped_content = Text(content, overflow="fold")
        messages_table.add_row(timestamp, msg_type, wrapped_content)

    layout["messages"].update(
        Panel(
            messages_table,
            title="Messages & Tools",
            border_style="blue",
            padding=(1, 2),
        )
    )

    # Analysis panel showing current report
    if message_buffer.current_report:
        layout["analysis"].update(
            Panel(
                Markdown(message_buffer.current_report),
                title="Current Report",
                border_style="green",
                padding=(1, 2),
            )
        )
    else:
        layout["analysis"].update(
            Panel(
                "[italic]Waiting for analysis report...[/italic]",
                title="Current Report",
                border_style="green",
                padding=(1, 2),
            )
        )

    # Footer with statistics
    # Agent progress - derived from agent_status dict
    agents_completed = sum(
        1 for status in message_buffer.agent_status.values() if status == "completed"
    )
    agents_total = len(message_buffer.agent_status)

    # Report progress - based on agent completion (not just content existence)
    reports_completed = message_buffer.get_completed_reports_count()
    reports_total = len(message_buffer.report_sections)

    # Build stats parts
    stats_parts = [f"Agents: {agents_completed}/{agents_total}"]

    # LLM and tool stats from callback handler
    if stats_handler:
        stats = stats_handler.get_stats()
        stats_parts.append(f"LLM: {stats['llm_calls']}")
        stats_parts.append(f"Tools: {stats['tool_calls']}")

        # Token display with graceful fallback
        if stats["tokens_in"] > 0 or stats["tokens_out"] > 0:
            tokens_str = f"Tokens: {format_tokens(stats['tokens_in'])}\u2191 {format_tokens(stats['tokens_out'])}\u2193"
        else:
            tokens_str = "Tokens: --"
        stats_parts.append(tokens_str)

    stats_parts.append(f"Reports: {reports_completed}/{reports_total}")

    # Elapsed time
    if start_time:
        elapsed = time.time() - start_time
        elapsed_str = f"\u23f1 {int(elapsed // 60):02d}:{int(elapsed % 60):02d}"
        stats_parts.append(elapsed_str)

    stats_table = Table(show_header=False, box=None, padding=(0, 2), expand=True)
    stats_table.add_column("Stats", justify="center")
    stats_table.add_row(" | ".join(stats_parts))

    layout["footer"].update(Panel(stats_table, border_style="grey50"))


def get_user_selections():
    """Get all user selections before starting the analysis display."""
    # Display ASCII art welcome message
    with open(Path(__file__).parent / "static" / "welcome.txt", "r", encoding="utf-8") as f:
        welcome_ascii = f.read()

    # Create welcome box content
    welcome_content = f"{welcome_ascii}\n"
    welcome_content += "[bold green]TradingAgents: Multi-Agents LLM Financial Trading Framework - CLI[/bold green]\n\n"
    welcome_content += "[bold]Workflow Steps:[/bold]\n"
    welcome_content += "I. Analyst Team → II. Research Team → III. Trader → IV. Risk Management → V. Portfolio Management\n\n"
    welcome_content += (
        "[dim]Built by [Tauric Research](https://github.com/TauricResearch)[/dim]"
    )

    # Create and center the welcome box
    welcome_box = Panel(
        welcome_content,
        border_style="green",
        padding=(1, 2),
        title="Welcome to TradingAgents",
        subtitle="Multi-Agents LLM Financial Trading Framework",
    )
    console.print(Align.center(welcome_box))
    console.print()
    console.print()  # Add vertical space before announcements

    # Fetch and display announcements (silent on failure)
    announcements = fetch_announcements()
    display_announcements(console, announcements)

    # Create a boxed questionnaire for each step
    def create_question_box(title, prompt, default=None):
        box_content = f"[bold]{title}[/bold]\n"
        box_content += f"[dim]{prompt}[/dim]"
        if default:
            box_content += f"\n[dim]Default: {default}[/dim]"
        return Panel(box_content, border_style="blue", padding=(1, 2))

    # Step 1: Ticker symbol
    console.print(
        create_question_box(
            "Step 1: Ticker Symbol",
            "Enter the exact ticker symbol to analyze, including exchange suffix when needed (examples: SPY, CNC.TO, 7203.T, 0700.HK)",
            "SPY",
        )
    )
    selected_ticker = get_ticker()

    # Step 2: Analysis date
    default_date = datetime.datetime.now().strftime("%Y-%m-%d")
    console.print(
        create_question_box(
            "Step 2: Analysis Date",
            "Enter the analysis date (YYYY-MM-DD)",
            default_date,
        )
    )
    analysis_date = get_analysis_date()

    # Step 3: Output language
    console.print(
        create_question_box(
            "Step 3: Output Language",
            "Select the language for analyst reports and final decision"
        )
    )
    output_language = ask_output_language()

    # Step 4: Select analysts
    console.print(
        create_question_box(
            "Step 4: Analysts Team", "Select your LLM analyst agents for the analysis"
        )
    )
    selected_analysts = select_analysts()
    console.print(
        f"[green]Selected analysts:[/green] {', '.join(analyst.value for analyst in selected_analysts)}"
    )

    # Step 5: Research depth
    console.print(
        create_question_box(
            "Step 5: Research Depth", "Select your research depth level"
        )
    )
    selected_research_depth = select_research_depth()

    # Step 6: LLM Provider
    console.print(
        create_question_box(
            "Step 6: LLM Provider", "Select your LLM provider"
        )
    )
    selected_llm_provider, backend_url = select_llm_provider()

    # Step 7: Thinking agents
    console.print(
        create_question_box(
            "Step 7: Thinking Agents", "Select your thinking agents for analysis"
        )
    )
    selected_shallow_thinker = select_shallow_thinking_agent(selected_llm_provider)
    selected_deep_thinker = select_deep_thinking_agent(selected_llm_provider)

    # Step 8: Provider-specific thinking configuration
    thinking_level = None
    reasoning_effort = None
    anthropic_effort = None

    provider_lower = selected_llm_provider.lower()
    if provider_lower == "google":
        console.print(
            create_question_box(
                "Step 8: Thinking Mode",
                "Configure Gemini thinking mode"
            )
        )
        thinking_level = ask_gemini_thinking_config()
    elif provider_lower == "openai":
        console.print(
            create_question_box(
                "Step 8: Reasoning Effort",
                "Configure OpenAI reasoning effort level"
            )
        )
        reasoning_effort = ask_openai_reasoning_effort()
    elif provider_lower == "anthropic":
        console.print(
            create_question_box(
                "Step 8: Effort Level",
                "Configure Claude effort level"
            )
        )
        anthropic_effort = ask_anthropic_effort()

    return {
        "ticker": selected_ticker,
        "analysis_date": analysis_date,
        "analysts": selected_analysts,
        "research_depth": selected_research_depth,
        "llm_provider": selected_llm_provider.lower(),
        "backend_url": backend_url,
        "shallow_thinker": selected_shallow_thinker,
        "deep_thinker": selected_deep_thinker,
        "google_thinking_level": thinking_level,
        "openai_reasoning_effort": reasoning_effort,
        "anthropic_effort": anthropic_effort,
        "output_language": output_language,
    }


def get_ticker():
    """Get ticker symbol from user input."""
    return typer.prompt("", default="SPY")


def get_analysis_date():
    """Get the analysis date from user input."""
    while True:
        date_str = typer.prompt(
            "", default=datetime.datetime.now().strftime("%Y-%m-%d")
        )
        try:
            # Validate date format and ensure it's not in the future
            analysis_date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            if analysis_date.date() > datetime.datetime.now().date():
                console.print("[red]Error: Analysis date cannot be in the future[/red]")
                continue
            return date_str
        except ValueError:
            console.print(
                "[red]Error: Invalid date format. Please use YYYY-MM-DD[/red]"
            )


def save_report_to_disk(final_state, ticker: str, save_path: Path):
    """Save complete analysis report to disk with organized subfolders."""
    save_path.mkdir(parents=True, exist_ok=True)
    sections = []

    # 1. Analysts
    analysts_dir = save_path / "1_analysts"
    analyst_parts = []
    if final_state.get("market_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "market.md").write_text(final_state["market_report"], encoding="utf-8")
        analyst_parts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "sentiment.md").write_text(final_state["sentiment_report"], encoding="utf-8")
        analyst_parts.append(("Social Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "news.md").write_text(final_state["news_report"], encoding="utf-8")
        analyst_parts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):
        analysts_dir.mkdir(exist_ok=True)
        (analysts_dir / "fundamentals.md").write_text(final_state["fundamentals_report"], encoding="utf-8")
        analyst_parts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    if analyst_parts:
        content = "\n\n".join(f"### {name}\n{text}" for name, text in analyst_parts)
        sections.append(f"## I. Analyst Team Reports\n\n{content}")

    # 2. Research
    if final_state.get("investment_debate_state"):
        research_dir = save_path / "2_research"
        debate = final_state["investment_debate_state"]
        research_parts = []
        if debate.get("bull_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bull.md").write_text(debate["bull_history"], encoding="utf-8")
            research_parts.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "bear.md").write_text(debate["bear_history"], encoding="utf-8")
            research_parts.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):
            research_dir.mkdir(exist_ok=True)
            (research_dir / "manager.md").write_text(debate["judge_decision"], encoding="utf-8")
            research_parts.append(("Research Manager", debate["judge_decision"]))
        if research_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in research_parts)
            sections.append(f"## II. Research Team Decision\n\n{content}")

    # 3. Trading
    if final_state.get("trader_investment_plan"):
        trading_dir = save_path / "3_trading"
        trading_dir.mkdir(exist_ok=True)
        (trading_dir / "trader.md").write_text(final_state["trader_investment_plan"], encoding="utf-8")
        sections.append(f"## III. Trading Team Plan\n\n### Trader\n{final_state['trader_investment_plan']}")

    # 4. Risk Management
    if final_state.get("risk_debate_state"):
        risk_dir = save_path / "4_risk"
        risk = final_state["risk_debate_state"]
        risk_parts = []
        if risk.get("aggressive_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "aggressive.md").write_text(risk["aggressive_history"], encoding="utf-8")
            risk_parts.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "conservative.md").write_text(risk["conservative_history"], encoding="utf-8")
            risk_parts.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_dir.mkdir(exist_ok=True)
            (risk_dir / "neutral.md").write_text(risk["neutral_history"], encoding="utf-8")
            risk_parts.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_parts:
            content = "\n\n".join(f"### {name}\n{text}" for name, text in risk_parts)
            sections.append(f"## IV. Risk Management Team Decision\n\n{content}")

        # 5. Portfolio Manager
        if risk.get("judge_decision"):
            portfolio_dir = save_path / "5_portfolio"
            portfolio_dir.mkdir(exist_ok=True)
            (portfolio_dir / "decision.md").write_text(risk["judge_decision"], encoding="utf-8")
            sections.append(f"## V. Portfolio Manager Decision\n\n### Portfolio Manager\n{risk['judge_decision']}")

    # Write consolidated report
    header = f"# Trading Analysis Report: {ticker}\n\nGenerated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    (save_path / "complete_report.md").write_text(header + "\n\n".join(sections), encoding="utf-8")
    return save_path / "complete_report.md"


def display_complete_report(final_state):
    """Display the complete analysis report sequentially (avoids truncation)."""
    console.print()
    console.print(Rule("Complete Analysis Report", style="bold green"))

    # I. Analyst Team Reports
    analysts = []
    if final_state.get("market_report"):
        analysts.append(("Market Analyst", final_state["market_report"]))
    if final_state.get("sentiment_report"):
        analysts.append(("Social Analyst", final_state["sentiment_report"]))
    if final_state.get("news_report"):
        analysts.append(("News Analyst", final_state["news_report"]))
    if final_state.get("fundamentals_report"):
        analysts.append(("Fundamentals Analyst", final_state["fundamentals_report"]))
    if analysts:
        console.print(Panel("[bold]I. Analyst Team Reports[/bold]", border_style="cyan"))
        for title, content in analysts:
            console.print(Panel(Markdown(content), title=title, border_style="blue", padding=(1, 2)))

    # II. Research Team Reports
    if final_state.get("investment_debate_state"):
        debate = final_state["investment_debate_state"]
        research = []
        if debate.get("bull_history"):
            research.append(("Bull Researcher", debate["bull_history"]))
        if debate.get("bear_history"):
            research.append(("Bear Researcher", debate["bear_history"]))
        if debate.get("judge_decision"):
            research.append(("Research Manager", debate["judge_decision"]))
        if research:
            console.print(Panel("[bold]II. Research Team Decision[/bold]", border_style="magenta"))
            for title, content in research:
                console.print(Panel(Markdown(content), title=title, border_style="blue", padding=(1, 2)))

    # III. Trading Team
    if final_state.get("trader_investment_plan"):
        console.print(Panel("[bold]III. Trading Team Plan[/bold]", border_style="yellow"))
        console.print(Panel(Markdown(final_state["trader_investment_plan"]), title="Trader", border_style="blue", padding=(1, 2)))

    # IV. Risk Management Team
    if final_state.get("risk_debate_state"):
        risk = final_state["risk_debate_state"]
        risk_reports = []
        if risk.get("aggressive_history"):
            risk_reports.append(("Aggressive Analyst", risk["aggressive_history"]))
        if risk.get("conservative_history"):
            risk_reports.append(("Conservative Analyst", risk["conservative_history"]))
        if risk.get("neutral_history"):
            risk_reports.append(("Neutral Analyst", risk["neutral_history"]))
        if risk_reports:
            console.print(Panel("[bold]IV. Risk Management Team Decision[/bold]", border_style="red"))
            for title, content in risk_reports:
                console.print(Panel(Markdown(content), title=title, border_style="blue", padding=(1, 2)))

        # V. Portfolio Manager Decision
        if risk.get("judge_decision"):
            console.print(Panel("[bold]V. Portfolio Manager Decision[/bold]", border_style="green"))
            console.print(Panel(Markdown(risk["judge_decision"]), title="Portfolio Manager", border_style="blue", padding=(1, 2)))


def update_research_team_status(status):
    """Update status for research team members (not Trader)."""
    research_team = ["Bull Researcher", "Bear Researcher", "Research Manager"]
    for agent in research_team:
        message_buffer.update_agent_status(agent, status)


# Ordered list of analysts for status transitions
ANALYST_ORDER = ["market", "social", "news", "fundamentals"]
ANALYST_AGENT_NAMES = {
    "market": "Market Analyst",
    "social": "Social Analyst",
    "news": "News Analyst",
    "fundamentals": "Fundamentals Analyst",
}
ANALYST_REPORT_MAP = {
    "market": "market_report",
    "social": "sentiment_report",
    "news": "news_report",
    "fundamentals": "fundamentals_report",
}


def update_analyst_statuses(message_buffer, chunk):
    """Update analyst statuses based on accumulated report state.

    Logic:
    - Store new report content from the current chunk if present
    - Check accumulated report_sections (not just current chunk) for status
    - Analysts with reports = completed
    - First analyst without report = in_progress
    - Remaining analysts without reports = pending
    - When all analysts done, set Bull Researcher to in_progress
    """
    selected = message_buffer.selected_analysts
    found_active = False

    for analyst_key in ANALYST_ORDER:
        if analyst_key not in selected:
            continue

        agent_name = ANALYST_AGENT_NAMES[analyst_key]
        report_key = ANALYST_REPORT_MAP[analyst_key]

        # Capture new report content from current chunk
        if chunk.get(report_key):
            message_buffer.update_report_section(report_key, chunk[report_key])

        # Determine status from accumulated sections, not just current chunk
        has_report = bool(message_buffer.report_sections.get(report_key))

        if has_report:
            message_buffer.update_agent_status(agent_name, "completed")
        elif not found_active:
            message_buffer.update_agent_status(agent_name, "in_progress")
            found_active = True
        else:
            message_buffer.update_agent_status(agent_name, "pending")

    # When all analysts complete, transition research team to in_progress
    if not found_active and selected:
        if message_buffer.agent_status.get("Bull Researcher") == "pending":
            message_buffer.update_agent_status("Bull Researcher", "in_progress")

def extract_content_string(content):
    """Extract string content from various message formats.
    Returns None if no meaningful text content is found.
    """
    import ast

    def is_empty(val):
        """Check if value is empty using Python's truthiness."""
        if val is None or val == '':
            return True
        if isinstance(val, str):
            s = val.strip()
            if not s:
                return True
            try:
                return not bool(ast.literal_eval(s))
            except (ValueError, SyntaxError):
                return False  # Can't parse = real text
        return not bool(val)

    if is_empty(content):
        return None

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, dict):
        text = content.get('text', '')
        return text.strip() if not is_empty(text) else None

    if isinstance(content, list):
        text_parts = [
            item.get('text', '').strip() if isinstance(item, dict) and item.get('type') == 'text'
            else (item.strip() if isinstance(item, str) else '')
            for item in content
        ]
        result = ' '.join(t for t in text_parts if t and not is_empty(t))
        return result if result else None

    return str(content).strip() if not is_empty(content) else None


def classify_message_type(message) -> tuple[str, str | None]:
    """Classify LangChain message into display type and extract content.

    Returns:
        (type, content) - type is one of: User, Agent, Data, Control
                        - content is extracted string or None
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    content = extract_content_string(getattr(message, 'content', None))

    if isinstance(message, HumanMessage):
        if content and content.strip() == "Continue":
            return ("Control", content)
        return ("User", content)

    if isinstance(message, ToolMessage):
        return ("Data", content)

    if isinstance(message, AIMessage):
        return ("Agent", content)

    # Fallback for unknown types
    return ("System", content)


def format_tool_args(args, max_length=80) -> str:
    """Format tool arguments for terminal display."""
    result = str(args)
    if len(result) > max_length:
        return result[:max_length - 3] + "..."
    return result

def run_analysis(checkpoint: bool = False):
    # First get all user selections
    selections = get_user_selections()

    # Create config with selected research depth
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = selections["research_depth"]
    config["max_risk_discuss_rounds"] = selections["research_depth"]
    config["quick_think_llm"] = selections["shallow_thinker"]
    config["deep_think_llm"] = selections["deep_thinker"]
    config["backend_url"] = selections["backend_url"]
    config["llm_provider"] = selections["llm_provider"].lower()
    # Provider-specific thinking configuration
    config["google_thinking_level"] = selections.get("google_thinking_level")
    config["openai_reasoning_effort"] = selections.get("openai_reasoning_effort")
    config["anthropic_effort"] = selections.get("anthropic_effort")
    config["output_language"] = selections.get("output_language", "English")
    config["checkpoint_enabled"] = checkpoint

    # Create stats callback handler for tracking LLM/tool calls
    stats_handler = StatsCallbackHandler()

    # Normalize analyst selection to predefined order (selection is a 'set', order is fixed)
    selected_set = {analyst.value for analyst in selections["analysts"]}
    selected_analyst_keys = [a for a in ANALYST_ORDER if a in selected_set]

    # Initialize the graph with callbacks bound to LLMs
    graph = TradingAgentsGraph(
        selected_analyst_keys,
        config=config,
        debug=True,
        callbacks=[stats_handler],
    )

    # Initialize message buffer with selected analysts
    message_buffer.init_for_analysis(selected_analyst_keys)

    # Track start time for elapsed display
    start_time = time.time()

    # Create result directory
    results_dir = Path(config["results_dir"]) / selections["ticker"] / selections["analysis_date"]
    results_dir.mkdir(parents=True, exist_ok=True)
    report_dir = results_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    log_file = results_dir / "message_tool.log"
    log_file.touch(exist_ok=True)

    def save_message_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, message_type, content = obj.messages[-1]
            content = content.replace("\n", " ")  # Replace newlines with spaces
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [{message_type}] {content}\n")
        return wrapper
    
    def save_tool_call_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)
            timestamp, tool_name, args = obj.tool_calls[-1]
            args_str = ", ".join(f"{k}={v}" for k, v in args.items())
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} [Tool Call] {tool_name}({args_str})\n")
        return wrapper

    def save_report_section_decorator(obj, func_name):
        func = getattr(obj, func_name)
        @wraps(func)
        def wrapper(section_name, content):
            func(section_name, content)
            if section_name in obj.report_sections and obj.report_sections[section_name] is not None:
                content = obj.report_sections[section_name]
                if content:
                    file_name = f"{section_name}.md"
                    text = "\n".join(str(item) for item in content) if isinstance(content, list) else content
                    with open(report_dir / file_name, "w", encoding="utf-8") as f:
                        f.write(text)
        return wrapper

    message_buffer.add_message = save_message_decorator(message_buffer, "add_message")
    message_buffer.add_tool_call = save_tool_call_decorator(message_buffer, "add_tool_call")
    message_buffer.update_report_section = save_report_section_decorator(message_buffer, "update_report_section")

    # Now start the display layout
    layout = create_layout()

    with Live(layout, refresh_per_second=4) as live:
        # Initial display
        update_display(layout, stats_handler=stats_handler, start_time=start_time)

        # Add initial messages
        message_buffer.add_message("System", f"Selected ticker: {selections['ticker']}")
        message_buffer.add_message(
            "System", f"Analysis date: {selections['analysis_date']}"
        )
        message_buffer.add_message(
            "System",
            f"Selected analysts: {', '.join(analyst.value for analyst in selections['analysts'])}",
        )
        update_display(layout, stats_handler=stats_handler, start_time=start_time)

        # Update agent status to in_progress for the first analyst
        first_analyst = f"{selections['analysts'][0].value.capitalize()} Analyst"
        message_buffer.update_agent_status(first_analyst, "in_progress")
        update_display(layout, stats_handler=stats_handler, start_time=start_time)

        # Create spinner text
        spinner_text = (
            f"Analyzing {selections['ticker']} on {selections['analysis_date']}..."
        )
        update_display(layout, spinner_text, stats_handler=stats_handler, start_time=start_time)

        # Initialize state and get graph args with callbacks
        init_agent_state = graph.propagator.create_initial_state(
            selections["ticker"], selections["analysis_date"]
        )
        # Pass callbacks to graph config for tool execution tracking
        # (LLM tracking is handled separately via LLM constructor)
        args = graph.propagator.get_graph_args(callbacks=[stats_handler])

        # Stream the analysis
        trace = []
        for chunk in graph.graph.stream(init_agent_state, **args):
            # Process all messages in chunk, deduplicating by message ID
            for message in chunk.get("messages", []):
                msg_id = getattr(message, "id", None)
                if msg_id is not None:
                    if msg_id in message_buffer._processed_message_ids:
                        continue
                    message_buffer._processed_message_ids.add(msg_id)

                msg_type, content = classify_message_type(message)
                if content and content.strip():
                    message_buffer.add_message(msg_type, content)

                if hasattr(message, "tool_calls") and message.tool_calls:
                    for tool_call in message.tool_calls:
                        if isinstance(tool_call, dict):
                            message_buffer.add_tool_call(tool_call["name"], tool_call["args"])
                        else:
                            message_buffer.add_tool_call(tool_call.name, tool_call.args)

            # Update analyst statuses based on report state (runs on every chunk)
            update_analyst_statuses(message_buffer, chunk)

            # Research Team - Handle Investment Debate State
            if chunk.get("investment_debate_state"):
                debate_state = chunk["investment_debate_state"]
                bull_hist = debate_state.get("bull_history", "").strip()
                bear_hist = debate_state.get("bear_history", "").strip()
                judge = debate_state.get("judge_decision", "").strip()

                # Only update status when there's actual content
                if bull_hist or bear_hist:
                    update_research_team_status("in_progress")
                if bull_hist:
                    message_buffer.update_report_section(
                        "investment_plan", f"### Bull Researcher Analysis\n{bull_hist}"
                    )
                if bear_hist:
                    message_buffer.update_report_section(
                        "investment_plan", f"### Bear Researcher Analysis\n{bear_hist}"
                    )
                if judge:
                    message_buffer.update_report_section(
                        "investment_plan", f"### Research Manager Decision\n{judge}"
                    )
                    update_research_team_status("completed")
                    message_buffer.update_agent_status("Trader", "in_progress")

            # Trading Team
            if chunk.get("trader_investment_plan"):
                message_buffer.update_report_section(
                    "trader_investment_plan", chunk["trader_investment_plan"]
                )
                if message_buffer.agent_status.get("Trader") != "completed":
                    message_buffer.update_agent_status("Trader", "completed")
                    message_buffer.update_agent_status("Aggressive Analyst", "in_progress")

            # Risk Management Team - Handle Risk Debate State
            if chunk.get("risk_debate_state"):
                risk_state = chunk["risk_debate_state"]
                agg_hist = risk_state.get("aggressive_history", "").strip()
                con_hist = risk_state.get("conservative_history", "").strip()
                neu_hist = risk_state.get("neutral_history", "").strip()
                judge = risk_state.get("judge_decision", "").strip()

                if agg_hist:
                    if message_buffer.agent_status.get("Aggressive Analyst") != "completed":
                        message_buffer.update_agent_status("Aggressive Analyst", "in_progress")
                    message_buffer.update_report_section(
                        "final_trade_decision", f"### Aggressive Analyst Analysis\n{agg_hist}"
                    )
                if con_hist:
                    if message_buffer.agent_status.get("Conservative Analyst") != "completed":
                        message_buffer.update_agent_status("Conservative Analyst", "in_progress")
                    message_buffer.update_report_section(
                        "final_trade_decision", f"### Conservative Analyst Analysis\n{con_hist}"
                    )
                if neu_hist:
                    if message_buffer.agent_status.get("Neutral Analyst") != "completed":
                        message_buffer.update_agent_status("Neutral Analyst", "in_progress")
                    message_buffer.update_report_section(
                        "final_trade_decision", f"### Neutral Analyst Analysis\n{neu_hist}"
                    )
                if judge:
                    if message_buffer.agent_status.get("Portfolio Manager") != "completed":
                        message_buffer.update_agent_status("Portfolio Manager", "in_progress")
                        message_buffer.update_report_section(
                            "final_trade_decision", f"### Portfolio Manager Decision\n{judge}"
                        )
                        message_buffer.update_agent_status("Aggressive Analyst", "completed")
                        message_buffer.update_agent_status("Conservative Analyst", "completed")
                        message_buffer.update_agent_status("Neutral Analyst", "completed")
                        message_buffer.update_agent_status("Portfolio Manager", "completed")

            # Update the display
            update_display(layout, stats_handler=stats_handler, start_time=start_time)

            trace.append(chunk)

        # Get final state and decision
        final_state = trace[-1]
        decision = graph.process_signal(final_state["final_trade_decision"])

        # Update all agent statuses to completed
        for agent in message_buffer.agent_status:
            message_buffer.update_agent_status(agent, "completed")

        message_buffer.add_message(
            "System", f"Completed analysis for {selections['analysis_date']}"
        )

        # Update final report sections
        for section in message_buffer.report_sections.keys():
            if section in final_state:
                message_buffer.update_report_section(section, final_state[section])

        update_display(layout, stats_handler=stats_handler, start_time=start_time)

    # Post-analysis prompts (outside Live context for clean interaction)
    console.print("\n[bold cyan]Analysis Complete![/bold cyan]\n")

    # Prompt to save report
    save_choice = typer.prompt("Save report?", default="Y").strip().upper()
    if save_choice in ("Y", "YES", ""):
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default_path = Path.cwd() / "reports" / f"{selections['ticker']}_{timestamp}"
        save_path_str = typer.prompt(
            "Save path (press Enter for default)",
            default=str(default_path)
        ).strip()
        save_path = Path(save_path_str)
        try:
            report_file = save_report_to_disk(final_state, selections["ticker"], save_path)
            console.print(f"\n[green]✓ Report saved to:[/green] {save_path.resolve()}")
            console.print(f"  [dim]Complete report:[/dim] {report_file.name}")
        except Exception as e:
            console.print(f"[red]Error saving report: {e}[/red]")

    # Prompt to display full report
    display_choice = typer.prompt("\nDisplay full report on screen?", default="Y").strip().upper()
    if display_choice in ("Y", "YES", ""):
        display_complete_report(final_state)


@app.command()
def analyze(
    checkpoint: bool = typer.Option(
        False,
        "--checkpoint",
        help="Enable checkpoint/resume: save state after each node so a crashed run can resume.",
    ),
    clear_checkpoints: bool = typer.Option(
        False,
        "--clear-checkpoints",
        help="Delete all saved checkpoints before running (force fresh start).",
    ),
):
    if clear_checkpoints:
        from tradingagents.graph.checkpointer import clear_all_checkpoints
        n = clear_all_checkpoints(DEFAULT_CONFIG["data_cache_dir"])
        console.print(f"[yellow]Cleared {n} checkpoint(s).[/yellow]")
    run_analysis(checkpoint=checkpoint)


@app.command("process-analysis-requests")
def process_analysis_requests(
    limit: int = typer.Option(1, "--limit", min=1, help="Maximum queued requests to process."),
    dry_run: bool = typer.Option(False, "--dry-run", help="List queued requests without running analysis."),
):
    """Process queued site analysis refresh requests."""

    import os

    from tradingagents.site.analysis_runner import run_tradingagents_graph_for_request
    from tradingagents.site.analysis_worker import (
        process_queued_analysis_requests,
        requeue_stale_running_requests,
    )
    from tradingagents.storage import StorageRepository, create_storage_engine

    if not os.getenv("DATABASE_URL"):
        raise typer.BadParameter("DATABASE_URL is required for the analysis request worker")

    repo = StorageRepository(create_storage_engine())
    if not dry_run:
        stranded = requeue_stale_running_requests(repo)
        if stranded:
            console.print(f"[yellow]Requeued {len(stranded)} request(s) left running by an interrupted worker.[/yellow]")
    if dry_run:
        queued = repo.list_analysis_requests(status="queued", limit=limit)
        if not queued:
            console.print("[yellow]No queued analysis requests.[/yellow]")
            return
        table = Table(title="Queued Analysis Requests", box=box.SIMPLE_HEAD)
        table.add_column("ID")
        table.add_column("Ticker")
        table.add_column("Trade Date")
        table.add_column("Reason")
        for request in queued:
            table.add_row(
                str(request["id"]),
                str(request["ticker_code"]),
                str(request["requested_trade_date"]),
                str(request.get("reason") or ""),
            )
        console.print(table)
        return

    results = process_queued_analysis_requests(
        repo,
        lambda request: run_tradingagents_graph_for_request(
            request,
            config={"database_url": os.getenv("DATABASE_URL")},
        ),
        limit=limit,
    )
    if not results:
        console.print("[yellow]No queued analysis requests.[/yellow]")
        return
    for result in results:
        if result.status == "completed":
            console.print(
                f"[green]Completed[/green] {result.ticker_code}: analysis_run_id={result.analysis_run_id}"
            )
        else:
            console.print(f"[red]Failed[/red] {result.ticker_code}: {result.error}")


@app.command("process-analysis-outcomes")
def process_analysis_outcomes(
    limit: int = typer.Option(20, "--limit", min=1, help="Maximum completed public runs to evaluate."),
    horizons: str = typer.Option("5,20", "--horizons", help="Comma-separated holding periods in trading days."),
    dry_run: bool = typer.Option(False, "--dry-run", help="List completed public runs without evaluating returns."),
):
    """Evaluate public analysis outcomes and benchmark alpha."""

    import os

    from tradingagents.site.outcome_worker import (
        evaluate_public_analysis_outcomes,
        summarize_analysis_outcome_results,
    )
    from tradingagents.storage import StorageRepository, create_storage_engine

    if not os.getenv("DATABASE_URL"):
        raise typer.BadParameter("DATABASE_URL is required for the analysis outcome worker")

    horizon_values = _parse_horizon_csv(horizons)
    repo = StorageRepository(create_storage_engine())
    if dry_run:
        runs = repo.list_public_analysis_runs(limit=limit)
        if not runs:
            console.print("[yellow]No completed public analysis runs.[/yellow]")
            return
        table = Table(title="Public Analysis Runs", box=box.SIMPLE_HEAD)
        table.add_column("ID")
        table.add_column("Ticker")
        table.add_column("Trade Date")
        table.add_column("Horizons")
        for run in runs:
            table.add_row(
                str(run["id"]),
                str(run["ticker_code"]),
                str(run["trade_date"]),
                ",".join(str(value) for value in horizon_values),
            )
        console.print(
            f"[cyan]Dry run[/cyan] {len(runs)} public runs x {len(horizon_values)} horizons = "
            f"{len(runs) * len(horizon_values)} outcome checks."
        )
        console.print(table)
        return

    results = evaluate_public_analysis_outcomes(repo, horizons=horizon_values, limit=limit)
    if not results:
        console.print("[yellow]No completed public analysis runs.[/yellow]")
        return
    summary = summarize_analysis_outcome_results(results)
    console.print(
        "[bold]Outcome summary[/bold] "
        f"results={summary['result_count']} completed={summary['completed_count']} "
        f"pending={summary['pending_count']} unavailable={summary['unavailable_count']} "
        f"skipped={summary['skipped_count']}"
    )
    if summary["average_alpha_return"] is not None:
        console.print(f"[bold]Average alpha[/bold] {float(summary['average_alpha_return']):.4f}")
    for result in results:
        if result.status == "completed":
            console.print(
                f"[green]Outcome[/green] {result.ticker_code} {result.horizon_days}d: "
                f"raw={result.raw_return:.4f} alpha={result.alpha_return:.4f}"
            )
        else:
            console.print(
                f"[yellow]{result.status}[/yellow] {result.ticker_code} {result.horizon_days}d: {result.error}"
            )


@app.command("screen")
def screen_command(
    markets: str = typer.Option("KOSPI,KOSDAQ", "--markets", help="Comma-separated markets: KOSPI, KOSDAQ."),
    top_n: int = typer.Option(20, "--top", min=1, max=50, help="Number of ranked candidates to print."),
    as_of_date: Optional[str] = typer.Option(None, "--date", help="Snapshot date YYYY-MM-DD (default: latest trading day)."),
    min_market_cap: Optional[float] = typer.Option(None, "--min-market-cap", help="Minimum market cap in KRW."),
    max_per: Optional[float] = typer.Option(None, "--max-per", help="Maximum PER to keep."),
    json_output: bool = typer.Option(False, "--json", help="Print the raw JSON payload instead of a table."),
):
    """Rank KOSPI/KOSDAQ candidates with the rule-based screener (no LLM, no orders)."""

    import json

    from tradingagents.site.screener_api import build_screener_payload

    payload = build_screener_payload(
        as_of_date=as_of_date,
        markets=markets,
        top_n=top_n,
        min_market_cap=min_market_cap,
        max_per=max_per,
    )
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False, default=str))
        return
    table = Table(title=f"Screener {payload['as_of_date']} ({', '.join(payload['markets'])})", box=box.SIMPLE_HEAD)
    for column in ("#", "Code", "Name", "Mkt", "Close", "Composite", "Mom20", "RSI", "Vol×", "Reasons"):
        table.add_column(column)
    for candidate in payload["candidates"]:
        factors = candidate["factors"]
        table.add_row(
            str(candidate["rank"]),
            candidate["code"],
            candidate["name"],
            candidate["market"],
            f"{candidate['close']:,.0f}",
            f"{factors['composite']:+.3f}",
            _fmt_pct(factors.get("momentum_20d")),
            _fmt_num(factors.get("rsi_14")),
            _fmt_num(factors.get("volume_surge")),
            ", ".join(candidate["reasons"][:3]),
        )
    console.print(table)
    console.print(
        f"[dim]universe={payload['universe_size']} prefiltered={payload['prefiltered_size']} scored={payload['scored_size']}[/dim]"
    )
    for notice in payload["notices"]:
        console.print(f"[yellow]{notice}[/yellow]")


@app.command("forecast")
def forecast_command(
    ticker: str = typer.Argument(..., help="Korean 6-digit ticker code, e.g. 005930."),
    horizon: int = typer.Option(20, "--horizon", min=1, max=60, help="Forecast horizon in trading days."),
    as_of_date: Optional[str] = typer.Option(None, "--date", help="As-of date YYYY-MM-DD."),
    backend: Optional[str] = typer.Option(None, "--backend", help="naive, timesfm, or auto (default from TRADINGAGENTS_FORECAST_BACKEND)."),
    json_output: bool = typer.Option(False, "--json", help="Print the raw JSON payload."),
):
    """Statistical close-price forecast (TimesFM when installed, naive fallback otherwise)."""

    import json

    from tradingagents.site.screener_api import build_forecast_payload

    payload = build_forecast_payload(ticker, as_of_date=as_of_date, horizon_days=horizon, backend=backend)
    if json_output:
        console.print_json(json.dumps(payload, ensure_ascii=False, default=str))
        return
    if payload["status"] != "available":
        console.print(f"[yellow]{payload['status']}[/yellow] ({payload.get('point_count', 0)} points)")
        return
    console.print(f"[bold]{payload['ticker']['name']} ({payload['ticker']['code']})[/bold] {payload['summary']}")
    factors = payload["factors"]
    console.print(f"factors: composite={factors['composite']:+.3f} labels={', '.join(factors['labels'])}")
    risk = payload["risk_metrics"]
    console.print(
        f"risk: vol={_fmt_num(risk.get('annualized_volatility'))} mdd={_fmt_pct(risk.get('max_drawdown'))} "
        f"VaR95={_fmt_pct(risk.get('value_at_risk_95'))} sharpe={_fmt_num(risk.get('sharpe_ratio'))}"
    )
    for notice in payload["notices"]:
        console.print(f"[yellow]{notice}[/yellow]")


@app.command("playbook")
def playbook_command(
    target: str = typer.Argument(..., help="Ticker code, company name, or sector to analyse, e.g. 005930 or 반도체."),
    prompts: Optional[str] = typer.Option(None, "--prompts", help="Comma-separated prompt ids (default: all 17)."),
    core_only: bool = typer.Option(False, "--core", help="Run only the operator's original ten prompts."),
    list_only: bool = typer.Option(False, "--list", help="List the playbook prompts and exit."),
    as_of_date: Optional[str] = typer.Option(None, "--date", help="As-of date YYYY-MM-DD for chart/forecast context."),
    output: Optional[Path] = typer.Option(None, "--output", help="Write results JSON to this path."),
    deep: bool = typer.Option(False, "--deep", help="Use the deep-think model instead of the quick-think model."),
):
    """Run the ten-step analysis playbook (market → diversification → risk → ... → global events)."""

    import json

    from tradingagents.harness import list_prompts, run_playbook
    from tradingagents.harness.tasks import llm_from_config

    if list_only:
        table = Table(title="Playbook prompts", box=box.SIMPLE_HEAD)
        table.add_column("#")
        table.add_column("id")
        table.add_column("title")
        table.add_column("placeholders")
        for prompt in list_prompts():
            marker = "" if prompt.order <= 10 else " (추가)"
            table.add_row(str(prompt.order), prompt.id, prompt.title + marker, ", ".join(prompt.placeholders) or "-")
        console.print(table)
        return

    context = _playbook_context(target, as_of_date)
    values = {"target": target, "strategy": "스크리너 후보 확인 후 손절/익절 규칙 기반 스윙", "financial_statements": target}
    prompt_ids = [item.strip() for item in prompts.split(",") if item.strip()] if prompts else None
    results = run_playbook(llm_from_config(deep=deep), values=values, context=context, prompt_ids=prompt_ids, extended=not core_only)
    for result in results:
        colour = "green" if result.status == "ok" else "red"
        console.print(f"[{colour}]{result.title}[/{colour}] {result.status}")
        if result.status == "ok":
            console.print(Markdown(f"> {result.data.get('summary', '')}"))
        elif result.error:
            console.print(f"  {result.error}")
    if output is not None:
        output.write_text(json.dumps([r.as_dict() for r in results], ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        console.print(f"[dim]saved {output}[/dim]")


@app.command("pipeline")
def pipeline_command(
    markets: str = typer.Option("KOSPI,KOSDAQ", "--markets", help="Comma-separated markets."),
    top_n: int = typer.Option(20, "--top", min=1, max=50, help="Screener candidates to consider."),
    confirm_top_n: int = typer.Option(5, "--confirm", min=1, max=20, help="How many candidates to send to the LLM gate."),
    as_of_date: Optional[str] = typer.Option(None, "--date", help="As-of date YYYY-MM-DD."),
    confirmer: str = typer.Option("playbook", "--confirmer", help="playbook, debate, graph, or none (deterministic only)."),
    broker: str = typer.Option("paper", "--broker", help="paper (local) or kis (KIS 모의투자/live via env gates)."),
    execute: bool = typer.Option(False, "--execute", help="Send orders. Default is a dry run that only logs intents."),
    confirm_live: bool = typer.Option(False, "--confirm-live", help="Required together with KIS_IS_PAPER=false and TRADINGAGENTS_ENABLE_LIVE_TRADING=true."),
    initial_cash: Optional[float] = typer.Option(None, "--cash", help="Paper broker starting cash (KRW). Defaults to the account's configured capital."),
    risk_per_trade: float = typer.Option(0.01, "--risk", help="Fraction of equity risked per trade."),
    audit_log: Optional[Path] = typer.Option(None, "--audit-log", help="Hash-chained JSONL ledger path (default TRADINGAGENTS_AUDIT_LOG_PATH)."),
    output: Optional[Path] = typer.Option(None, "--output", help="Write the run result JSON to this path."),
    persist: bool = typer.Option(False, "--persist", help="Store the run and decisions in DATABASE_URL (Supabase) for the /harness page."),
    debate_rounds: int = typer.Option(1, "--debate-rounds", min=1, max=3, help="Bull/bear rounds for --confirmer debate."),
    exits_only: bool = typer.Option(False, "--exits-only", help="Only close positions that hit a stop, target, or holding limit. No new entries."),
    news_check: bool = typer.Option(False, "--news-check", help="Also close a held position when recent news breaks the reason it was bought."),
    account: str = typer.Option("paper", "--account", help="Which book to trade: paper (AI confirmed), rules (rule score only), kis."),
):
    """Daily harness: screen → forecast → LLM confirm → size → mandate gate → order."""

    import json
    import os

    from tradingagents.execution import AuditLedger, KISBrokerAdapter, KISConfig, KoreaTradingRules
    from tradingagents.harness import PipelineConfig, run_daily_pipeline
    from tradingagents.harness.pipeline import debate_confirmer, graph_confirmer, playbook_confirmer
    from tradingagents.harness.tasks import llm_from_config
    from tradingagents.screener import ScreenerConfig

    from tradingagents.harness.paper_state import default_initial_cash

    initial_cash = default_initial_cash() if initial_cash is None else initial_cash
    market_tuple = tuple(part.strip().upper() for part in markets.split(",") if part.strip())
    config = PipelineConfig(
        markets=market_tuple,
        screener=ScreenerConfig(markets=market_tuple, top_n=top_n),
        confirm_top_n=confirm_top_n,
        risk_percent_per_trade=risk_per_trade,
        initial_cash=initial_cash,
        dry_run=not execute,
        exits_only=exits_only,
        account_key=account.strip().lower() or "paper",
        require_llm_confirmation=confirmer.lower() != "none",
    )
    selected_confirmer = None
    if exits_only:
        confirmer = "none"  # no candidate is confirmed on an exits-only pass
    if confirmer.lower() == "playbook":
        selected_confirmer = playbook_confirmer(llm_from_config())
    elif confirmer.lower() == "debate":
        selected_confirmer = debate_confirmer(llm_from_config(), rounds=debate_rounds)
    elif confirmer.lower() == "graph":
        def _graph_factory(harness_context: str = ""):
            return TradingAgentsGraph(config={**DEFAULT_CONFIG, "harness_context": harness_context})

        selected_confirmer = graph_confirmer(_graph_factory, trade_date=as_of_date)
    elif confirmer.lower() != "none":
        raise typer.BadParameter("--confirmer must be playbook, debate, graph, or none")

    repo = None
    if persist:
        from tradingagents.storage import StorageRepository, create_storage_engine

        if not os.getenv("DATABASE_URL"):
            raise typer.BadParameter("--persist requires DATABASE_URL")
        repo = StorageRepository(create_storage_engine())

    broker_adapter = None
    restore_notes: list[str] = []
    if broker.lower() == "paper" and execute and repo is not None and config.account_key != "kis":
        from tradingagents.harness.paper_state import restore_paper_account

        broker_adapter, restore_notes = restore_paper_account(
            repo,
            initial_cash=initial_cash,
            max_position_weight=config.max_position_weight,
            account_key=config.account_key,
        )
        for note in restore_notes:
            console.print(f"[dim]{note}[/dim]")
    if broker.lower() == "kis":
        kis_config = KISConfig.from_env()
        errors = kis_config.validation_errors()
        if errors:
            raise typer.BadParameter("; ".join(errors))
        broker_adapter = KISBrokerAdapter(config=kis_config, confirm_live=confirm_live, execution_rules=KoreaTradingRules())
        console.print(f"[bold]KIS broker[/bold] mode={'모의투자(paper)' if broker_adapter.is_paper else 'LIVE'}")
    elif broker.lower() != "paper":
        raise typer.BadParameter("--broker must be paper or kis")

    held_prices: dict[str, float] = {}
    if broker_adapter is not None and getattr(broker_adapter, "name", "") == "paper":
        held = sorted(getattr(broker_adapter, "broker").portfolio.positions)
        if held:
            # exits compare today's price with the average cost, and the paper
            # broker has no quote feed of its own
            from tradingagents.site.market_api import build_latest_prices_payload

            try:
                payload = build_latest_prices_payload(held, ignore_errors=True, max_tickers=max(len(held), 1))
                for code, item in (payload.get("prices") or {}).items():
                    price = item.get("close")
                    if price:
                        held_prices[str(code)] = float(price)
            except Exception as exc:
                console.print(f"[yellow]held-position prices unavailable ({exc.__class__.__name__}); exits skipped this run[/yellow]")
            console.print(f"[dim]priced {len(held_prices)}/{len(held)} holding(s) for exit checks[/dim]")

    risk_checker = None
    held_names: dict[str, str] = {}
    if broker_adapter is not None and getattr(broker_adapter, "name", "") == "paper":
        held = sorted(getattr(broker_adapter, "broker").portfolio.positions)
        if held:
            try:
                from tradingagents.dataflows.kr_ticker_directory import lookup_directory

                for code in held:
                    entry = lookup_directory(code)
                    if entry is not None:
                        held_names[code] = entry.name
            except Exception:
                held_names = {}
    if news_check:
        from tradingagents.harness.news_guard import build_news_risk_checker
        from tradingagents.harness.tasks import llm_from_config

        risk_checker = build_news_risk_checker(llm_from_config())
        console.print("[dim]news check enabled for held positions[/dim]")

    ledger = AuditLedger(audit_log) if audit_log else AuditLedger.from_env()
    result = run_daily_pipeline(
        as_of_date,
        config=config,
        confirmer=selected_confirmer,
        broker=broker_adapter,
        ledger=ledger,
        repo=repo,
        current_prices=held_prices or None,
        confirmer_name=confirmer.lower(),
        risk_checker=risk_checker,
        held_names=held_names or None,
    )
    if result.run_id:
        console.print(f"[dim]persisted harness_run_id={result.run_id} → /harness/{result.run_id}[/dim]")

    console.print(
        f"[bold]Pipeline {result.as_of_date}[/bold] broker={result.broker} mode={result.mode} "
        f"dry_run={result.dry_run} candidates={result.screener['candidate_count']}"
    )
    table = Table(box=box.SIMPLE_HEAD)
    for column in ("Code", "Name", "Stage", "Qty", "Order", "Reasons"):
        table.add_column(column)
    for decision in result.decisions:
        table.add_row(
            decision.code,
            decision.name,
            decision.stage,
            str((decision.sizing or {}).get("quantity") or (decision.order or {}).get("order", {}).get("quantity") or ""),
            str((decision.order or {}).get("status") or ""),
            "; ".join(decision.reasons)[:80],
        )
    console.print(table)
    console.print(f"cash {result.account_before['cash']:,.0f} → {result.account_after['cash']:,.0f} KRW")
    console.print(f"[dim]audit {ledger.path} seq {result.audit_sequence_start}-{result.audit_sequence_end}[/dim]")
    for note in result.notes:
        console.print(f"[yellow]{note}[/yellow]")
    if output is not None:
        output.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        console.print(f"[dim]saved {output}[/dim]")


@app.command("reconcile-kis-fills")
def reconcile_kis_fills_command(
    days: int = typer.Option(5, "--days", min=1, max=30, help="How many days back to ask KIS about."),
):
    """Replace accepted KIS 모의투자 orders with the fills KIS actually recorded."""

    import os

    from tradingagents.execution import KISConfig
    from tradingagents.execution.kis_client import KISClient
    from tradingagents.site.kis_reconcile import reconcile_kis_fills
    from tradingagents.storage import StorageRepository, create_storage_engine

    if not os.getenv("DATABASE_URL"):
        raise typer.BadParameter("DATABASE_URL is required to reconcile fills")
    config = KISConfig.from_env()
    errors = config.validation_errors()
    if errors:
        raise typer.BadParameter("; ".join(errors))

    repo = StorageRepository(create_storage_engine())
    result = reconcile_kis_fills(repo, KISClient(config), lookback_days=days)
    status = result.get("status")
    if status == "reconciled":
        console.print(
            f"[green]reconciled {result['reconciled']}[/green] · 부분체결 {result.get('partial')} · "
            f"미체결 {result.get('unfilled')} · 대조 실패 {result.get('unmatched')} (주문 {result.get('broker_rows')}건 조회)"
        )
        return
    console.print(f"[yellow]{status}: {result.get('error') or ''} (대기 {result.get('pending', 0)}건)[/yellow]")


@app.command("record-paper-snapshot")
def record_paper_snapshot_command(
    as_of: Optional[str] = typer.Option(None, "--date", help="Snapshot date YYYY-MM-DD (default: today KST)."),
    initial_cash: Optional[float] = typer.Option(None, "--cash", help="Starting cash the account is measured against."),
    account: Optional[str] = typer.Option(None, "--account", help="Record one account (paper, rules, kis). Default: all of them."),
):
    """Record one day of each paper account with the KOSPI close beside it."""

    import os

    from tradingagents.site.paper_snapshot_worker import record_paper_account_snapshot
    from tradingagents.storage import StorageRepository, create_storage_engine

    if not os.getenv("DATABASE_URL"):
        raise typer.BadParameter("DATABASE_URL is required to record account snapshots")

    repo = StorageRepository(create_storage_engine())
    if not account:
        from tradingagents.site.paper_snapshot_worker import record_all_account_snapshots

        summary = record_all_account_snapshots(repo, as_of=as_of)
        for key, value in (summary.get("accounts") or {}).items():
            console.print(f"[dim]{key}[/dim] {value.get('status')} equity={value.get('equity')} positions={value.get('position_count')}")
        return
    result = record_paper_account_snapshot(repo, as_of=as_of, initial_cash=initial_cash, account_key=account.strip().lower())
    if result.get("status") != "recorded":
        console.print(f"[yellow]{result.get('status')}: {result.get('error') or ''}[/yellow]")
        return
    console.print(
        f"[green]{result['snapshot_date']}[/green] equity {result.get('equity'):,.0f} "
        f"return {(result.get('total_return') or 0) * 100:+.2f}% "
        f"benchmark {result.get('benchmark_close')} positions {result.get('position_count')}"
    )
    for note in result.get("notes") or []:
        console.print(f"[yellow]{note}[/yellow]")


@app.command("process-harness-outcomes")
def process_harness_outcomes_command(
    limit: int = typer.Option(50, "--limit", min=1, max=200, help="Maximum harness picks to evaluate."),
    horizons: str = typer.Option("5,20", "--horizons", help="Comma-separated holding periods in trading days."),
    dry_run: bool = typer.Option(False, "--dry-run", help="List harness picks without fetching returns."),
):
    """Evaluate 5D/20D realised returns and benchmark alpha for harness picks (stage=ordered)."""

    import os

    from tradingagents.site.harness_outcome_worker import evaluate_harness_outcomes, summarize_harness_outcome_results
    from tradingagents.storage import StorageRepository, create_storage_engine

    if not os.getenv("DATABASE_URL"):
        raise typer.BadParameter("DATABASE_URL is required for the harness outcome worker")
    horizon_values = _parse_horizon_csv(horizons)
    repo = StorageRepository(create_storage_engine())
    if dry_run:
        decisions = repo.list_harness_decisions_for_outcomes(limit=limit)
        if not decisions:
            console.print("[yellow]No harness picks (stage=ordered) to evaluate.[/yellow]")
            return
        table = Table(title="Harness picks", box=box.SIMPLE_HEAD)
        for column in ("Decision", "Ticker", "Entry", "Rating", "Existing outcomes"):
            table.add_column(column)
        for decision in decisions:
            table.add_row(str(decision["id"])[:8], str(decision["ticker_code"]), str(decision["as_of_date"]), str(decision.get("confirmation_rating") or "-"), str(len(decision.get("outcomes") or [])))
        console.print(table)
        return
    results = evaluate_harness_outcomes(repo, horizons=horizon_values, limit=limit)
    summary = summarize_harness_outcome_results(results)
    console.print(
        f"[bold]Harness outcomes[/bold] results={summary['result_count']} completed={summary['completed_count']} "
        f"pending={summary['pending_count']} unavailable={summary['unavailable_count']} skipped={summary['skipped_count']}"
    )
    if summary["hit_rate"] is not None:
        console.print(f"hit rate {summary['hit_rate']:.1%} · average alpha {summary['average_alpha_return']:+.4f}")
    for result in results:
        colour = {"completed": "green", "pending": "yellow", "skipped": "dim"}.get(result.status, "red")
        detail = f"raw={result.raw_return:+.4f} alpha={result.alpha_return:+.4f}" if result.status == "completed" else (result.error or "")
        console.print(f"[{colour}]{result.status}[/{colour}] {result.ticker_code} {result.horizon_days}d: {detail}")


@app.command("backtest")
def backtest_command(
    years: float = typer.Option(3.0, "--years", min=0.25, max=10.0, help="How far back to replay."),
    universe: int = typer.Option(180, "--universe", min=10, max=400, help="How many of today's most liquid names to replay."),
    top_n: int = typer.Option(5, "--top", min=1, max=20, help="Names bought per day, as in the live run."),
    cash: float = typer.Option(50_000_000.0, "--cash", help="Starting capital."),
    label: str = typer.Option("rules", "--label", help="Which replay this is."),
    persist: bool = typer.Option(False, "--persist", help="Store the result for the site."),
    output: Optional[Path] = typer.Option(None, "--output", help="Write the full result JSON here."),
):
    """Replay the screening rules over past prices and report what they would have done."""

    import json
    import os
    from datetime import date, timedelta

    from tradingagents.dataflows.chart_data import get_ohlcv_chart_series
    from tradingagents.harness.backtest import BacktestConfig, run_rule_backtest
    from tradingagents.screener.universe import load_naver_market_snapshot

    end = date.today()
    start = end - timedelta(days=int(years * 365))
    fetch_start = (start - timedelta(days=260)).isoformat()  # the score needs history before day one

    console.print(f"[bold]Backtest[/bold] {start} → {end} · universe {universe} · top {top_n}")
    import time as _time

    names: dict[str, str] = {}
    for attempt in range(1, 4):
        try:
            snapshot = load_naver_market_snapshot(markets=("KOSPI", "KOSDAQ"), max_rows_per_market=max(universe, 200))
            rows = sorted(snapshot.rows, key=lambda row: float(row.trading_value or 0), reverse=True)[:universe]
            names = {row.code: row.name for row in rows}
            if names:
                console.print(f"[dim]universe: {len(names)} names by traded value[/dim]")
                break
        except Exception as exc:
            console.print(f"[yellow]universe attempt {attempt} failed ({exc.__class__.__name__})[/yellow]")
        _time.sleep(5 * attempt)
    if not names:
        # The vendor rate-limits; the stored directory still names the market.
        from tradingagents.dataflows.kr_ticker_directory import load_directory

        entries = [entry for entry in load_directory() if entry.sector and "ETF" not in entry.name.upper()]
        names = {entry.code: entry.name for entry in entries[:universe]}
        console.print(f"[yellow]universe from the stored directory: {len(names)} names (not ranked by liquidity)[/yellow]")
    if not names:
        raise typer.BadParameter("no universe could be resolved")

    history: dict[str, list[dict]] = {}
    failures = 0
    for index, code in enumerate(names, start=1):
        try:
            series = get_ohlcv_chart_series(code, fetch_start, end.isoformat(), vendor="pykrx")
            history[code] = [point.as_dict() for point in series.points]
        except Exception:
            failures += 1
        if index % 25 == 0:
            console.print(f"[dim]  history {index}/{len(names)} (실패 {failures})[/dim]")
    if not history:
        raise typer.BadParameter("no price history could be fetched")

    benchmark = {}
    try:
        from tradingagents.dataflows.kr_returns import fetch_benchmark_close

        for point in history[next(iter(history))]:
            day = str(point.get("date"))[:10]
            if day:
                benchmark.setdefault(day, None)
        benchmark = {}
        start_close = fetch_benchmark_close(on_date=start.isoformat())
        end_close = fetch_benchmark_close(on_date=end.isoformat())
        if start_close and end_close:
            benchmark = {start.isoformat(): start_close, end.isoformat(): end_close}
    except Exception:
        benchmark = {}

    def _sector(code: str) -> str:
        from tradingagents.dataflows.kr_ticker_directory import sector_of

        return sector_of(code)

    result = run_rule_backtest(
        history=history,
        names=names,
        start=start,
        end=end,
        config=BacktestConfig(top_n=top_n, initial_cash=cash),
        sector_lookup=_sector,
        benchmark=benchmark or None,
    )
    metrics = result.metrics
    console.print(
        f"[green]{result.start_date} → {result.end_date}[/green] "
        f"수익률 {(metrics.get('total_return') or 0) * 100:+.2f}% · "
        f"최대낙폭 {(metrics.get('max_drawdown') or 0) * 100:.2f}% · "
        f"샤프 {metrics.get('sharpe_ratio')} · 거래 {metrics.get('trade_count')}건 · 승률 {metrics.get('hit_rate')}"
    )
    for note in result.notes:
        console.print(f"[yellow]{note}[/yellow]")

    if output is not None:
        output.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        console.print(f"[dim]saved {output}[/dim]")
    if persist:
        if not os.getenv("DATABASE_URL"):
            raise typer.BadParameter("--persist requires DATABASE_URL")
        from tradingagents.storage import StorageRepository, create_storage_engine

        repo = StorageRepository(create_storage_engine())
        run_id = repo.save_backtest_run(result.as_dict(), label=label)
        console.print(f"[dim]persisted backtest_run_id={run_id}[/dim]")


@app.command("audit-verify")
def audit_verify_command(
    path: Optional[Path] = typer.Option(None, "--path", help="Ledger path (default TRADINGAGENTS_AUDIT_LOG_PATH)."),
):
    """Verify the hash chain of the harness audit ledger."""

    from tradingagents.execution import AuditLedger

    ledger = AuditLedger(path) if path else AuditLedger.from_env()
    ok, error = ledger.verify_chain()
    if ok:
        console.print(f"[green]OK[/green] {ledger.path} records={ledger.sequence}")
    else:
        console.print(f"[red]BROKEN[/red] {ledger.path}: {error}")
        raise typer.Exit(code=1)


def _playbook_context(target: str, as_of_date: Optional[str]) -> dict:
    """Best-effort deterministic context for playbook prompts (chart/forecast/risk)."""

    from tradingagents.dataflows.kr_tickers import is_kr_ticker
    from tradingagents.site.screener_api import build_forecast_payload

    context: dict = {}
    if is_kr_ticker(target):
        try:
            forecast_payload = build_forecast_payload(target, as_of_date=as_of_date, horizon_days=20)
        except Exception as exc:  # pragma: no cover - network dependent
            context["forecast_error"] = f"{exc.__class__.__name__}: {exc}"
        else:
            context["forecast"] = forecast_payload.get("forecast")
            context["factors"] = forecast_payload.get("factors")
            context["risk_metrics"] = forecast_payload.get("risk_metrics")
            context["snapshot"] = forecast_payload.get("ticker")
    return context


def _fmt_pct(value) -> str:
    return "-" if value is None else f"{float(value) * 100:+.1f}%"


def _fmt_num(value) -> str:
    return "-" if value is None else f"{float(value):.2f}"


def _parse_horizon_csv(value: str) -> tuple[int, ...]:
    try:
        horizons = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise typer.BadParameter("--horizons must contain comma-separated integers") from exc
    if not horizons:
        raise typer.BadParameter("--horizons must include at least one value")
    if any(horizon <= 0 for horizon in horizons):
        raise typer.BadParameter("--horizons values must be positive")
    return horizons


if __name__ == "__main__":
    app()
