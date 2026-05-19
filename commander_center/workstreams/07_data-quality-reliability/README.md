# 07 Data Quality Reliability

## Mandate

Make data freshness, source quality, fallback behavior, and vendor failures
visible and testable.

## Responsibilities

- KRX, pykrx, DART, and Naver adapter reliability
- fallback rules and source labels
- vendor latency and quota measurement
- chart data cache strategy
- payload validation for public pages
- stale/missing data warnings

## Quality Checks

- KOSPI probe: `005930`
- KOSDAQ probe: `086520`
- chart vendor modes: `pykrx`, `krx`, and `auto`
- readiness with and without `probe_krx=true`
- DART and Naver configured/online status
- response field mapping and null handling

## Output Standard

Public payloads should make these clear:

- source vendor
- generated timestamp
- number of data points
- missing vendor reason, if any
- fallback source, if any

