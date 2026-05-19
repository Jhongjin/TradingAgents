# Best-Team Roster

The Commander Center uses specialist workstreams, not generic helpers. Each
workstream has a mandate, decision rights, and launch-blocking authority for
its domain.

## 00 Commander Center

Owns prioritization, dispatch, integration, and final ship/no-ship decisions.
Keeps the product aligned with the public Korean-stock AI analysis mission.
For releases, it acts as the Release Council and can freeze deploys, workers,
or analysis refreshes when trust or accuracy is at risk.

## 01 Product Planning

Turns business goals into scoped user flows, launch milestones, and queue items.
Protects the core product from drifting into broker execution too early.

## 02 Design Experience

Owns information architecture, visual trust, interaction clarity, responsive
quality, and member/public page usability.

## 03 Engineering Platform

Owns backend, frontend, storage, API contracts, worker queues, migrations,
deployment, and maintainability.

## 04 QA Verification

Owns test strategy, smoke checks, browser verification, regression plans, and
release evidence.

## 05 Security Trust

Owns secrets handling, auth boundaries, Supabase policies, CORS, read-only
broker posture, abuse controls, and incident response.

## 06 Korean Market Domain

Owns KRX/KOSPI/KOSDAQ market assumptions, ticker semantics, trading calendar,
tick sizes, transaction-cost assumptions, DART/Naver/KRX source interpretation,
and user-facing financial caveats.

## 07 Data Quality Reliability

Owns vendor availability, fallback logic, caching, provenance labels, schema
validation, freshness checks, and reconciliation across pykrx, KRX, DART, and
Naver.

## 08 AI Evaluation Research

Owns agent prompt quality, hallucination controls, report structure,
benchmark-alpha interpretation, outcome evaluation, and model-cost discipline.

## 09 Growth Content SEO

Owns public analysis feed quality, stock-page SEO, sitemap/robots, AdSense
readiness, editorial guidelines, and content trust language.

## 10 Operations SRE

Owns readiness, cron safety, uptime checks, Vercel aliases, deployment rollback
notes, observability, and operational runbooks.

## 11 Compliance Policy

Owns financial-risk wording, no-advice boundaries, Korean/English disclaimers,
tax/legal caveats, broker-integration approval gates, and periodic regulatory
assumption reviews.

## 12 User Trust Support

Owns user-facing explanations, support feedback loops, help copy, incident
communications, and recurring confusion signals from members or public readers.

## Launch-Blocking Authority

Any of these workstreams may block a public release:

- Security Trust: data leak, auth bypass, live-trading exposure, secret risk
- Compliance Policy: advice-like claims, missing disclaimers, stale regulatory assumptions
- Korean Market Domain: materially wrong market assumption or misleading claim
- Data Quality Reliability: stale, unlabeled, or silently failed public data
- QA Verification: untested critical path or broken public/member flow
- Operations SRE: failed readiness or broken production alias

## Operating Rhythm

- Daily: readiness, domain alias, failed worker queue, and vendor-health check.
- Weekly: public analysis quality review, 5D/20D outcome review, risky-copy
  audit, and top user-flow friction review.
- Pre-release: all applicable gates in `GATES.md` must be satisfied by the
  responsible workstream plus Commander Center.
- Incident mode: freeze expensive or risky analysis refreshes first, keep cached
  public pages available when safe, then restore vendors/workers after root
  cause is understood.
