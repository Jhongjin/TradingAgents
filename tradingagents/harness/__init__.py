"""Analysis harness: the ten-step playbook and the daily trading pipeline.

The playbook (``prompts.py``) encodes the ten Korean analysis prompts the
operator specified (market analysis, diversification, risk management,
technical analysis, economic indicators, value investing, sentiment,
financial statements, growth vs dividend, global events). ``tasks.py`` runs
them against any LLM with structured JSON output. ``pipeline.py`` wires the
deterministic screener, the forecaster, the multi-agent graph, the mandate
gate, and the broker adapter into one auditable cycle:

    screen → forecast → confirm (LLM) → size → mandate gate → order (paper/KIS 모의투자)

The LLM is a confirmation gate, not the origin of the trade idea (Binance-
Agent). Risk sizing precedes execution (AutoHedge). Every step is appended to
the hash-chained audit ledger (Vibe-Trading).
"""

from .debate import DebateOutcome, DebateTurn, build_harness_context_text, run_debate
from .pipeline import (
    PipelineConfig,
    PipelineDecision,
    PipelineRunResult,
    run_daily_pipeline,
)
from .prompts import PLAYBOOK, PlaybookPrompt, get_prompt, list_prompts, render_prompt
from .tasks import HarnessTask, HarnessTaskResult, run_playbook, run_task

__all__ = [
    "DebateOutcome",
    "DebateTurn",
    "HarnessTask",
    "build_harness_context_text",
    "run_debate",
    "HarnessTaskResult",
    "PLAYBOOK",
    "PipelineConfig",
    "PipelineDecision",
    "PipelineRunResult",
    "PlaybookPrompt",
    "get_prompt",
    "list_prompts",
    "render_prompt",
    "run_daily_pipeline",
    "run_playbook",
    "run_task",
]
