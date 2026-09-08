# Harness Deployment Checklist (Git · Vercel · Supabase)

This is the operator checklist for shipping the harness (screener → forecast →
AI debate → sizing → mandate gate → dry-run/paper) to the public site. Follow
the sections in order; each one lists what you must do yourself because it
needs your accounts or secrets.

## 1. Git repository

- Branch: work stays on `codex/kr-market`; merge to `main` when the Vercel
  production alias should update.
- Commit the new modules (`tradingagents/analytics`, `screener`, `forecast`,
  `harness`, `execution/{audit,broker,kis_client,mandate,position_sizing}.py`,
  `site/{screener_api,harness_api,harness_pages}.py`, migration
  `supabase/migrations/202609080001_harness_runs.sql`, workflow
  `.github/workflows/harness-daily.yml`, docs, tests).
- Never commit `.env`. `.env.example` documents the new variables.
- GitHub Actions secrets for the daily workflow (Settings → Secrets and
  variables → Actions):
  - `OPENAI_API_KEY` (or the provider you configure in `DEFAULT_CONFIG`)
  - `DATABASE_URL` (Supabase pooler URL, same as Vercel)
  - repository variable `TRADINGAGENTS_SCREENER_UNIVERSE` (optional CSV of
    codes; used only if whole-market pykrx frames are blocked from the runner)
- The workflow runs `tradingagents pipeline --confirmer debate --persist`
  at 07:50 KST on weekdays as a dry run and uploads the run JSON and audit
  ledger as artifacts. Trigger it manually first from the Actions tab.

## 2. Supabase

- Apply migrations in order through the SQL editor or CLI. The new file is
  `supabase/migrations/202609080001_harness_runs.sql`; it creates
  `harness_runs` and `harness_decisions` with RLS that allows public `select`
  on `visibility = 'public'` rows only. Writes come from the service-role
  `DATABASE_URL` used by workers, never from the browser.
- Confirm with `GET /api/readiness`: `checks.storage_schema_ready` must be
  `true` after the migration (the check now includes the two harness tables).
- No Supabase Auth changes are needed; harness pages are public read-only.
- Optional: add `harness_decisions` to a Supabase dashboard chart to track
  stage counts per day (ordered vs rejected) for model drift review.

## 3. Vercel

Environment variables to add (Production and Preview):

```text
# already required
DATABASE_URL=
TRADINGAGENTS_STORAGE_ENABLED=true
TRADINGAGENTS_WORKER_TOKEN=
CRON_SECRET=
OPENAI_API_KEY=

# new for the harness
TRADINGAGENTS_FORECAST_BACKEND=naive
TRADINGAGENTS_SCREENER_UNIVERSE=005930,000660,035420,373220,086520,005380,051910,068270,005490,035720
TRADINGAGENTS_HARNESS_CRON_CONFIRMER=none
TRADINGAGENTS_HARNESS_CRON_CONFIRM_TOP_N=3
TRADINGAGENTS_HARNESS_MARKETS=KOSPI,KOSDAQ
TRADINGAGENTS_AUDIT_LOG_PATH=
TRADINGAGENTS_ENABLE_LIVE_TRADING=false
```

Notes:

- `vercel.json` now rewrites `/harness` and `/harness/:id` and schedules
  `GET /api/cron/run-harness` at 16:40 KST (`40 7 * * 1-5` UTC). The cron
  runs a **dry run** and persists decisions. Keep
  `TRADINGAGENTS_HARNESS_CRON_CONFIRMER=none` on Vercel: the 60-second
  function limit is too short for LLM confirmers on more than one or two
  names. Use the GitHub Actions workflow (or a local scheduler) for
  `playbook`/`debate` confirmers.
- `TRADINGAGENTS_SCREENER_UNIVERSE` is required on Vercel. pykrx whole-market
  snapshots call `data.krx.co.kr`, which is slow and sometimes blocked from
  cloud IPs; the bounded universe keeps the cron inside the time limit.
- `TRADINGAGENTS_AUDIT_LOG_PATH` may stay empty on Vercel (the ledger falls
  back to the function's temp dir and is not durable). Durable ledgers come
  from the CLI/GitHub Actions runs.
- TimesFM is not installable on Vercel (torch is too large). Leave
  `TRADINGAGENTS_FORECAST_BACKEND=naive` there; run TimesFM locally or in the
  Actions runner with `pip install "tradingagents[forecast]"`.

Routes added:

| Route | Purpose |
|---|---|
| `GET /harness`, `GET /harness/{run_id}` | public HTML pages |
| `GET /api/harness/runs`, `/api/harness/runs/latest`, `/api/harness/runs/{id}` | public JSON |
| `GET /api/harness/tickers/{code}` | per-ticker decision history |
| `GET /api/screener`, `GET /api/forecast/{code}` | screener and forecast payloads |
| `POST /api/admin/harness/run` | operator dry run (worker token), body `{confirmer, confirm_top_n, top_n, markets, as_of_date}` |
| `GET /api/cron/run-harness` | Vercel Cron dry run |

Smoke after deploy:

```bash
curl -s https://your-domain/api/readiness | jq .checks.storage_schema_ready
curl -s -X POST https://your-domain/api/admin/harness/run \
  -H "Authorization: Bearer $TRADINGAGENTS_WORKER_TOKEN" \
  -H "Content-Type: application/json" -d '{"confirmer":"none","confirm_top_n":3}'
curl -s https://your-domain/api/harness/runs/latest | jq .summary
open https://your-domain/harness
```

## 4. Broker progression (operator only, never on Vercel)

| Stage | Command | Requirements |
|---|---|---|
| Local paper, persisted | `tradingagents pipeline --confirmer debate --persist` | `DATABASE_URL`, LLM key |
| KIS 모의투자 | `tradingagents pipeline --broker kis --execute --persist` | `KIS_IS_PAPER=true`, `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_ACCOUNT_NO`, `KIS_ACCOUNT_PRODUCT_CODE` |
| KIS live | `tradingagents pipeline --broker kis --execute --confirm-live` | above plus `KIS_IS_PAPER=false`, `TRADINGAGENTS_ENABLE_LIVE_TRADING=true`, and a legal/risk review |

Run `tradingagents audit-verify` after every executed cycle and keep the
ledger file under backup.
