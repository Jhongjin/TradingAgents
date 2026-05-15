# Korean Market Operations

This fork keeps Korean-market execution in paper/backtest mode until live
broker support is explicitly designed and reviewed.

## Preflight

Run the local preflight before smoke tests or deployments:

```powershell
.\.venv\Scripts\python.exe scripts\doctor_korea_market.py
```

The doctor prints only non-secret status. It validates:

- LLM, DART, and Naver credential presence
- KIS paper credential shape
- KRX Open API key presence, if already approved
- Optional KRX Open API service approval with `TRADINGAGENTS_DOCTOR_CHECK_KRX_ONLINE=true`
- HTTPS verification and optional CA bundle path

## Local Smoke

Run the Korean-market smoke without invoking an LLM:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_korea_market.py
```

Expected state before KRX approval:

- `pykrx`: OK
- `dart`: OK when `DART_API_KEY` is configured
- `naver`: OK unless local Windows/corporate SSL interception blocks Python trust
- `kis`: OK when paper credential shape is valid
- `krx`: SKIP until `KRX_API_KEY` or `KRX_OPENAPI_KEY` is approved

After KRX approval, keep pykrx as the default public chart vendor until quota
and latency are measured. Set `TRADINGAGENTS_CHART_DATA_VENDOR=auto` to try KRX
first and fall back to pykrx, or use `TRADINGAGENTS_CHART_DATA_VENDOR=krx` /
`/api/stocks/005930?chart_vendor=krx` for explicit KRX-only diagnostics.

For local Naver SSL failures, prefer fixing `TRADINGAGENTS_HTTP_CA_BUNDLE`.
For Vercel/Linux deployment, a custom bundle is usually not needed.
On Windows, the project can also use the OS certificate store through the
optional `truststore` package. Keep `TRADINGAGENTS_HTTP_USE_SYSTEM_CERTS=true`
for local diagnostics when PowerShell/browser HTTPS works but Python reports
`self-signed certificate in certificate chain`.

To diagnose a KRX key that is configured but rejected by the API, run:

```powershell
$env:TRADINGAGENTS_DOCTOR_CHECK_KRX_ONLINE="true"
.\.venv\Scripts\python.exe scripts\doctor_korea_market.py
```

Use either `KRX_API_KEY` or `KRX_OPENAPI_KEY`; if both are configured,
`KRX_API_KEY` takes precedence. The doctor warns when both aliases differ or
when a copied key contains leading/trailing whitespace.

The probe calls Samsung Electronics (`005930`) for the last completed business
day, or the date in `TRADINGAGENTS_DOCTOR_KRX_PROBE_DATE`. A 401-style failure
usually means the Vercel/local key value, product type, or KRX service-level API
approval still needs to be corrected in the KRX dashboard. When the raw KRX
response is `Unauthorized API Call`, verify that the exact auth key has
service-level approval for `sto/stk_bydd_trd` (`유가증권 일별매매정보`). When
it is `Unauthorized Key`, re-copy the Open API auth key itself.

## Korean Execution Assumptions

Paper/backtest execution applies these Korean-market assumptions:

- Regular session: 09:00 to 15:30 Asia/Seoul
- Daily price limit: plus/minus 30% from the base price
- Upper/lower limit width is truncated to the base-price tick unit
- KRW execution prices are rounded to KRX tick units
- Sell-side listed-stock transaction costs are modeled by market:
  - KOSPI: 0.20% total, including the KOSPI rural special tax component
  - KOSDAQ: 0.20%
  - KONEX: 0.10%

These rates are for backtesting realism, not tax advice. Re-check laws and
broker statements before any live trading workflow.

## Deployment Notes

For Vercel or another hosted runtime, configure environment variables in the
platform dashboard instead of committing secrets:

- `OPENAI_API_KEY`
- `DART_API_KEY`
- `NAVER_CLIENT_ID`
- `NAVER_CLIENT_SECRET`
- `KIS_IS_PAPER=true`
- `KIS_APP_KEY`
- `KIS_APP_SECRET`
- `KIS_ACCOUNT_NO`
- `KIS_ACCOUNT_PRODUCT_CODE`
- `KRX_API_KEY` or `KRX_OPENAPI_KEY` once approved
- `TRADINGAGENTS_CHART_DATA_VENDOR=pykrx` by default; use `auto` for KRX-first fallback or `krx` for diagnostics

Do not set `TRADINGAGENTS_HTTP_VERIFY_SSL=false` in production.

## Sources

- KRX global market rules: https://global.krx.co.kr/
- KRX regulation page for KOSDAQ price limits: https://regulation.krx.co.kr/contents/RGL/03/03020201/RGL03020201.jsp
- Securities Transaction Tax Act Enforcement Decree, Article 5: https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joBrNo=00&joNo=0005&lsiSeq=280901&urlMode=lsScJoRltInfoR
- National Tax Service stock capital-gains overview: https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=8800
