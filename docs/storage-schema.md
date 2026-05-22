# Storage Schema

This schema supports the public Korean-stock analysis site and the later
member-only manual portfolio features.

## Supabase Migration

Apply the migrations in order:

```text
supabase/migrations/202605050001_tradingagents_public_site.sql
supabase/migrations/202605050002_manual_watchlists.sql
supabase/migrations/202605050003_analysis_refresh_requests.sql
supabase/migrations/202605050004_analysis_request_run_link.sql
supabase/migrations/202605060001_analysis_outcomes.sql
```

The migrations create:

- `analysis_runs`: one AI analysis execution for a ticker/date
- `analysis_refresh_requests`: queued member requests for a background analysis worker
- `agent_reports`: market/news/fundamentals/trader/risk report bodies
- `trade_decisions`: final rating/action from the analysis workflow
- `analysis_outcomes`: realised return, benchmark return, and alpha after public analysis horizons elapse
- `manual_portfolios`: member-owned manual portfolios
- `manual_trades`: member-entered buy/sell history
- `manual_price_targets`: target/stop prices for member-entered holdings
- `manual_watchlists`: member-owned watchlists
- `manual_watchlist_items`: member-entered watchlist tickers

Row Level Security is enabled. Public analysis rows are readable when
`visibility = 'public'`. Manual portfolios and trades are readable and writable
only by the authenticated owner. Watchlists follow the same owner-only policy in
`supabase/migrations/202605050002_manual_watchlists.sql`.

The migration intentionally avoids PL/pgSQL trigger functions so it can be run
reliably from the Supabase dashboard SQL editor. Application updates should set
`updated_at` when editing portfolio names or price targets.

## Python Repository

The Python repository lives under `tradingagents.storage`:

```python
from datetime import date

from tradingagents.storage import AnalysisRunInput, StorageRepository, create_storage_engine

repo = StorageRepository(create_storage_engine())
run_id = repo.create_analysis_run(
    AnalysisRunInput(
        ticker_code="005930",
        ticker_name="삼성전자",
        market="KOSPI",
        trade_date=date(2026, 5, 5),
    )
)
```

`create_storage_engine()` reads `DATABASE_URL`. If the value begins with
`postgresql://`, it is normalized to SQLAlchemy's `postgresql+psycopg://`
dialect. Without `DATABASE_URL`, it uses in-memory SQLite for local tests.

Use `repo.create_schema()` only for local SQLite or development databases.
Production Supabase should use the migration so RLS policies are installed.

Manual portfolio helpers include user-entered trade storage, position
calculation, and price target upserts. `set_price_target(...)` updates the
existing `(portfolio_id, ticker_code)` row and sets `updated_at` from the app
layer, which keeps the Supabase migration free of dashboard-fragile trigger
functions.

For member pages, `tradingagents.site.build_manual_portfolio_payload(...)`
combines stored manual trades, optional current prices supplied by the app, and
manual target/stop rows into a JSON-ready portfolio summary. The result is an
estimate from user-entered data, not broker-verified account state. Portfolio
payloads include average cost, realised/unrealised PnL, total PnL rate, and
target/stop distance rates when current prices are available.

Watchlist helpers store member-owned ticker lists separately from portfolio
holdings. `tradingagents.site.build_watchlist_payload(...)` returns a JSON-ready
watchlist with optional current prices supplied by the app, pricing coverage,
memo counts, and public stock-page paths for each watched ticker.

Analysis refresh requests are intentionally queued in
`analysis_refresh_requests` instead of running LLM analysis inline during a web
request. A separate worker should read queued rows, run TradingAgents, persist
the completed analysis, link `analysis_run_id`, and update the request status.
Request payloads expose duplicate suppression, active status labels, and public
stock-page paths so the member UI can explain queue state without polling
private worker details. Before inserting a new row, the site API reuses active
requests for the same member, ticker, and trade date; it also enforces per-user
active and rolling 24-hour request limits using existing request status and
`created_at` fields.
`tradingagents.site.analysis_worker.process_queued_analysis_requests(...)`
provides the first runner-injection skeleton for that background process.
`tradingagents.site.analysis_runner.run_tradingagents_graph_for_request(...)`
is the concrete adapter for invoking `TradingAgentsGraph` once a worker is ready
to process queued rows. Public report pages render provenance directly from the
stored run bundle, including `trade_date`, model fields, `metadata_json.source`,
`metadata_json.selected_analysts`, timestamps, outcome counts, and the matching
JSON endpoint for audit.

Analysis outcomes are intentionally calculated after completed public runs. The
`tradingagents.site.outcome_worker.evaluate_public_analysis_outcomes(...)`
helper reads public completed analyses, evaluates configured horizons such as 5
and 20 trading days, and upserts `analysis_outcomes` rows. Completed rows store
raw return, benchmark return, alpha return, and holding-day metadata. Rows stay
`pending` when a horizon has not elapsed yet, and become `unavailable` when
market data cannot be fetched. Existing `completed` horizons are skipped on
later worker runs so scheduled jobs do not repeatedly call the data vendor for
immutable realised outcomes.

## Analysis Persistence Hook

The TradingAgents graph can persist completed runs after the existing JSON log
and memory log are written. Enable it explicitly:

```text
DATABASE_URL=postgresql://...
TRADINGAGENTS_STORAGE_ENABLED=true
TRADINGAGENTS_STORAGE_CREATE_SCHEMA=false
TRADINGAGENTS_ANALYSIS_VISIBILITY=public
# Optional: Supabase auth.users.id UUID for private/server-owned runs.
TRADINGAGENTS_ANALYSIS_USER_ID=
```

When enabled, a completed run writes one `analysis_runs` row, one row per
available report in `agent_reports`, and the final parsed rating/action in
`trade_decisions`. Storage failures are logged and do not block the CLI analysis
workflow.

For public pages, use `StorageRepository.latest_public_analysis_bundle("005930")`
to fetch the newest public run with reports and final decision, or
`list_public_analysis_runs(ticker_code="005930")` for feed/search views. Private
runs are excluded from these public helpers, and the default listing includes
only `completed` analyses. Pass `status=None` only for internal admin views that
need pending or failed rows.
The public stock bundle includes `analysis_outcomes` so the site can show a
visible track record next to the latest agent report.

## Product Boundary

Manual trade data is user-entered recordkeeping. Do not store broker passwords,
certificates, OTPs, or other access media. Broker integration, if added later,
must start with read-only official APIs and a separate security review.
