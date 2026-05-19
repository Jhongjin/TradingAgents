# 10 Operations SRE

## Mandate

Keep deployment, domains, cron jobs, readiness checks, and operator runbooks
boringly reliable.

## Responsibilities

- Vercel deployment verification
- production and preview alias checks
- `/api/readiness` monitoring
- worker cron safety
- rollback notes
- incident runbooks

## Standard Deployment Check

1. Push branch.
2. Poll `/api/readiness` until `deployment.git_sha` matches the commit.
3. Confirm public URL HTTP 200.
4. Confirm canonical/alias URL points to the intended deployment.
5. Check `ads_configured=false` is expected before AdSense approval.
6. Check `live_trading_disabled=true`.

## Known Gotcha

Preview branch URLs and production aliases can diverge. A branch deployment can
be healthy while a user-facing alias returns Vercel `404: NOT_FOUND`. Always
verify the exact user-facing domain after public UI changes.

