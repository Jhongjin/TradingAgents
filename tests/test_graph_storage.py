from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.storage import StorageRepository, create_storage_engine


def _repo() -> StorageRepository:
    repo = StorageRepository(create_storage_engine())
    repo.create_schema()
    return repo


def _graph(repo: StorageRepository | None) -> TradingAgentsGraph:
    graph = TradingAgentsGraph.__new__(TradingAgentsGraph)
    graph.storage_repo = repo
    graph.config = {
        "analysis_visibility": "public",
        "analysis_user_id": None,
        "llm_provider": "openai",
        "deep_think_llm": "gpt-5.4",
        "quick_think_llm": "gpt-5.4-mini",
        "currency": "KRW",
        "output_language": "Korean",
        "market": "KR",
    }
    graph.selected_analysts = ["market", "news", "fundamentals"]
    graph.ticker = "005930"
    graph.last_analysis_run_id = None
    return graph


def _final_state() -> dict:
    return {
        "company_of_interest": "005930",
        "trade_date": "2026-05-05",
        "market_report": "KRX OHLCV report",
        "sentiment_report": "Naver sentiment report",
        "news_report": "Naver news report",
        "fundamentals_report": "DART financial report",
        "investment_debate_state": {
            "bull_history": "bull",
            "bear_history": "bear",
            "history": "debate",
            "current_response": "response",
            "judge_decision": "judge",
        },
        "trader_investment_plan": "Trader plan",
        "risk_debate_state": {
            "aggressive_history": "aggressive",
            "conservative_history": "conservative",
            "neutral_history": "neutral",
            "history": "risk debate",
            "judge_decision": "risk judge",
        },
        "investment_plan": "Research plan",
        "final_trade_decision": "Rating: Buy\nIncrease exposure after risk review.",
    }


def test_trading_graph_persists_completed_analysis_run():
    repo = _repo()
    graph = _graph(repo)

    run_id = graph._persist_analysis_run(_final_state(), "2026-05-05")

    assert run_id is not None
    assert graph.last_analysis_run_id == run_id

    bundle = repo.get_analysis_bundle(run_id)
    assert bundle is not None
    assert bundle["run"]["ticker_code"] == "005930"
    assert bundle["run"]["ticker_name"] == "삼성전자"
    assert bundle["run"]["market"] == "KOSPI"
    assert bundle["run"]["status"] == "completed"
    assert bundle["run"]["model_provider"] == "openai"

    report_roles = {report["role"] for report in bundle["reports"]}
    assert {"market", "news", "fundamentals", "trader", "risk"} <= report_roles
    assert bundle["decision"]["rating"] == "Buy"
    assert bundle["decision"]["action"] == "increase"
    assert bundle["decision"]["target_weight"] == 0.25


def test_trading_graph_storage_hook_is_optional():
    graph = _graph(None)

    assert graph._persist_analysis_run(_final_state(), "2026-05-05") is None
    assert graph.last_analysis_run_id is None
