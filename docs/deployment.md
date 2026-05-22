# Deployment

## Vercel API

This repository includes a first Vercel-ready FastAPI entrypoint:

```text
api/index.py
```

`vercel.json` rewrites `/api/:path*` and `/health` to that entrypoint. The
entrypoint exposes the same read-only API created by
`tradingagents.site.create_app`.

This project is a Python FastAPI API, not a Next.js app. `vercel.json` pins the
Framework Preset to `Other` with `"framework": null`. If Vercel still shows
`No Next.js version detected`, open **Project Settings -> Build & Development
Settings** and set **Framework Preset** to **Other**, then redeploy.

For a public ad-supported site, Vercel Deployment Protection must not block the
production URL. If `/`, `/health`, or `/api/readiness` returns `401
Unauthorized` in a normal browser/incognito session, open **Project Settings ->
Deployment Protection** and disable protection for the environment/domain you
intend to publish. Keep preview deployments protected if you want, but the
canonical `TRADINGAGENTS_SITE_BASE_URL` must be publicly crawlable for SEO,
`ads.txt`, and AdSense verification.

Required production environment:

```text
OPENAI_API_KEY=
DART_API_KEY=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
DATABASE_URL=
TRADINGAGENTS_POSTGRES_DRIVER=pg8000
TRADINGAGENTS_STORAGE_ENABLED=true
SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_URL=
SUPABASE_ANON_KEY=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
TRADINGAGENTS_API_CORS_ORIGINS=https://your-domain.example
TRADINGAGENTS_API_CORS_METHODS=GET,POST,PUT,DELETE,OPTIONS
TRADINGAGENTS_API_PUBLIC_CACHE_SECONDS=300
TRADINGAGENTS_API_MAX_PRICE_TICKERS=20
TRADINGAGENTS_API_MAX_ANALYSIS_FEED_LIMIT=50
TRADINGAGENTS_API_DOCS_ENABLED=false
TRADINGAGENTS_AUTH_TIMEOUT_SECONDS=5
TRADINGAGENTS_SITE_BASE_URL=https://your-domain.example
TRADINGAGENTS_SITEMAP_TICKERS=005930,000660,035420,035720,051910,005380,068270,005490
TRADINGAGENTS_SITEMAP_MAX_ANALYSIS_TICKERS=200
TRADINGAGENTS_CHART_DATA_VENDOR=pykrx
TRADINGAGENTS_ADSENSE_PUBLISHER_ID=pub-0000000000000000
# Or set a full custom ads.txt body with \n between lines:
TRADINGAGENTS_ADS_TXT=
TRADINGAGENTS_WORKER_TOKEN=
TRADINGAGENTS_WORKER_MAX_REQUESTS=1
TRADINGAGENTS_WORKER_CRON_LIMIT=1
TRADINGAGENTS_ANALYSIS_REQUEST_ACTIVE_LIMIT=5
TRADINGAGENTS_ANALYSIS_REQUEST_DAILY_LIMIT=20
TRADINGAGENTS_OUTCOME_WORKER_MAX_RUNS=20
TRADINGAGENTS_OUTCOME_WORKER_CRON_LIMIT=5
# Optional Vercel Cron secret. If set, Vercel sends it as Authorization: Bearer <CRON_SECRET>.
CRON_SECRET=
TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER=false
```

Vercel environment variables are scoped by environment. The branch domain
`trading-agents-git-codex-kr-market-...vercel.app` is a **Preview** deployment,
so set the required variables for Preview too, or promote/deploy the branch to
Production and test the production domain. `GET /api/readiness` returns
`deployment.vercel_env` and non-secret boolean checks to confirm which scope is
actually active.

If you already configured Supabase for a browser client, the API also accepts
`NEXT_PUBLIC_SUPABASE_URL` in place of `SUPABASE_URL`, and
`NEXT_PUBLIC_SUPABASE_ANON_KEY` in place of `SUPABASE_ANON_KEY`. The readiness
response includes a non-secret `missing_environment` object that lists env
names still needed by the active deployment. If `DATABASE_URL` is present but
malformed, readiness keeps the site alive and reports a sanitized
`configuration_errors.storage_configured` hint instead of exposing the URL.
Readiness also opens a lightweight database connection and reports
`checks.storage_online=false` with a sanitized `configuration_errors.storage_online`
message when the password, pooler host, or URL encoding is wrong. After the
connection succeeds, it checks that the required application tables are present;
`checks.storage_schema_ready=false` means the Supabase migrations still need to
be applied in order. Public deployment readiness also requires
`TRADINGAGENTS_ENABLE_LIVE_TRADING` to remain unset or false.

Apply the Supabase migration before enabling persistent analysis storage. Do
not enable `TRADINGAGENTS_STORAGE_CREATE_SCHEMA` in production Supabase; use the
migration so RLS policies are installed.

`TRADINGAGENTS_POSTGRES_DRIVER` defaults to `pg8000`, a pure-Python SQLAlchemy
Postgres driver that is friendly to Vercel serverless deployments. You may set
it to `psycopg` or `psycopg2` for other hosting environments after installing
the matching driver package.

The API remains read-only:

- `GET /`: public Samsung Electronics analysis page
- `GET /analyses`: public completed-analysis feed page
- `GET /analyses/{analysis_run_id}`: public rendered analysis report page backed by the same bundle as JSON
- `GET /features/{feature_slug}`: public feature/trust pages including research, outcomes, member workspace, and methodology
- `GET /member`: noindex member dashboard shell for Supabase Auth and manual records
- `GET /stocks/{ticker}`: public Korean stock analysis page with KRW chart
- `GET /ads.txt`: advertising seller declaration generated from AdSense/custom env
- `GET /robots.txt`: crawler policy with sitemap URL
- `GET /sitemap.xml`: public page sitemap built from `TRADINGAGENTS_SITEMAP_TICKERS` and stored public analyses
- `GET /api/readiness`: non-secret deployment readiness checks
- `GET /api/tickers/search?q=삼성`: Korean ticker code/name search
- `GET /api/stocks/{ticker}`: public Korean stock payload
- `GET /api/analyses?ticker=005930`: public completed-analysis feed
- `GET /api/analyses/{analysis_run_id}`: public completed-analysis bundle JSON for verification/debugging
- `GET /api/analysis-outcomes?ticker=005930`: public realised-return and benchmark-alpha outcome feed
- `GET /api/prices/latest?tickers=005930,000660`: latest close-price snapshots
- `POST /api/analysis-requests`: queue an authenticated member analysis refresh request
- `GET /api/analysis-requests`: list authenticated member analysis refresh requests
- `GET /api/analysis-requests/{request_id}`: inspect one authenticated member analysis refresh request
- `POST /api/admin/analysis-requests/process`: protected operator endpoint for queued analysis processing
- `GET /api/cron/process-analysis-requests`: protected Vercel Cron-compatible processing endpoint
- `POST /api/admin/analysis-outcomes/process`: protected operator endpoint for realised-return outcome processing
- `GET /api/cron/process-analysis-outcomes`: protected Vercel Cron-compatible outcome processing endpoint
- `POST /api/portfolios`: create an authenticated member manual portfolio
- `GET /api/portfolios`: list authenticated member manual portfolios
- `POST /api/portfolio/{portfolio_id}/trades`: add a user-entered buy/sell record
- `PUT /api/portfolio/{portfolio_id}/targets/{ticker}`: save a target/stop price
- `POST /api/watchlists`: create an authenticated member watchlist
- `GET /api/watchlists`: list authenticated member watchlists
- `POST /api/watchlists/{watchlist_id}/items`: add or update a watchlist item
- `DELETE /api/watchlists/{watchlist_id}/items/{ticker}`: remove a watchlist item
- `GET /api/portfolio/{portfolio_id}`: manual portfolio summary from stored user-entered trades
- `GET /api/watchlists/{watchlist_id}`: member watchlist summary from stored ticker lists
- `GET /health`: deployment health check

For member portfolio/watchlist detail endpoints, pass
`include_latest_prices=true` to price Korean tickers with the latest pykrx close
instead of supplying `current_prices=005930:83000` manually.

Public stock chart data uses `TRADINGAGENTS_CHART_DATA_VENDOR=pykrx` by default.
Set it to `auto` to try KRX Open API first only when the requested chart range
is within `TRADINGAGENTS_KRX_CHART_MAX_DAYS` (default `14`), then fall back to
pykrx if KRX authentication, quota, availability, or range limits fail. Set it
to `krx`, or pass `chart_vendor=krx` on `/stocks/{ticker}` and
`/api/stocks/{ticker}`, only for explicit KRX-only diagnostics. KRX-only
requests without `chart_start` use that same short max-days window to avoid
serverless function timeouts. Keep `pykrx` or `auto` for high-traffic public
pages until KRX API quota, latency, and caching are measured. Public stock
payloads include non-secret chart source metadata (`requested_vendor`,
`resolved_vendor`, `point_count`, `data_source_label`, and `fallback_used`) so
operators and rendered pages can tell when `auto` selected or fell back to
pykrx.
If readiness shows `krx_configured=true` but `chart_vendor=krx` returns a 401,
run the local doctor with `TRADINGAGENTS_DOCTOR_CHECK_KRX_ONLINE=true`; the key
may exist but still lack KRX service-level approval.
You can also call `/api/readiness?probe_krx=true` after deploys to run an
explicit KRX Open API probe. It uses Samsung Electronics (`005930`) by default;
set `TRADINGAGENTS_KRX_PROBE_TICKER=086520` to probe the KOSDAQ daily trade
endpoint instead. The default `/api/readiness` response does not call external
market-data vendors. Probe responses include non-secret `diagnostics.krx_probe`
metadata such as ticker, date, row count, elapsed milliseconds, and sanitized
failure type/message so operators can measure vendor health without exposing
keys.

No live trading or broker order placement is exposed.

For Google AdSense, set `TRADINGAGENTS_ADSENSE_PUBLISHER_ID` to your `pub-...`
publisher ID. The generated `ads.txt` line follows the AdSense format:
`google.com, pub-0000000000000000, DIRECT, f08c47fec0942fa0`.

Analysis refresh requests are queued. Use
`tradingagents.site.analysis_worker.process_queued_analysis_requests(...)` as
the worker foundation; inject a runner that executes TradingAgents and returns
the persisted `analysis_runs.id`. The first graph runner adapter is
`tradingagents.site.analysis_runner.run_tradingagents_graph_for_request(...)`;
it enables the graph storage hook and expects `last_analysis_run_id` after
`propagate(...)`.

For an operator-run worker:

```bash
tradingagents process-analysis-requests --dry-run
tradingagents process-analysis-requests --limit 1
```

The worker requires `DATABASE_URL` and processes queued rows one at a time by
default.

The protected API worker endpoint requires `TRADINGAGENTS_WORKER_TOKEN` and
accepts either `Authorization: Bearer <token>` or
`X-TradingAgents-Worker-Token: <token>`. Keep `TRADINGAGENTS_WORKER_MAX_REQUESTS`
small on Vercel because a full TradingAgents run can be expensive and may hit
serverless duration limits.

Member-created analysis refresh requests are rate limited before they enter the
worker queue. `TRADINGAGENTS_ANALYSIS_REQUEST_ACTIVE_LIMIT` caps each member's
simultaneous queued/running requests, and
`TRADINGAGENTS_ANALYSIS_REQUEST_DAILY_LIMIT` caps requests in a rolling 24-hour
window. Duplicate active requests for the same member, ticker, and trade date
return the existing queue item instead of consuming another quota slot.

Vercel Cron invokes endpoints with GET requests. The repo therefore includes
`GET /api/cron/process-analysis-requests`, which accepts the same worker token
or Vercel's `CRON_SECRET` bearer header. `vercel.json` schedules this endpoint
for 18:10 KST on weekdays (`10 9 * * 1-5` in UTC). Keep the cron active only
when you are ready to pay for scheduled LLM runs.

Public analysis outcomes are a separate post-analysis verification pass. They
look at completed public analysis runs, fetch later Korean-market returns, and
store raw return, benchmark return, and alpha in `analysis_outcomes`. This is
market-data work, not a new LLM analysis, so it uses separate limits:
`TRADINGAGENTS_OUTCOME_WORKER_MAX_RUNS` for manual/API calls and
`TRADINGAGENTS_OUTCOME_WORKER_CRON_LIMIT` for cron calls. The default horizons
are 5 and 20 trading days. `vercel.json` schedules the outcome pass for 19:10
KST on weekdays (`10 10 * * 1-5` in UTC). See
[`docs/outcome-worker-runbook.md`](outcome-worker-runbook.md) for the operator
checklist, response interpretation, retry rules, and escalation path.

For an operator-run outcome worker:

```bash
tradingagents process-analysis-outcomes --dry-run
tradingagents process-analysis-outcomes --limit 20 --horizons 5,20
```

The protected API endpoint accepts the same worker token style:

```bash
curl -X POST "https://your-domain.example/api/admin/analysis-outcomes/process" \
  -H "Authorization: Bearer <TRADINGAGENTS_WORKER_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"limit":20,"horizons":[5,20]}'
```

Use `GET /api/analysis-outcomes?ticker=005930` to inspect the public track
record that feeds the stock page outcome cards. If a horizon has not yet
elapsed or market data is unavailable, the row is stored as `pending` or
`unavailable` instead of failing the worker. Completed horizons are idempotent:
later worker runs skip them unless the code is changed to support an explicit
force/recompute mode.

Member routes require an authenticated user context before they will return
portfolio or watchlist data. By default the API verifies `Authorization: Bearer
<Supabase access token>` by calling Supabase Auth `/auth/v1/user` with
`SUPABASE_URL` or `NEXT_PUBLIC_SUPABASE_URL`, plus `SUPABASE_ANON_KEY`,
`NEXT_PUBLIC_SUPABASE_ANON_KEY`, or `SUPABASE_PUBLISHABLE_KEY`.

Supabase Auth email confirmations must return to the member dashboard. In
**Supabase Dashboard -> Authentication -> URL Configuration**, set **Site URL**
to the public site origin and add the member callback URL to **Redirect URLs**:

```text
https://your-domain.example/member
```

For Vercel Preview testing, also allow the active preview member URL, for
example:

```text
https://trading-agents-git-codex-kr-market-jeonhongjins-projects.vercel.app/member
```

Keep `http://localhost:3000` only for local development. The `/member` browser
client sends Supabase signup requests with an explicit `redirect_to` value and
removes Supabase access-token fragments from the address bar after confirmation,
but Supabase still has to allow the destination URL.

`X-TradingAgents-User-Id` is accepted only when
`TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER=true`, which should be used only
behind a trusted auth proxy that sets the header from a verified Supabase user
UUID. Do not expose that trust mode directly to browsers without an auth proxy.
