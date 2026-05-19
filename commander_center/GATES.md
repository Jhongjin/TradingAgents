# Release And Trust Gates

## Gate 1: Product Scope

- The change supports Korean-stock AI analysis, member research workflow, or
  public trust.
- The change does not introduce live trading or broker order placement.
- User-facing copy avoids guaranteed-profit or personalized-advice claims.

## Gate 2: Data Provenance

- Public stock data identifies source family where practical: pykrx, KRX, DART,
  Naver, stored analysis, or calculated outcome.
- Stale, missing, partial, or fallback data is visible to users or operators.
- KRX-only behavior remains diagnostic unless quota and latency are proven.
- Benchmark alpha must be reproducible from stored or fetchable market data.

## Gate 3: Security And Privacy

- No secrets in code, docs, tests, logs, screenshots, or commits.
- `.env` remains untouched.
- Member data is owner-scoped and private/no-store.
- Public CORS origins are explicit.
- Live trading remains disabled in readiness and code paths.
- Public browser-facing deployments must not use
  `TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER=true` unless protected by a
  verified auth proxy that strips spoofed headers.
- Production deployments must not set `TRADINGAGENTS_HTTP_VERIFY_SSL=false`.
- Production API docs should stay disabled with
  `TRADINGAGENTS_API_DOCS_ENABLED=false`.
- Supabase migrations and RLS policies must be applied before member launch.

## Gate 4: Accuracy And AI Quality

- Reports distinguish observed data from model interpretation.
- Analysis has timestamps and ticker identity.
- Outcome tracking is not presented before the horizon has elapsed.
- Missing DART/Naver/KRX data cannot be turned into confident claims.
- Major fixture tickers should cover both KOSPI and KOSDAQ when analysis prompt
  or report structure changes.
- Generated report sections should expose source/vendor/date/freshness metadata
  in rendered UI, not only raw JSON payloads.

## Gate 5: UX And Accessibility

- Core flows work at desktop, tablet, and narrow mobile widths.
- Important text does not overlap, clip, or hide behind animated layers.
- Reduced-motion preferences are respected for perpetual motion.
- Public pages expose clear next actions without in-app tutorial text clutter.

## Gate 6: Verification

Minimum verification by change type:

- docs only: spelling/links by inspection and `git diff --check`
- Python/API: focused tests plus full `pytest -q`
- public/member UI: browser screenshot, console check, overflow check, focused
  tests, and full `pytest -q`
- deployment/domain: `/api/readiness`, target URL HTTP 200, and final alias check

## Gate 7: Ship

- Commit message describes one coherent unit.
- Push branch `codex/kr-market`.
- Verify Vercel deployment SHA or alias for public-facing changes.
- Record remaining blockers in the final user update.
- Scan public UI and routes for accidental order/trade/buy/sell execution
  language before launches that touch broker, portfolio, or analysis wording.

## Gate 8: Outcome Accountability

- Public analyses accumulate 5D/20D realised return and benchmark-alpha outcomes
  when horizons have elapsed.
- Unavailable market data is recorded as unavailable, not silently ignored.
- Commander Center reviews misses, unavailable data, and possible model drift at
  least weekly once the public feed is active.
