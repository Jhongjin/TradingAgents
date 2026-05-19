# 06 Korean Market Domain

## Mandate

Ensure Korean-market assumptions, terminology, and calculations are accurate
enough for a public investor-facing research service.

## Responsibilities

- KOSPI/KOSDAQ ticker and market classification
- KRX calendar, sessions, price limits, and tick-size assumptions
- KRW chart and portfolio conventions
- DART disclosure interpretation
- Korean news context and event language
- benchmark-alpha and outcome framing
- tax/fee assumptions with visible caveats

## Source Hierarchy

1. official Korean sources: KRX, DART, law.go.kr, National Tax Service
2. exchange/vendor API responses from configured credentials
3. persisted internal analysis and outcomes
4. pykrx data used as an implementation source
5. third-party articles only for context, never as primary rules

## Knowledge Queue

- Verify KRX API field meanings for KOSPI and KOSDAQ daily trade endpoints.
- Confirm current transaction tax and fee assumptions before public methodology
  publication.
- Build a glossary for Korean investor-facing terms.
- Define how to explain benchmark alpha to non-professional users.

