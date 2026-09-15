"""The second layer: how the site behaves when things are wrong or odd.

    python scripts/qa_deep.py [base-url]

Bad input, missing pages, hostile input, redirects, duplicate content, and
whether the numbers one page shows agree with the numbers another one does.
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import requests

from tradingagents.dataflows.http_trust import apply_system_truststore_if_available

apply_system_truststore_if_available()
BASE = sys.argv[1] if len(sys.argv) > 1 else "https://agenttrust.kr"
session = requests.Session()
session.headers["User-Agent"] = "agenttrust-qa/1.0"


def get(path: str, **kwargs):
    return session.get(BASE + path, timeout=90, **kwargs)


print(f"===== {BASE} : 심층 =====")

print("\n[1] 없는 것을 찾을 때")
missing = {
    "/does-not-exist": 404,
    "/stocks/999999": (200, 404),
    "/harness/00000000-0000-0000-0000-000000000000": 404,
    "/analyses/00000000-0000-0000-0000-000000000000": 404,
    "/features/nope": 404,
    "/api/stocks/999999": (200, 404, 422),
    "/api/harness/runs/00000000-0000-0000-0000-000000000000": 404,
}
for path, expected in missing.items():
    wanted = expected if isinstance(expected, tuple) else (expected,)
    response = get(path)
    ok = response.status_code in wanted
    body = response.text
    leaked = "Traceback" in body or "sqlalchemy" in body.lower() or "psycopg" in body.lower()
    note = "ok" if ok else f"!! {wanted} 예상"
    if leaked:
        note += "  !! 내부 오류 노출"
    print(f"  {path:<52} {response.status_code} {note}")

print("\n[2] 이상한 입력 (5xx 가 나오면 안 됨)")
bad = [
    "/api/screener?top_n=0", "/api/screener?top_n=999", "/api/screener?markets=NYSE",
    "/api/screener?as_of_date=notadate", "/api/screener?min_market_cap=-1",
    "/api/forecast/005930?horizon_days=0", "/api/forecast/005930?horizon_days=9999",
    "/api/forecast/%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "/api/tickers/search?q=", "/api/tickers/search?q=" + "가" * 300,
    "/api/tickers/search?q=%27%20OR%201%3D1--",
    "/api/stocks/005930?chart_vendor=../../etc/passwd",
    "/api/prices/sparkline?codes=" + ",".join(["005930"] * 200),
    "/lab/gold?bars=1", "/lab/gold?bars=99999", "/lab/gold?intervals=" + "x" * 200,
]
for path in bad:
    response = get(path)
    flag = "!!" if response.status_code >= 500 else "  "
    leaked = "Traceback" in response.text or "sqlalchemy" in response.text.lower()
    print(f"{flag} {path[:64]:<66} {response.status_code}{'  !! 내부 노출' if leaked else ''}")

print("\n[3] 반사 (XSS)")
probe = "<script>alert(1)</script>"
for path in (f"/api/tickers/search?q={probe}", f"/stocks?q={probe}", f"/analyses?ticker={probe}"):
    response = get(path)
    kind = (response.headers.get("Content-Type") or "").split(";")[0]
    # Echoing the query inside a JSON string is not an injection: the browser
    # will not parse application/json as markup, and nosniff stops it trying.
    inert = kind == "application/json" and response.headers.get("X-Content-Type-Options") == "nosniff"
    reflected = probe in response.text and not inert
    verdict = "!! 원문 반사" if reflected else ("ok (JSON)" if inert else "ok")
    print(f"  {path[:60]:<62} {response.status_code}  {verdict}")

print("\n[4] 리다이렉트와 정규 주소")
for url in ("http://agenttrust.kr/", "https://www.agenttrust.kr/", f"{BASE}/paper/", f"{BASE}/PAPER"):
    try:
        response = session.get(url, timeout=60, allow_redirects=False)
        print(f"  {url:<40} {response.status_code} -> {response.headers.get('Location') or '-'}")
    except Exception as exc:                                       # noqa: BLE001
        print(f"  {url:<40} ERR {type(exc).__name__}")

print("\n[5] 색인 정책")
pages = ["/", "/start", "/stocks", "/analyses", "/outcomes", "/harness", "/paper", "/pricing",
         "/features", "/terms", "/privacy", "/disclaimer", "/member", "/mypage", "/billing", "/lab/gold"]
sitemap = set(re.findall(r"<loc>([^<]+)</loc>", get("/sitemap.xml").text))
with ThreadPoolExecutor(max_workers=6) as pool:
    bodies = dict(zip(pages, pool.map(lambda path: get(path).text, pages)))
for path in pages:
    body = bodies[path]
    noindex = "noindex" in (re.search(r'<meta name="robots"[^>]*>', body) or type("x", (), {"group": lambda self: ""})()).group()
    canonical = (re.search(r'<link rel="canonical" href="([^"]+)"', body) or type("x", (), {"group": lambda self, n: "-"})()).group(1)
    in_sitemap = canonical in sitemap
    verdict = []
    if noindex and in_sitemap:
        verdict.append("!! noindex 인데 사이트맵에 있음")
    if not noindex and not in_sitemap:
        verdict.append("색인 대상인데 사이트맵에 없음")
    if canonical != "-" and not canonical.startswith(BASE):
        verdict.append(f"!! canonical 이 외부: {canonical}")
    print(f"  {path:<14} {'noindex' if noindex else 'index  '}  canonical {canonical.replace(BASE, '') or '/':<28} {' · '.join(verdict) or 'ok'}")

print("\n[6] 숫자가 서로 맞는가")
account = get("/api/paper-account").json()
curve = get("/api/paper-account/curve").json()
harness = get("/api/harness/runs/latest").json()
summary = account.get("summary") or {}
positions = account.get("positions") or []
closed = account.get("closed") or []
print(f"  보유 {summary.get('open_count')} vs positions {len(positions)}: "
      f"{'ok' if summary.get('open_count') == len(positions) else '!! 불일치'}")
print(f"  종료 {summary.get('closed_count')} vs closed {len(closed)}: "
      f"{'ok' if summary.get('closed_count') == len(closed) else '!! 불일치'}")
equity, cash, holdings = (summary.get("equity"), summary.get("cash"), summary.get("holdings_value"))
if None not in (equity, cash, holdings):
    drift = abs(float(equity) - (float(cash) + float(holdings)))
    print(f"  평가금액 = 현금 + 보유평가 오차 {drift:,.0f}원: {'ok' if drift < 1 else '!! 불일치'}")
points = curve.get("points") or curve.get("curve") or []
print(f"  자산곡선 점 {len(points)}개")
run = harness.get("run") or {}
decisions = harness.get("decisions") or []
print(f"  최신 실행 {run.get('as_of_date')} · 결정 {len(decisions)}건 · 요약 {(harness.get('summary') or {}).get('decision_count')}")
codes = {row.get("ticker_code") for row in decisions if row.get("ticker_code")}
held = {row.get("ticker_code") for row in positions}
print(f"  주문된 종목이 계좌에 있는가: "
      f"{sorted(codes & held) or '겹치는 종목 없음 (오래된 실행이면 정상)'}")

print("\n[7] 선별 종목의 링크가 살아 있는가")
screener = get("/api/screener").json()
paths = [f"/stocks/{row['code']}" for row in (screener.get("candidates") or [])[:8]]
with ThreadPoolExecutor(max_workers=6) as pool:
    codes_out = list(pool.map(lambda path: (path, get(path).status_code), paths))
broken = [(path, status) for path, status in codes_out if status != 200]
print(f"  후보 종목 페이지 {len(paths)}개 · 실패 {len(broken)}개", broken or "")

print("\n[8] 캐시가 로그인 응답을 섞지 않는가")
for path in ("/api/paper-account", "/api/backtest", "/api/screener"):
    anon = get(path).headers.get("Cache-Control")
    authed = get(path, headers={"Authorization": "Bearer not-a-real-token"}).headers.get("Cache-Control")
    ok = (anon or "").startswith("public") and authed == "private, no-store"
    print(f"  {path:<24} 익명 {anon:<38} 로그인 {authed}  {'ok' if ok else '!! 확인 필요'}")

print("\n[9] 데이터 신선도")
for path, key in (("/api/screener", "as_of_date"), ("/api/paper-account", "as_of_date"),
                  ("/api/harness/runs/latest", None), ("/api/analysis-outcomes", None)):
    body = get(path).json()
    stamp = body.get(key) if key else (body.get("generated_at") or (body.get("run") or {}).get("as_of_date"))
    print(f"  {path:<30} {stamp}")
