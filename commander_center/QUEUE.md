# Cross-Team Queue

This queue is intentionally high level. Workstream folders hold deeper notes.

## Active Priorities

| Priority | Item | Lead | Supporting Workstreams | Status |
| --- | --- | --- | --- | --- |
| P1 | Verify production alias and readiness after every deploy | Operations SRE | QA Verification | active |
| P1 | Member signup/login/email redirect browser test | QA Verification | Security Trust, Product Planning | browser-safe path verified; live email redirect blocked on Supabase/test mailbox |
| P1 | KRX approved API probe and chart-vendor `auto` stability | Data Quality Reliability | Korean Market Domain, Engineering Platform | shipped |
| P2 | Public homepage trust and design polish | Design Experience | Growth Content SEO, QA Verification | shipped |
| P2 | Manual portfolio UX: trades, average cost, PnL, target/stop | Product Planning | Engineering Platform, QA Verification | shipped |
| P2 | Watchlist UX and public analysis request flow | Product Planning | Engineering Platform, Design Experience | shipped |
| P2 | Public analysis report storage and feed quality | AI Evaluation Research | Data Quality Reliability, Growth Content SEO | shipped |
| P2 | 5D/20D outcome worker operational runbook | Operations SRE | AI Evaluation Research, Data Quality Reliability | shipped |
| P2 | Public methodology and trust page | Growth Content SEO | Korean Market Domain, AI Evaluation Research, Security Trust | shipped |
| P2 | Vendor/readiness dashboard design | Operations SRE | Data Quality Reliability, Design Experience | shipped |
| P2 | Per-user analysis request quotas and duplicate suppression | Operations SRE | Security Trust, Engineering Platform | shipped |
| P2 | Rendered report provenance metadata audit | Data Quality Reliability | AI Evaluation Research, Growth Content SEO | shipped |
| P2 | Production security readiness additions for TLS/API-docs/trust-header | Security Trust | Operations SRE, Engineering Platform | shipped |

## Trust-Building Backlog

- Shipped: Add source and freshness labels to key public stock data blocks.
- Shipped: Add public methodology page explaining data sources, AI limits, and
  outcome verification.
- Shipped: Add analysis confidence and missing-data warnings instead of silent
  fallbacks.
- Add queue transparency for member analysis requests.
- Add vendor latency/quota measurement for KRX, DART, and Naver.
- Add systematic hallucination checks for generated analysis reports.
- Add public track-record cards once enough outcomes exist.

## User-Action Blockers

- AdSense publisher ID and `ads.txt` after approval.
- Supabase email redirect dashboard settings for final domain and a test mailbox
  to verify the real confirmation link end to end.
- KRX API quota/latency confirmation after real-world use.
- Any legal/compliance review before broker read-only integration.
