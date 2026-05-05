# Deployment

## Vercel API

This repository includes a first Vercel-ready FastAPI entrypoint:

```text
api/index.py
```

`vercel.json` rewrites `/api/:path*` and `/health` to that entrypoint. The
entrypoint exposes the same read-only API created by
`tradingagents.site.create_app`.

Required production environment:

```text
OPENAI_API_KEY=
DART_API_KEY=
NAVER_CLIENT_ID=
NAVER_CLIENT_SECRET=
DATABASE_URL=
TRADINGAGENTS_STORAGE_ENABLED=true
TRADINGAGENTS_API_CORS_ORIGINS=https://your-domain.example
TRADINGAGENTS_API_PUBLIC_CACHE_SECONDS=300
TRADINGAGENTS_API_MAX_PRICE_TICKERS=20
```

Apply the Supabase migration before enabling persistent analysis storage. Do
not enable `TRADINGAGENTS_STORAGE_CREATE_SCHEMA` in production Supabase; use the
migration so RLS policies are installed.

The API remains read-only:

- `GET /api/stocks/{ticker}`: public Korean stock payload
- `GET /api/prices/latest?tickers=005930,000660`: latest close-price snapshots
- `GET /api/portfolio/{portfolio_id}`: manual portfolio summary from stored user-entered trades
- `GET /api/watchlists/{watchlist_id}`: member watchlist summary from stored ticker lists
- `GET /health`: deployment health check

No live trading or broker order placement is exposed.
