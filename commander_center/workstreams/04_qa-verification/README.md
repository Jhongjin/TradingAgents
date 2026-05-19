# 04 QA Verification

## Mandate

Prove that public and member flows work before release. QA owns the evidence,
not just the checklist.

## Responsibilities

- focused tests for changed behavior
- full regression tests before commit
- browser checks for public/member pages
- API readiness and payload checks
- smoke tests for Korean tickers such as `005930` and `086520`

## Browser Checklist

- no console errors or warnings
- no horizontal overflow
- important text visible at desktop and mobile widths
- auth state messages match actual state
- public stock pages load chart and analysis fallback states
- member flows protect private data and noindex surfaces

## Release Evidence

Every release note should include:

- test command and result
- browser URLs checked
- readiness status
- deployment SHA or alias status

