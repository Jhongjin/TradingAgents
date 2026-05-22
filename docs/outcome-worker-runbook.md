# 5D/20D outcome worker runbook

TradingAgents Korea uses the outcome worker to verify public AI analysis after
time has passed. It never creates a trade order and never starts a new LLM
research run. The worker reads completed public analysis runs, fetches later
Korean-market returns, and upserts 5-trading-day and 20-trading-day outcome
rows.

## Preconditions

- `DATABASE_URL` points to the Supabase/Postgres project and the storage schema
  is ready.
- `TRADINGAGENTS_WORKER_TOKEN` is set for operator/admin calls.
- `CRON_SECRET` is optional, but if present Vercel Cron sends it as
  `Authorization: Bearer <CRON_SECRET>`.
- `TRADINGAGENTS_ENABLE_LIVE_TRADING` remains unset or false.
- KRX/pykrx market data may be unavailable on holidays, before enough trading
  days have elapsed, or during vendor outages. Those cases are recorded as
  `pending` or `unavailable`.

## Schedule

`vercel.json` runs the outcome worker on production only:

- Path: `GET /api/cron/process-analysis-outcomes`
- Cron: `10 10 * * 1-5` UTC
- Local time: 19:10 KST, Monday-Friday
- Horizons: `[5, 20]`
- Limit: `TRADINGAGENTS_OUTCOME_WORKER_CRON_LIMIT` (default `5`)

Keep this scheduled pass after the analysis-request cron so same-day public
runs are created before outcome verification scans them.

## Manual operation

1. Check readiness:

   ```bash
   curl "https://your-domain.example/api/readiness"
   ```

2. Dry-run candidate public runs:

   ```bash
   tradingagents process-analysis-outcomes --dry-run --limit 20 --horizons 5,20
   ```

   Or from the protected admin API:

   ```bash
   curl -X POST "https://your-domain.example/api/admin/analysis-outcomes/process" \
     -H "Authorization: Bearer <TRADINGAGENTS_WORKER_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"dry_run":true,"limit":20,"horizons":[5,20]}'
   ```

3. Process once:

   ```bash
   tradingagents process-analysis-outcomes --limit 20 --horizons 5,20
   ```

   Or:

   ```bash
   curl -X POST "https://your-domain.example/api/admin/analysis-outcomes/process" \
     -H "Authorization: Bearer <TRADINGAGENTS_WORKER_TOKEN>" \
     -H "Content-Type: application/json" \
     -d '{"limit":20,"horizons":[5,20]}'
   ```

4. Inspect the public track record:

   ```bash
   curl "https://your-domain.example/api/analysis-outcomes?limit=20"
   curl "https://your-domain.example/api/analysis-outcomes?ticker=005930"
   ```

## Response reading

- `summary.result_count`: number of run/horizon checks attempted.
- `summary.status_counts.completed`: outcomes with enough holding days and
  return data.
- `summary.status_counts.pending`: data exists, but the requested 5D/20D
  horizon has not elapsed.
- `summary.status_counts.unavailable`: market data or benchmark data could not
  be fetched.
- `summary.status_counts.skipped`: completed horizon already existed and was
  left unchanged.
- `summary.average_alpha_return`: average alpha across newly completed checks.
- `inspect_path`: public endpoint to verify persisted outcome rows.

Completed outcomes are idempotent. Later worker runs skip them unless a future
force/recompute mode is intentionally added. Pending and unavailable rows can be
retried by running the worker again after more market data is available.

## Escalation

- If readiness reports `storage_online=false` or `storage_schema_ready=false`,
  stop and fix storage/migrations before running the worker.
- If `krx_configured=false`, outcomes may still use pykrx-backed paths, but
  vendor reliability should be investigated before treating track-record gaps as
  platform failures.
- If the admin endpoint returns 401/403, verify the worker token in the browser
  session or request header. Do not paste tokens into source files or commits.
- If the cron does not run, confirm the deployment is production and inspect
  Vercel logs for `/api/cron/process-analysis-outcomes`.
