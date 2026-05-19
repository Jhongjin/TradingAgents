# Risk Register

| ID | Risk | Severity | Owner | Mitigation |
| --- | --- | --- | --- | --- |
| R-001 | Public output is interpreted as investment advice | High | Growth Content SEO | Prominent disclaimers, methodology page, no guaranteed-return language |
| R-002 | Live trading appears accidentally | Critical | Security Trust | Keep readiness check, tests, and review gate blocking any order path |
| R-003 | KRX API key exists but endpoint approval or quota fails | Medium | Data Quality Reliability | Doctor probes, `auto` fallback, latency/quota logging before default switch |
| R-004 | DART/Naver/KRX data is stale or partially unavailable | High | Data Quality Reliability | Source freshness labels and missing-data warnings |
| R-005 | Supabase member data leaks across users | Critical | Security Trust | Bearer-token verification, owner checks, RLS migration review |
| R-006 | Analysis hallucination creates confident but unsupported claims | High | AI Evaluation Research | Evidence tags, prompt constraints, report validation, missing-data guardrails |
| R-007 | Vercel production alias points at old or missing deployment | High | Operations SRE | Alias check after deploy, readiness SHA check, runbook |
| R-008 | AdSense readiness conflicts with public crawlability | Medium | Growth Content SEO | Production domain no deployment protection, valid robots/sitemap/ads.txt |
| R-009 | Korean market tax/fee assumptions become outdated | Medium | Korean Market Domain | Periodic source review and visible "not tax advice" language |
| R-010 | Worker cron spends too much on LLM runs | Medium | Operations SRE | Low cron limits, dry-run commands, cost monitoring before scaling |
| R-011 | Trusted user header mode is exposed to browsers | High | Security Trust | Keep `TRADINGAGENTS_API_TRUST_MEMBER_USER_HEADER=false` unless behind verified auth proxy |
| R-012 | RLS missing in production Supabase | High | Security Trust | Schema/RLS readiness gate before member launch |
| R-013 | TLS verification disabled in production | High | Security Trust | Readiness failure or launch block when `TRADINGAGENTS_HTTP_VERIFY_SSL=false` |
| R-014 | Public API docs expose operational surface | Medium | Operations SRE | Keep `TRADINGAGENTS_API_DOCS_ENABLED=false` in production |
| R-015 | Manual portfolio is mistaken for broker-verified holdings | Medium | Product Planning | Label values as user-entered estimates until read-only broker review exists |
| R-016 | Per-user analysis refresh is abused or creates runaway cost | High | Operations SRE | Add quotas, duplicate suppression, audit logs, and operator alerting |
