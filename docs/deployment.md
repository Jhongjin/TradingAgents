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

Required production environment:

```text
OPENAI_API_KEY=
DART_API_KEY=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
DATABASE_URL=
TRADINGAGENTS_STORAGE_ENABLED=true
SUPABASE_URL=
SUPABASE_ANON_KEY=
TRADINGAGENTS_API_CORS_ORIGINS=https://your-domain.example
TRADINGAGENTS_API_CORS_METHODS=GET,POST,OPTIONS
TRADINGAGENTS_API_PUBLIC_CACHE_SECONDS=300
TRADINGAGENTS_API_MAX_PRICE_TICKERS=20
TRADINGAGENTS_API_MAX_ANALYSIS_FEED_LIMIT=50
TRADINGAGENTS_API_DOCS_ENABLED=false
TRADINGAGENTS_AUTH_TIMEOUT_SECONDS=5
TRADINGAGENTS_SITE_BASE_URL=https://your-domain.example
TRADINGAGENTS_SITEMAP_TICKERS=005930,000660,035420,035720,051910,005380,068270,005490
TRADINGAGENTS_ADSENSE_PUBLISHER_ID=pub-0000000000000000
# Or set a full custom ads.txt body with \n between lines:
TRADINGAGENTS_ADS_TXT=
TRADINGAGENTS_WORKER_TOKEN=
TRADINGAGENTS_WORKER_MAX_REQUESTS=1
TRADINGAGENTS_WORKER_CRON_LIMIT=1
# Optional Vercel Cron secret. If set, Vercel sends it as Authorization: Bearer <CRON_SECRET>.
CRON_SECRET=
TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER=false
```

Apply the Supabase migration before enabling persistent analysis storage. Do
not enable `TRADINGAGENTS_STORAGE_CREATE_SCHEMA` in production Supabase; use the
migration so RLS policies are installed.

The API remains read-only:

- `GET /`: public Samsung Electronics analysis page
- `GET /stocks/{ticker}`: public Korean stock analysis page with KRW chart
- `GET /ads.txt`: advertising seller declaration generated from AdSense/custom env
- `GET /robots.txt`: crawler policy with sitemap URL
- `GET /sitemap.xml`: public page sitemap built from `TRADINGAGENTS_SITEMAP_TICKERS`
- `GET /api/stocks/{ticker}`: public Korean stock payload
- `GET /api/analyses?ticker=005930`: public completed-analysis feed
- `GET /api/prices/latest?tickers=005930,000660`: latest close-price snapshots
- `POST /api/analysis-requests`: queue an authenticated member analysis refresh request
- `POST /api/admin/analysis-requests/process`: protected operator endpoint for queued analysis processing
- `GET /api/cron/process-analysis-requests`: protected Vercel Cron-compatible processing endpoint
- `GET /api/portfolio/{portfolio_id}`: manual portfolio summary from stored user-entered trades
- `GET /api/watchlists/{watchlist_id}`: member watchlist summary from stored ticker lists
- `GET /health`: deployment health check

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

Vercel Cron invokes endpoints with GET requests. The repo therefore includes
`GET /api/cron/process-analysis-requests`, which accepts the same worker token
or Vercel's `CRON_SECRET` bearer header. Add a `crons` entry in `vercel.json`
only after you are ready to pay for scheduled LLM runs.

Member routes require an authenticated user context before they will return
portfolio or watchlist data. By default the API verifies `Authorization: Bearer
<Supabase access token>` by calling Supabase Auth `/auth/v1/user` with
`SUPABASE_URL` and `SUPABASE_ANON_KEY` or `SUPABASE_PUBLISHABLE_KEY`.

`X-TradingAgents-User-Id` is accepted only when
`TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER=true`, which should be used only
behind a trusted auth proxy that sets the header from a verified Supabase user
UUID. Do not expose that trust mode directly to browsers without an auth proxy.
