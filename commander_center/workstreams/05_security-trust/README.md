# 05 Security Trust

## Mandate

Protect users, credentials, member data, and the read-only product boundary.

## Responsibilities

- secrets hygiene
- Supabase auth and owner scoping
- RLS migration review
- CORS and cache headers
- worker token and cron endpoint protection
- live-trading boundary enforcement
- incident response

## Red Lines

- Never commit secrets.
- Never edit `.env`.
- Never trust `X-TradingAgents-User-Id` from browsers unless the deployment is
  behind a verified auth proxy and explicitly configured for that mode.
- Never expose live order, one-click trading, or automated trading routes.
- Never disable SSL verification in production.

## Required Checks

- `/api/readiness` shows `live_trading_disabled=true`.
- Member routes require verified auth.
- Private member responses are `no-store`.
- Public CORS origins are scoped to the deployment domain.
- `TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER` is false on public browser-facing
  deployments unless a verified auth proxy owns that header.
- `TRADINGAGENTS_HTTP_VERIFY_SSL=false` is not used in production.
- `TRADINGAGENTS_API_DOCS_ENABLED=false` is used in production.
- Supabase RLS migrations are applied before member launch.

## Incident First Moves

- Freeze scheduled LLM workers if abuse, cost runaway, or output quality risk is
  suspected.
- Keep cached public pages available when they are safe and clearly labeled.
- Rotate any secret that appears in chat, logs, screenshots, or issue trackers.
- Preserve sanitized evidence for post-incident review.
