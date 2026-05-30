# TradingAgents/graph/trading_graph.py

import logging
import os
from pathlib import Path
import json
from datetime import date, datetime, timedelta
from typing import Dict, Any, Tuple, List, Optional

import yfinance as yf

logger = logging.getLogger(__name__)

from langgraph.prebuilt import ToolNode

from tradingagents.llm_clients import create_llm_client

from tradingagents.agents import *
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.agents.utils.agent_states import (
    AgentState,
    InvestDebateState,
    RiskDebateState,
)
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker, to_yfinance_symbol
from tradingagents.dataflows.kr_returns import fetch_korean_returns
from tradingagents.execution.signals import signal_from_decision
from tradingagents.report_quality import evaluate_report_quality
from tradingagents.storage import (
    AgentReportInput,
    AnalysisRunInput,
    StorageRepository,
    TradeDecisionInput,
    create_storage_engine,
)

# Import the new abstract tool methods from agent_utils
from tradingagents.agents.utils.agent_utils import (
    get_stock_data,
    get_indicators,
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement,
    get_news,
    get_insider_transactions,
    get_global_news
)

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .setup import GraphSetup
from .propagation import Propagator
from .reflection import Reflector
from .signal_processing import SignalProcessor


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=["market", "social", "news", "fundamentals"],
        debug=False,
        config: Dict[str, Any] = None,
        callbacks: Optional[List] = None,
    ):
        """Initialize the trading agents graph and components.

        Args:
            selected_analysts: List of analyst types to include
            debug: Whether to run in debug mode
            config: Configuration dictionary. If None, uses default config
            callbacks: Optional list of callback handlers (e.g., for tracking LLM/tool stats)
        """
        self.debug = debug
        self.selected_analysts = selected_analysts
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []

        # Update the interface's config
        set_config(self.config)

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        # Initialize LLMs with provider-specific thinking configuration
        llm_kwargs = self._get_provider_kwargs()

        # Add callbacks to kwargs if provided (passed to LLM constructor)
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()
        
        self.memory_log = TradingMemoryLog(self.config)
        self.storage_repo = self._create_storage_repository()

        # Create tool nodes
        self.tool_nodes = self._create_tool_nodes()

        # Initialize components
        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
        )

        self.propagator = Propagator()
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        # State tracking
        self.curr_state = None
        self.ticker = None
        self.last_analysis_run_id = None
        self.log_states_dict = {}  # date to full state dict

        # Set up the graph: keep the workflow for recompilation with a checkpointer.
        self.workflow = self.graph_setup.setup_graph(selected_analysts)
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None

    def _get_provider_kwargs(self) -> Dict[str, Any]:
        """Get provider-specific kwargs for LLM client creation."""
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level

        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort

        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort

        return kwargs

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        """Create tool nodes for different data sources using abstract methods."""
        return {
            "market": ToolNode(
                [
                    # Core stock data tools
                    get_stock_data,
                    # Technical indicators
                    get_indicators,
                ]
            ),
            "social": ToolNode(
                [
                    # News tools for social media analysis
                    get_news,
                ]
            ),
            "news": ToolNode(
                [
                    # News and insider information
                    get_news,
                    get_global_news,
                    get_insider_transactions,
                ]
            ),
            "fundamentals": ToolNode(
                [
                    # Fundamental analysis tools
                    get_fundamentals,
                    get_balance_sheet,
                    get_cashflow,
                    get_income_statement,
                ]
            ),
        }

    def _create_storage_repository(self) -> StorageRepository | None:
        """Create the optional analysis storage repository."""

        if not self.config.get("storage_enabled"):
            return None

        try:
            repo = StorageRepository(
                create_storage_engine(
                    self.config.get("database_url"),
                    echo=bool(self.config.get("storage_echo", False)),
                )
            )
            if self.config.get("storage_create_schema"):
                repo.create_schema()
            return repo
        except Exception as exc:
            logger.warning("Analysis storage is disabled after initialization failure: %s", exc)
            return None

    def _fetch_returns(
        self, ticker: str, trade_date: str, holding_days: int = 5
    ) -> Tuple[Optional[float], Optional[float], Optional[int]]:
        """Fetch raw and alpha return for ticker over holding_days from trade_date.

        Returns (raw_return, alpha_return, actual_holding_days) or
        (None, None, None) if price data is unavailable (too recent, delisted,
        or network error).
        """
        try:
            if is_kr_ticker(ticker):
                try:
                    korean_returns = fetch_korean_returns(ticker, trade_date, holding_days)
                    if korean_returns[0] is not None:
                        return korean_returns
                    logger.info(
                        "pykrx returns were unavailable for %s on %s; falling back to yfinance",
                        ticker,
                        trade_date,
                    )
                except Exception as exc:
                    logger.info(
                        "Could not fetch pykrx returns for %s on %s; falling back to yfinance: %s",
                        ticker,
                        trade_date,
                        exc,
                    )

            start = datetime.strptime(trade_date, "%Y-%m-%d")
            end = start + timedelta(days=holding_days + 7)  # buffer for weekends/holidays
            end_str = end.strftime("%Y-%m-%d")

            stock_symbol = TradingAgentsGraph._history_symbol_for_returns(self, ticker)
            benchmark_symbol = TradingAgentsGraph._benchmark_symbol_for_returns(self, ticker)
            stock = yf.Ticker(stock_symbol).history(start=trade_date, end=end_str)
            benchmark = yf.Ticker(benchmark_symbol).history(start=trade_date, end=end_str)

            if len(stock) < 2 or len(benchmark) < 2:
                return None, None, None

            actual_days = min(holding_days, len(stock) - 1, len(benchmark) - 1)
            raw = float(
                (stock["Close"].iloc[actual_days] - stock["Close"].iloc[0])
                / stock["Close"].iloc[0]
            )
            benchmark_ret = float(
                (benchmark["Close"].iloc[actual_days] - benchmark["Close"].iloc[0])
                / benchmark["Close"].iloc[0]
            )
            alpha = raw - benchmark_ret
            return raw, alpha, actual_days
        except Exception as e:
            logger.warning(
                "Could not resolve outcome for %s on %s (will retry next run): %s",
                ticker, trade_date, e,
            )
            return None, None, None

    def _history_symbol_for_returns(self, ticker: str) -> str:
        """Return a yfinance-compatible symbol for deferred outcome checks."""
        if is_kr_ticker(ticker):
            return to_yfinance_symbol(ticker)
        return ticker

    def _benchmark_symbol_for_returns(self, ticker: str) -> str:
        cfg = getattr(self, "config", None)
        if not isinstance(cfg, dict):
            cfg = DEFAULT_CONFIG
        if cfg.get("benchmark_symbol"):
            return cfg["benchmark_symbol"]
        if is_kr_ticker(ticker):
            resolved = resolve_kr_ticker(ticker, lookup_pykrx=False)
            korea_cfg = cfg.get("korea", {}) if isinstance(cfg.get("korea"), dict) else {}
            by_market = korea_cfg.get("benchmark_by_market", {})
            return by_market.get(resolved.market, resolved.benchmark_symbol)
        return "SPY"

    def _resolve_pending_entries(self, ticker: str) -> None:
        """Resolve pending log entries for ticker at the start of a new run.

        Fetches returns for each same-ticker pending entry, generates reflections,
        then writes all updates in a single atomic batch write to avoid redundant I/O.
        Skips entries whose price data is not yet available (too recent or delisted).

        Trade-off: only same-ticker entries are resolved per run.  Entries for
        other tickers accumulate until that ticker is run again.
        """
        pending = [e for e in self.memory_log.get_pending_entries() if e["ticker"] == ticker]
        if not pending:
            return

        updates = []
        for entry in pending:
            raw, alpha, days = self._fetch_returns(ticker, entry["date"])
            if raw is None:
                continue  # price not available yet — try again next run
            reflection = self.reflector.reflect_on_final_decision(
                final_decision=entry.get("decision", ""),
                raw_return=raw,
                alpha_return=alpha,
            )
            updates.append({
                "ticker": ticker,
                "trade_date": entry["date"],
                "raw_return": raw,
                "alpha_return": alpha,
                "holding_days": days,
                "reflection": reflection,
            })

        if updates:
            self.memory_log.batch_update_with_outcomes(updates)

    def propagate(self, company_name, trade_date):
        """Run the trading agents graph for a company on a specific date.

        When ``checkpoint_enabled`` is set in config, the graph is recompiled
        with a per-ticker SqliteSaver so a crashed run can resume from the last
        successful node on a subsequent invocation with the same ticker+date.
        """
        self.ticker = company_name

        # Resolve any pending memory-log entries for this ticker before the pipeline runs.
        self._resolve_pending_entries(company_name)

        # Recompile with a checkpointer if the user opted in.
        if self.config.get("checkpoint_enabled"):
            self._checkpointer_ctx = get_checkpointer(
                self.config["data_cache_dir"], company_name
            )
            saver = self._checkpointer_ctx.__enter__()
            self.graph = self.workflow.compile(checkpointer=saver)

            step = checkpoint_step(
                self.config["data_cache_dir"], company_name, str(trade_date)
            )
            if step is not None:
                logger.info(
                    "Resuming from step %d for %s on %s", step, company_name, trade_date
                )
            else:
                logger.info("Starting fresh for %s on %s", company_name, trade_date)

        try:
            return self._run_graph(company_name, trade_date)
        finally:
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()

    def _run_graph(self, company_name, trade_date):
        """Execute the graph and write the resulting state to disk and memory log."""
        # Initialize state — inject memory log context for PM.
        past_context = self.memory_log.get_past_context(company_name)
        paper_learning_context = str(self.config.get("paper_learning_context") or "").strip()
        if paper_learning_context:
            past_context = "\n\n".join(
                part for part in (past_context, paper_learning_context) if part
            )
        init_agent_state = self.propagator.create_initial_state(
            company_name, trade_date, past_context=past_context
        )
        args = self.propagator.get_graph_args()

        # Inject thread_id so same ticker+date resumes, different date starts fresh.
        if self.config.get("checkpoint_enabled"):
            tid = thread_id(company_name, str(trade_date))
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid

        if self.debug:
            trace = []
            for chunk in self.graph.stream(init_agent_state, **args):
                if len(chunk["messages"]) == 0:
                    pass
                else:
                    chunk["messages"][-1].pretty_print()
                    trace.append(chunk)
            final_state = trace[-1]
        else:
            final_state = self.graph.invoke(init_agent_state, **args)

        # Store current state for reflection.
        self.curr_state = final_state

        # Log state to disk.
        self._log_state(trade_date, final_state)

        # Store decision for deferred reflection on the next same-ticker run.
        self.memory_log.store_decision(
            ticker=company_name,
            trade_date=trade_date,
            final_trade_decision=final_state["final_trade_decision"],
        )

        self._persist_analysis_run(final_state, trade_date)

        # Clear checkpoint on successful completion to avoid stale state.
        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config["data_cache_dir"], company_name, str(trade_date)
            )

        return final_state, self.process_signal(final_state["final_trade_decision"])

    def _persist_analysis_run(self, final_state: Dict[str, Any], trade_date: Any) -> str | None:
        """Persist a completed analysis run for the optional public web layer."""

        repo = getattr(self, "storage_repo", None)
        if repo is None:
            return None

        run_id = None
        try:
            company = str(
                final_state.get("company_of_interest")
                or getattr(self, "ticker", None)
                or ""
            ).strip()
            ticker_code, ticker_name, market = self._storage_ticker_fields(company)
            run_id = repo.create_analysis_run(
                AnalysisRunInput(
                    ticker_code=ticker_code,
                    ticker_name=ticker_name,
                    market=market,
                    trade_date=self._storage_trade_date(trade_date),
                    status="pending",
                    visibility=self.config.get("analysis_visibility", "public"),
                    user_id=self.config.get("analysis_user_id"),
                    model_provider=self.config.get("llm_provider"),
                    deep_model=self.config.get("deep_think_llm"),
                    quick_model=self.config.get("quick_think_llm"),
                    metadata={
                        "source": "trading_graph",
                        "currency": self.config.get("currency"),
                        "output_language": self.config.get("output_language"),
                        "selected_analysts": list(getattr(self, "selected_analysts", [])),
                    },
                )
            )

            run_context = {
                "ticker_code": ticker_code,
                "ticker_name": ticker_name,
                "market": market,
                "trade_date": self._storage_trade_date(trade_date),
            }
            for role, title, content in self._storage_report_items(final_state):
                if content is None:
                    continue
                rendered = self._stringify_report_content(content)
                if not rendered.strip():
                    continue
                report_context = {"role": role, "title": title, "content": rendered}
                repo.add_agent_report(
                    AgentReportInput(
                        analysis_run_id=run_id,
                        role=role,
                        title=title,
                        content=rendered,
                        metadata={"quality_checks": evaluate_report_quality(report_context, run_context)},
                    )
                )

            raw_decision = str(final_state.get("final_trade_decision") or "")
            signal = signal_from_decision(ticker_code, raw_decision)
            repo.record_trade_decision(
                TradeDecisionInput(
                    analysis_run_id=run_id,
                    rating=signal.rating,
                    action=signal.action,
                    target_weight=signal.target_weight,
                    rationale=signal.rationale,
                    raw_decision=raw_decision,
                )
            )
            repo.complete_analysis_run(run_id)
            self.last_analysis_run_id = run_id
            return run_id
        except Exception as exc:
            if run_id:
                try:
                    repo.complete_analysis_run(run_id, status="failed")
                except Exception:
                    pass
            logger.warning("Could not persist completed analysis run: %s", exc)
            return None

    def _storage_ticker_fields(self, company: str) -> tuple[str, str, str]:
        if is_kr_ticker(company):
            resolved = resolve_kr_ticker(company, lookup_pykrx=False)
            return resolved.code, resolved.name, resolved.market

        ticker_code = company.upper()
        market = str(self.config.get("market") or "US").upper()
        if market == "KR":
            market = "US"
        return ticker_code, company, market

    @staticmethod
    def _storage_trade_date(value: Any) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return datetime.strptime(str(value), "%Y-%m-%d").date()

    @staticmethod
    def _storage_report_items(final_state: Dict[str, Any]) -> list[tuple[str, str, Any]]:
        return [
            ("market", "Market report", final_state.get("market_report")),
            ("sentiment", "Sentiment report", final_state.get("sentiment_report")),
            ("news", "News report", final_state.get("news_report")),
            ("fundamentals", "Fundamentals report", final_state.get("fundamentals_report")),
            ("investment_debate", "Investment debate", final_state.get("investment_debate_state")),
            ("trader", "Trader investment plan", final_state.get("trader_investment_plan")),
            ("risk", "Risk debate", final_state.get("risk_debate_state")),
            ("investment_plan", "Research manager plan", final_state.get("investment_plan")),
        ]

    @staticmethod
    def _stringify_report_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False, default=str, indent=2)

    def _log_state(self, trade_date, final_state):
        """Log the final state to a JSON file."""
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state["company_of_interest"],
            "trade_date": final_state["trade_date"],
            "market_report": final_state["market_report"],
            "sentiment_report": final_state["sentiment_report"],
            "news_report": final_state["news_report"],
            "fundamentals_report": final_state["fundamentals_report"],
            "investment_debate_state": {
                "bull_history": final_state["investment_debate_state"]["bull_history"],
                "bear_history": final_state["investment_debate_state"]["bear_history"],
                "history": final_state["investment_debate_state"]["history"],
                "current_response": final_state["investment_debate_state"][
                    "current_response"
                ],
                "judge_decision": final_state["investment_debate_state"][
                    "judge_decision"
                ],
            },
            "trader_investment_decision": final_state["trader_investment_plan"],
            "risk_debate_state": {
                "aggressive_history": final_state["risk_debate_state"]["aggressive_history"],
                "conservative_history": final_state["risk_debate_state"]["conservative_history"],
                "neutral_history": final_state["risk_debate_state"]["neutral_history"],
                "history": final_state["risk_debate_state"]["history"],
                "judge_decision": final_state["risk_debate_state"]["judge_decision"],
            },
            "investment_plan": final_state["investment_plan"],
            "final_trade_decision": final_state["final_trade_decision"],
        }

        # Save to file. Reject ticker values that would escape the
        # results directory when joined as a path component.
        safe_ticker = safe_ticker_component(self.ticker)
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_states_dict[str(trade_date)], f, indent=4)

    def process_signal(self, full_signal):
        """Process a signal to extract the core decision."""
        return self.signal_processor.process_signal(full_signal)
