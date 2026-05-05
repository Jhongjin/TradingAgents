# Product Scope

This fork is a public Korean-stock AI analysis service first. User portfolio
tools, member features, and charts should support that core product instead of
pulling the roadmap away from it.

## Product Goal

Build a public website for Korean stock analysis that can earn ad revenue while
improving the original TradingAgents workflow:

- Korean stock data quality
- DART/Naver/KRX vendor reliability
- Multi-agent analysis completeness
- Benchmark alpha and backtest quality
- Safe paper execution and transparent risk reporting

The site must not present AI output as guaranteed profit, personalized legal or
tax advice, or live trading instruction.

## Primary Scope

These are the product's main jobs:

- Public Korean stock pages by 6-digit ticker code
- AI market, news, fundamentals, debate, trader, and risk reports
- DART disclosure and financial-statement summaries
- Naver/Korean-market news context
- pykrx/KRX OHLCV and benchmark-relative performance
- KRW paper/backtest reports
- Clear data-source, timestamp, and investment-risk disclaimers
- SEO-friendly public pages and ad placements

## Secondary Scope

These features are useful, but they must remain secondary to the core AI
analysis experience:

- Member signup and saved watchlists
- Manual portfolio entry
- Buy/sell history entered by the user
- Average cost, realized/unrealized PnL, position weight, target/stop checks
- Portfolio-level risk summaries based on user-entered data
- Saved analysis history and alerts

Manual portfolio entry is preferred before broker integration because it avoids
collecting broker access media, account passwords, OTPs, or certificate secrets.
The matching framework-neutral payload builder is
`tradingagents.site.build_manual_portfolio_payload`, which summarizes
user-entered trades, current prices supplied by the app, target/stop alerts, and
PnL estimates without broker account access.

## Chart Scope

Charts are valuable, but they are not the first bottleneck. Start with a simple
read-only chart after the core analysis pages work:

- Candlestick or OHLC chart
- Volume bars
- Moving averages
- Date range selector
- Basic responsive layout

Defer advanced charting until later:

- Drawing tools
- Multi-indicator workbench
- Multi-timeframe overlays
- TradingView-like customization
- Real-time streaming

Reference direction: AlphaSquare-style market summary pages, such as
`https://alphasquare.co.kr/home/market/market-summary?code=005930`, are useful
as product inspiration. Do not clone their UI or copy proprietary content.

The backend chart data shape starts in `tradingagents.dataflows.chart_data`.
It returns JSON-friendly OHLCV points from pykrx today, with a vendor boundary
so KRX Open API can replace the source later without changing the web layer.
The same module exposes latest close-price snapshots so manual portfolio pages
can value holdings without coupling directly to pykrx.

The first framework-neutral public page payload builder is
`tradingagents.site.build_public_stock_payload`. It combines ticker metadata,
latest persisted public analysis, optional OHLCV chart points, and investment
risk notices into a JSON-ready shape that can sit behind a future Next.js,
FastAPI, or Vercel API route. The payload also includes an `analysis_refresh`
hint so the web layer can show cached completed analysis while deciding whether
a background refresh should be queued.

The first HTTP adapter is `tradingagents.site.create_app`, a read-only FastAPI
surface with `/api/stocks/{ticker}` and `/api/portfolio/{portfolio_id}` routes.
It is deliberately thin: route handlers validate HTTP inputs and delegate to the
framework-neutral payload builders.

## Broker Integration Boundary

Broker integration is not part of the initial public launch.

When added, it should start as read-only account management:

- Holdings
- Cash and buying power, if available through an approved read-only API
- Fill/order history
- Evaluation PnL
- User-side target and stop calculations

Still deferred:

- Live orders
- Automated trading
- One-click buy/sell
- Account password, certificate, OTP, or access-media collection

Any live trading capability requires a separate legal, security, product, and
risk review before implementation.

## Recommended Build Order

1. Public stock analysis page
2. Analysis run storage
3. SEO/ad-ready public pages
4. Member signup and watchlists
5. Manual portfolio entry
6. Portfolio PnL and risk dashboard
7. Basic read-only charts
8. Broker read-only integration review
