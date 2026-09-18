"""What the serverless entry point drags in before it can answer anything.

Cold starts on Vercel were measured at 6 seconds on /harness, and 2.8s of that
was import time. Two modules were pulling in packages they only needed on one
code path. These hold that line.
"""

import subprocess
import sys


def _imports_after(module: str) -> set[str]:
    """The modules loaded by importing `module`, in a fresh interpreter."""

    code = (
        "import sys, json; "
        f"import {module}; "
        "print(json.dumps(sorted(sys.modules)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    import json

    return set(json.loads(out.stdout.strip().splitlines()[-1]))


def test_the_web_entry_point_does_not_build_the_agent_stack_to_start():
    """execution.signals wanted one regex helper and got all of tradingagents.agents."""

    loaded = _imports_after("tradingagents.execution.signals")
    assert "tradingagents.agents" not in loaded
    assert "tradingagents.agents.utils.rating" not in loaded


def test_reading_a_chart_does_not_import_yfinance_on_the_way_in():
    """Only non-Korean tickers reach yfinance, and this is a Korean-first site."""

    loaded = _imports_after("tradingagents.dataflows.chart_data")
    assert "yfinance" not in loaded


def test_the_helpers_that_moved_their_imports_still_work():
    from tradingagents.dataflows.stockstats_utils import yf_retry

    from yfinance.exceptions import YFRateLimitError

    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise YFRateLimitError()
        return "fine"

    assert yf_retry(flaky, max_retries=1, base_delay=0.001) == "fine"
    assert attempts["n"] == 2

    def other():
        raise ValueError("not a rate limit")

    try:
        yf_retry(other)
    except ValueError as exc:
        assert "not a rate limit" in str(exc)
    else:
        raise AssertionError("a non-rate-limit error must propagate immediately")


def test_the_cli_does_not_build_the_llm_graph_to_show_its_help():
    """Every desk, shorts and backtest run was paying 2.2s for a debate stack."""

    loaded = _imports_after("cli.main")
    assert "tradingagents.graph.trading_graph" not in loaded
    assert "langgraph.prebuilt" not in loaded
    assert "yfinance" not in loaded


def test_the_graph_commands_still_reach_the_graph():
    """A deferred import that is never reached is a broken command."""

    import inspect

    import cli.main as main

    source = inspect.getsource(main)
    lines = source.splitlines()
    uses = [i for i, line in enumerate(lines, 1) if "TradingAgentsGraph(" in line]
    imports = [i for i, line in enumerate(lines, 1) if "import TradingAgentsGraph" in line]

    assert uses and imports
    for use in uses:
        assert any(where < use for where in imports), f"line {use} uses it with no import above"
