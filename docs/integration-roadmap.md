# External Repo Integration Roadmap

This document records which ideas from the reviewed repositories were adopted,
where they live in this codebase, and what was deliberately left out. The
target workflow is:

```
스크리너(규칙) → 통계 예측 → AI 확인(하네스/멀티에이전트) → 리스크 사이징 → 만다트 게이트 → 주문(로컬 paper → KIS 모의투자 → 실계좌)
```

Korean market (KOSPI/KOSDAQ) is the only market wired end to end. US and
futures support stays on the existing yfinance/Alpha Vantage fallback path
until the Korean loop has accumulated paper results.

## Repo-by-repo

| Repo | What was adopted | Where |
|---|---|---|
| google-research/timesfm | Foundation-model price forecast (2.5 API, 3.0 API fallback), quantile bands, probability-up | `tradingagents/forecast/` (`TimesFMForecaster`, `NaiveForecaster` fallback), `get_price_forecast` agent tool, `/api/forecast/{ticker}`, `forecast` strategy lens |
| HKUDS/Vibe-Trading | Alpha-Zoo-style transparent factor screener, mandate/compliance gate, kill switch, hash-chained audit ledger, KRX rules (±30% limits, 0.20% tax already present) | `tradingagents/screener/`, `tradingagents/execution/mandate.py`, `tradingagents/execution/audit.py` |
| KattyFury/Binance-Agent | Deterministic scanner → AI confirmation gate → risk-sized order with stop/take-profit; fail-closed when the LLM is unavailable; `DRY_RUN` default; events log every cycle | `tradingagents/harness/pipeline.py`, `tradingagents/execution/position_sizing.py` |
| The-Swarm-Corporation/AutoHedge | Director → Quant → Risk → Execution sequencing with structured JSON outputs (technical_score, key_levels, risk score, order fields) | `tradingagents/harness/prompts.py` schemas, `playbook_confirmer` |
| Fincept-Corporation/FinceptTerminal | Institutional risk analytics (VaR/CVaR, Sharpe/Sortino, drawdown, beta), inverse-vol portfolio weights, uniform broker interface | `tradingagents/analytics/`, `tradingagents/execution/broker.py` |
| Jhongjin/TradingAgents | This repository's own remote; nothing to import | – |

Not adopted: Vibe-Trading's Electron/React desktop, FinceptTerminal's C++/Qt
shell, AutoHedge's Solana execution, Binance futures/OI data. They do not fit a
Korean cash-equity, serverless-friendly Python stack.

## The ten-step playbook

`tradingagents/harness/prompts.py` stores the operator's ten prompts verbatim
(시장 분석, 포트폴리오 다각화, 리스크 관리, 기술 분석, 경제 지표, 가치 투자,
시장 심리, 재무제표 해석, 성장주/배당주, 글로벌 이벤트). Each prompt has:

- bracket placeholders (`[업종 또는 주식]`) filled by `render_prompt`
- a JSON schema so the LLM returns comparable, storable fields
- `context_keys` selecting which deterministic data (chart, forecast, factors,
  risk metrics, screener, fundamentals, news) is attached

Run all: `tradingagents playbook 005930` (17 prompts). Only the original
ten: `tradingagents playbook 005930 --core`. A subset:
`tradingagents playbook 반도체 --prompts market_analysis,global_events`.

### Additional harness steps (11–17)

| # | id | Why it was added |
|---|---|---|
| 11 | `investor_flows` (수급 분석) | Korean prices are driven by foreign/institution flows and short interest; none of the ten prompts covered it |
| 12 | `disclosure_events` (공시·이벤트) | DART dilution (CB/증자), lock-ups, and earnings dates are the most common reasons a technically sound entry fails |
| 13 | `scenario_catalysts` (시나리오·촉매) | Forces explicit bull/base/bear probabilities and a probability-weighted return the sizer can compare with the forecast |
| 14 | `devils_advocate` (프리모템) | Structured contrarian pass that lowers conviction; used by the debate confirmer |
| 15 | `execution_plan` (실행 계획) | Turns the thesis into entry zone, tranches, stop, targets, holding period, and KRX-specific rules |
| 16 | `post_trade_review` (사후 복기) | Closes the loop with paper-simulation outcomes so rules improve over time |
| 17 | `market_regime` (시장 국면) | A regime gate (risk_on/neutral/risk_off) that can cap new entries when the index trend is broken |

### Debate confirmer

`tradingagents.harness.debate.run_debate` reproduces the existing graph's role
sequence (bull → bear → research manager → three-view risk panel → portfolio
manager) as structured JSON turns over deterministic evidence. It is exposed
as `--confirmer debate`. The full graph is still the deepest option
(`--confirmer graph`) and now receives the same evidence through the
`harness_context` config key, which the Portfolio Manager sees alongside the
memory-log lessons.

## Daily pipeline

`tradingagents pipeline` (dry run by default):

1. `screen_korean_market` loads one whole-market pykrx snapshot per market,
   drops illiquid/extreme names, fetches history for survivors, ranks by
   composite factor score.
2. `forecast_from_points` gates on expected return and probability-up.
3. A confirmer (`playbook`, `graph`, or `none`) returns a rating and
   confidence. Errors fail closed.
4. `size_position` converts risk-per-trade and the stop distance into a
   quantity, capped by weight and cash.
5. `MandateGate` checks weight, gross exposure, position count, daily loss,
   order cap, whitelist/blacklist, and kill switch.
6. The broker adapter places the order (`--execute`) or logs it (default).
7. Every stage appends to the audit ledger; `tradingagents audit-verify`
   re-hashes the chain.

Open positions are checked for stop/take-profit exits before new entries.

### Screener data sources

Whole-market snapshots (`get_market_ohlcv_by_ticker`, market cap, PER/PBR)
come from `data.krx.co.kr` through pykrx. On some corporate networks that host
returns HTML instead of JSON even after the OS truststore is applied; the
screener then falls back to a bounded universe (`TRADINGAGENTS_SCREENER_UNIVERSE`,
else `TRADINGAGENTS_SITEMAP_TICKERS`, else the built-in seed tickers) and
builds the snapshot from per-ticker daily history, which pykrx serves from a
different endpoint. Market-cap and PER filters are skipped in that mode and the
result notes say so. Set `allow_fallback_universe=False` on `ScreenerConfig`
to fail instead.

## Broker progression

| Stage | Adapter | Gate |
|---|---|---|
| Local paper | `PaperBrokerAdapter` | none (default) |
| KIS 모의투자 | `KISBrokerAdapter` with `KIS_IS_PAPER=true` | `--broker kis --execute` |
| KIS live | `KISBrokerAdapter` with `KIS_IS_PAPER=false` | `TRADINGAGENTS_ENABLE_LIVE_TRADING=true` **and** `--confirm-live` |

The public site keeps `TRADINGAGENTS_ENABLE_LIVE_TRADING=false`; the readiness
endpoint still degrades when it is set. Live trading is an operator CLI path,
never an HTTP route.

## Persistence and web

`run_daily_pipeline(..., repo=...)` (CLI `--persist`) stores each run in
`harness_runs` and every candidate decision in `harness_decisions`. The
public site renders them at `/harness` and `/harness/{run_id}` and serves
JSON at `/api/harness/*`. Vercel Cron (`/api/cron/run-harness`) and the
GitHub Actions workflow both run dry runs; see
`docs/harness-deployment-checklist.md`.

## What to do next

- Accumulate paper results: run `tradingagents pipeline --confirmer debate --persist`
  daily (the GitHub Actions workflow does this) and review `/harness`.
- Wire `harness_decisions` with stage `ordered` into the paper-simulation
  worker so 5D/20D outcomes are computed for harness picks too.
- Install `tradingagents[forecast]` on a machine with a GPU and set
  `TRADINGAGENTS_FORECAST_BACKEND=timesfm` to compare against the naive
  backend using the same audit ledger.
- Extend the screener universe loader to US tickers only after the Korean
  loop is stable.


## 유니버스: 코스피200 + 코스닥150 (2026-09-09)

`TRADINGAGENTS_SCREENER_SNAPSHOT_MODE=index`가 기본 운영 모드입니다.

- 코스피200: 네이버 금융 구성종목 페이지에서 실제 구성종목(약 200)을 현재가·거래대금·시가총액과 함께 읽습니다.
- 코스닥150: KRX 데이터포털 계정(`KRX_ID`/`KRX_PW`)이 있으면 pykrx로 실제 구성종목을 가져오고, 없으면
  코스닥 시가총액 상위 150종목을 대리 유니버스로 씁니다. `TRADINGAGENTS_KOSDAQ150_CODES`(CSV)로 직접
  지정할 수도 있습니다. 스냅샷 `vendor` 문자열에 어느 쪽을 썼는지 기록됩니다.
- 사전 필터 상한(`prefilter_limit`)은 400으로 올려 전 종목이 채점 대상이 되며, Vercel에서는 40초 시간 예산 안에
  받은 이력만 채점하고 나머지는 노트에 남깁니다. LLM 토론이 붙는 본 실행은 GitHub Actions에서 전체를 채점합니다.
