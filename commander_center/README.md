# TradingAgents Korea Commander Center

This folder is the operating room for turning TradingAgents Korea into a
trustworthy Korean-stock AI analysis platform. The Commander Center owns task
triage, parallel team briefings, launch gates, risk review, and evidence-based
quality decisions.

## Mission

Build a public Korean equity AI research service that users can trust because
every visible claim is supported by:

- traceable market, disclosure, news, and analysis data
- clear timestamps, source labels, and fallbacks
- measured 5-day and 20-day outcome tracking
- strict read-only boundaries with live trading disabled
- repeatable verification before commit, push, and deploy

## Operating Rule

The Commander Center is the single intake and dispatch layer. Every meaningful
task should be broken into a queue item, assigned to one or more specialist
workstreams, verified through gates, and closed with a short evidence note.

## Directory Map

- `OPERATING_SYSTEM.md`: commander workflow, queue states, and decision rules
- `TEAM.md`: best-team roster and responsibilities
- `QUEUE.md`: current cross-team backlog
- `GATES.md`: launch and release readiness gates
- `RISK_REGISTER.md`: active trust, security, data, and product risks
- `templates/`: reusable task, review, and incident templates
- `workstreams/`: specialist subprojects for parallel execution

## Non-Negotiables

- Do not edit `.env`.
- Do not commit API keys, passwords, tokens, account numbers, or secrets.
- Do not expose live trading, broker order placement, or one-click orders on
  the public site or API. Broker orders live only in the operator CLI harness
  (`tradingagents pipeline`): dry run by default, KIS 모의투자 before live, and
  live only behind `TRADINGAGENTS_ENABLE_LIVE_TRADING=true` + `--confirm-live`.
- Treat AI output as research content, not investment advice.
- Keep Korean-market accuracy and provenance ahead of visual polish.
- Preserve existing US-market fallback behavior unless a task explicitly says
  otherwise.

## Default Verification

Use the project-specific test environment when possible:

```powershell
$env:UV_PROJECT_ENVIRONMENT='.codex-test-venv'
uv run --with pytest pytest -q
```

If `uv.lock` changes only because `uv` adjusted the local test environment,
restore it before commit:

```powershell
git restore -- uv.lock
```

