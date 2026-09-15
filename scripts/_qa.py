"""Walk the live site and report what works, what costs, and what is exposed."""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from tradingagents.dataflows.http_trust import apply_system_truststore_if_available

apply_system_truststore_if_available()
BASE = sys.argv[1] if len(sys.argv) > 1 else "https://agenttrust.kr"

session = requests.Session()
session.headers["User-Agent"] = "agenttrust-qa/1.0"

PAGES = ["/", "/start", "/stocks", "/analyses", "/outcomes", "/harness", "/paper", "/pricing",
         "/member", "/mypage", "/billing", "/features", "/lab/gold", "/terms", "/privacy", "/disclaimer"]
FEEDS = ["/robots.txt", "/sitemap.xml", "/llms.txt", "/site.webmanifest", "/health", "/favicon.ico", "/og/home.png"]
APIS = ["/api/screener", "/api/analyses", "/api/analysis-outcomes", "/api/harness/runs",
        "/api/harness/runs/latest", "/api/harness/outcomes", "/api/paper-account",
        "/api/paper-account/curve", "/api/billing/plans", "/api/tickers/search?q=삼성",
        "/api/backtest", "/api/factor-study", "/lab/gold/data", "/lab/gold/quote"]
GUARDED = ["/api/member/dashboard", "/api/portfolios", "/api/watchlists", "/api/member/preferences",
           "/api/member/picks", "/api/analysis-requests", "/api/admin/members", "/api/admin/ops-summary",
           "/api/cron/refresh-screener", "/api/cron/refresh-valuations", "/api/cron/run-harness",
           "/api/cron/record-paper-snapshot", "/api/cron/notify-exits"]


def get(path: str) -> dict:
    started = time.perf_counter()
    try:
        response = session.get(BASE + path, timeout=90)
    except Exception as exc:                                       # noqa: BLE001
        return {"path": path, "status": f"ERR {type(exc).__name__}", "ms": 0, "kb": 0, "body": "", "headers": {}}
    return {
        "path": path,
        "status": response.status_code,
        "ms": round((time.perf_counter() - started) * 1000),
        "kb": round(len(response.content) / 1024, 1),
        "body": response.text,
        "headers": dict(response.headers),
    }


def sweep(paths: list[str], workers: int = 6) -> list[dict]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(get, paths))


def report(label: str, rows: list[dict]) -> list[dict]:
    print(f"\n-- {label}")
    for row in rows:
        flag = " " if row["status"] == 200 else "!"
        cache = (row["headers"].get("Cache-Control") or "-")[:34]
        print(f"{flag} {row['path']:<32} {row['status']} {row['ms']:>6}ms {row['kb']:>7.1f}KB  {cache}")
    return rows


print(f"===== {BASE} =====")
print("\n[1] 전체 경로 (1차: 캐시 없음)")
pages = report("PAGES", sweep(PAGES))
feeds = report("FEEDS", sweep(FEEDS))
apis = report("API", sweep(APIS))

print("\n[2] 2차 (캐시 적용 후)")
warm = {row["path"]: row["ms"] for row in sweep(PAGES + APIS)}
slow = sorted(((ms, path) for path, ms in warm.items() if ms > 1500), reverse=True)
print("  1.5초 넘는 경로:", ", ".join(f"{path} {ms}ms" for ms, path in slow) if slow else "없음")

print("\n[3] 인증 가드")
for row in sweep(GUARDED):
    verdict = "ok" if row["status"] in (401, 403, 503) else "!! 열려 있음"
    print(f"  {row['path']:<36} {row['status']} {verdict}")

print("\n[4] 마크업 · 접근성")
for row in pages:
    if row["status"] != 200:
        continue
    body, notes = row["body"], []
    if "<title>" not in body:
        notes.append("title 없음")
    if "Traceback" in body or "Internal Server Error" in body:
        notes.append("!! 본문에 서버 오류")
    images = re.findall(r"<img\b[^>]*>", body)
    if [tag for tag in images if "alt=" not in tag]:
        notes.append("alt 없는 img")
    ids = Counter(re.findall(r'\sid="([^"]+)"', body))
    if [name for name, count in ids.items() if count > 1]:
        notes.append("중복 id")
    if re.search(r'\son(click|load|error|change|submit)="', body):
        notes.append("인라인 핸들러")
    if 'lang="ko"' not in body:
        notes.append("lang 누락")
    print(f"  {row['path']:<32} {' | '.join(notes) if notes else 'ok'}")

print("\n[5] 보안 헤더")
headers = pages[0]["headers"]
for name in ("Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options",
             "Referrer-Policy", "Strict-Transport-Security", "Permissions-Policy"):
    print(f"  {name:<28} {'있음' if name in headers else '!! 없음'}")

print("\n[6] 내부 링크")
found: dict[str, set[str]] = {}
for row in pages:
    for href in re.findall(r'href="(/[^"#?]*)"', row["body"]):
        found.setdefault(href, set()).add(row["path"])
checked = sweep(sorted(found), workers=8)
broken = [row for row in checked if row["status"] != 200]
print(f"  링크 {len(checked)}개 · 깨진 링크 {len(broken)}개")
for row in broken:
    print(f"    {row['status']}  {row['path']}  <- {', '.join(sorted(found[row['path']]))}")

sitemap = next(row for row in feeds if row["path"] == "/sitemap.xml")["body"]
urls = sorted({url.split(BASE, 1)[-1] or "/" for url in re.findall(r"<loc>([^<]+)</loc>", sitemap)})
bad = [row for row in sweep(urls, workers=8) if row["status"] != 200]
print(f"  사이트맵 {len(urls)}개 · 실패 {len(bad)}개", "".join(f"\n    {r['status']} {r['path']}" for r in bad))

print("\n[7] 스크리너 내용")
screener = json.loads(next(row for row in apis if row["path"] == "/api/screener")["body"])
for note in screener.get("notes") or []:
    print("  -", note)
candidates = screener.get("candidates") or []
priced = sum(1 for row in candidates if row.get("per") is not None or row.get("pbr") is not None)
print(f"  후보 {len(candidates)}개 · 심사 {screener.get('universe_size')}종목 · 밸류에이션 있는 후보 {priced}/{len(candidates)}")
markets = Counter(row.get("market") for row in candidates)
print("  시장 분포:", dict(markets))
over = [(row["name"], row["per"]) for row in candidates if (row.get("per") or 0) > 60]
print("  PER 60 초과 통과:", over or "없음")

print("\n[8] 모의 계좌")
account = json.loads(next(row for row in apis if row["path"] == "/api/paper-account")["body"])
summary = account.get("summary") or {}
print(f"  상태 {account.get('status')} · 보유 {summary.get('open_count')} · 종료 {summary.get('closed_count')}"
      f" · 누적 {summary.get('total_return')}")

print("\n[9] 회원 페이지")
member = next(row for row in pages if row["path"] == "/member")["body"]
print("  구글 버튼:", "있음" if 'data-oauth-provider="google"' in member else "없음")
print("  카카오 흔적:", "!! 남아 있음" if "kakao" in member.lower() else "없음")
print("  providers:", re.search(r'"providers":\[[^\]]*\]', member).group() if '"providers"' in member else "-")
print("  소셜이 폼보다 위:", member.index('id="authSocial"') < member.index('id="authForm"'))
