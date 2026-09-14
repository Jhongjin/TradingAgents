"""Walk the live site and report what each page costs and whether it works."""

from __future__ import annotations

import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from tradingagents.dataflows.http_trust import apply_system_truststore_if_available

apply_system_truststore_if_available()

BASE = sys.argv[1] if len(sys.argv) > 1 else "https://agenttrust.kr"

PAGES = [
    "/", "/start", "/stocks", "/analyses", "/outcomes", "/harness", "/paper",
    "/pricing", "/member", "/mypage", "/billing", "/features", "/lab/gold",
    "/terms", "/privacy", "/disclaimer",
]
FEEDS = ["/robots.txt", "/sitemap.xml", "/llms.txt", "/site.webmanifest", "/health", "/api/readiness"]
APIS = [
    "/api/screener", "/api/analyses", "/api/analysis-outcomes", "/api/harness/runs",
    "/api/harness/runs/latest", "/api/harness/outcomes", "/api/paper-account",
    "/api/paper-account/curve", "/api/billing/plans", "/api/prices/latest",
    "/api/tickers/search?q=삼성", "/api/backtest", "/api/factor-study",
    "/lab/gold/data", "/lab/gold/quote",
]
GUARDED = [
    "/api/member/dashboard", "/api/portfolios", "/api/watchlists",
    "/api/member/preferences", "/api/admin/members", "/api/admin/ops-summary",
]


def fetch(path: str) -> dict:
    url = BASE + path
    start = time.perf_counter()
    try:
        response = requests.get(url, timeout=45, headers={"User-Agent": "agenttrust-qa/1.0"})
    except Exception as exc:                       # noqa: BLE001 - the report is the point
        return {"path": path, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "path": path,
        "status": response.status_code,
        "ms": round((time.perf_counter() - start) * 1000),
        "kb": round(len(response.content) / 1024, 1),
        "type": (response.headers.get("content-type") or "").split(";")[0],
        "cache": response.headers.get("cache-control") or "-",
        "text": response.text,
    }


def run(paths: list[str]) -> list[dict]:
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(fetch, paths))


def line(row: dict) -> str:
    if "error" in row:
        return f"  {row['path']:<34} ERROR {row['error'][:70]}"
    flag = " " if row["status"] < 400 else "!"
    return (f"{flag} {row['path']:<34} {row['status']} {row['ms']:>6}ms {row['kb']:>8.1f}KB "
            f"{row['type']:<26} {row['cache'][:38]}")


print(f"== {BASE} ==\n")
for label, paths in (("PAGES", PAGES), ("FEEDS", FEEDS), ("API", APIS)):
    print(f"-- {label}")
    rows = run(paths)
    for row in rows:
        print(line(row))
    if label == "PAGES":
        print("\n-- page health")
        for row in rows:
            if "error" in row or row["status"] >= 400:
                continue
            body = row["text"]
            notes = []
            if "<title>" not in body:
                notes.append("no <title>")
            if 'name="description"' not in body:
                notes.append("no description")
            if 'rel="canonical"' not in body:
                notes.append("no canonical")
            if "Traceback" in body or "Internal Server Error" in body:
                notes.append("SERVER ERROR IN BODY")
            inline_js = sum(len(block) for block in re.findall(r"<script[^>]*>(.*?)</script>", body, re.S))
            inline_css = sum(len(block) for block in re.findall(r"<style[^>]*>(.*?)</style>", body, re.S))
            notes.append(f"js {inline_js // 1024}KB css {inline_css // 1024}KB")
            print(f"  {row['path']:<34} {' | '.join(notes)}")
    print()

print("-- guarded (expect 401/403)")
for row in run(GUARDED):
    if "error" in row:
        print(line(row))
        continue
    verdict = "ok" if row["status"] in (401, 403) else "OPEN!"
    print(f"  {row['path']:<34} {row['status']} {verdict}")
