# Korean Market Source Map

## Primary Sources

| Area | Source | Use |
| --- | --- | --- |
| Exchange rules and market structure | KRX official sites | market hours, price limits, market classifications |
| Daily trade data | KRX Open API | KOSPI/KOSDAQ OHLCV diagnostics and future primary source |
| Disclosure and financial filings | OpenDART | filings, financial statement data, receipt numbers |
| Korean news context | Naver Search API | public news links and recent issue context |
| Laws and enforcement decrees | law.go.kr | tax and regulatory rule verification |
| Tax overview | National Tax Service | public caveats and review checkpoints |

## Internal Source Surfaces

- `tradingagents/dataflows/krx_openapi.py`
- `tradingagents/dataflows/pykrx_vendor.py`
- `tradingagents/dataflows/dart.py`
- `tradingagents/dataflows/naver_news.py`
- `tradingagents/dataflows/chart_data.py`
- `tradingagents/dataflows/kr_returns.py`
- `tradingagents/site/public_api.py`

## Review Cadence

- KRX API endpoint fields: after approval changes and before switching defaults
- KRX quota/latency: weekly during public beta
- Tax/fee assumptions: quarterly or before public methodology updates
- Market hours/price limits: quarterly or after exchange notice changes
- Public disclaimers: before each major public launch

