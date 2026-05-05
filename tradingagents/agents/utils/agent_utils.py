from langchain_core.messages import HumanMessage, RemoveMessage

# Import tools from separate utility files
from tradingagents.agents.utils.core_stock_tools import (
    get_stock_data
)
from tradingagents.agents.utils.technical_indicators_tools import (
    get_indicators
)
from tradingagents.agents.utils.fundamental_data_tools import (
    get_fundamentals,
    get_balance_sheet,
    get_cashflow,
    get_income_statement
)
from tradingagents.agents.utils.news_data_tools import (
    get_news,
    get_insider_transactions,
    get_global_news
)
from tradingagents.dataflows.kr_tickers import is_kr_ticker, resolve_kr_ticker


def get_language_instruction() -> str:
    """Return a prompt instruction for the configured output language.

    Returns empty string when English (default), so no extra tokens are used.
    Only applied to user-facing agents (analysts, portfolio manager).
    Internal debate agents stay in English for reasoning quality.
    """
    from tradingagents.dataflows.config import get_config
    lang = get_config().get("output_language", "English")
    if lang.strip().lower() == "english":
        return ""
    return f" Write your entire response in {lang}."


def build_instrument_context(ticker: str) -> str:
    """Describe the exact instrument so agents preserve exchange-qualified tickers."""
    if is_kr_ticker(ticker):
        resolved = resolve_kr_ticker(ticker, lookup_pykrx=False)
        return (
            f"The instrument to analyze is Korean stock `{resolved.code}` "
            f"({resolved.name}, {resolved.market}). Use this exact 6-digit "
            "Korean ticker code in every tool call. Market context: Korea "
            "Exchange (KRX), currency KRW, timezone Asia/Seoul, regular session "
            "09:00-15:30 KST. Prefer Korean-market evidence such as KRX/pykrx "
            "OHLCV, DART disclosures and financial statements, Naver news, "
            "foreign/institutional flow, short-sale context, upper/lower price "
            "limits, and KOSPI/KOSDAQ benchmark-relative performance."
        )
    return (
        f"The instrument to analyze is `{ticker}`. "
        "Use this exact ticker in every tool call, report, and recommendation, "
        "preserving any exchange suffix (e.g. `.TO`, `.L`, `.HK`, `.T`)."
    )

def create_msg_delete():
    def delete_messages(state):
        """Clear messages and add placeholder for Anthropic compatibility"""
        messages = state["messages"]

        # Remove all messages
        removal_operations = [RemoveMessage(id=m.id) for m in messages]

        # Add a minimal placeholder message
        placeholder = HumanMessage(content="Continue")

        return {"messages": removal_operations + [placeholder]}

    return delete_messages


        
