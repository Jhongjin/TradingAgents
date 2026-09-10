"""Regenerate tradingagents/dataflows/data/kr_tickers.json from Naver's market-cap listing.

Walks every KOSPI and KOSDAQ page (ETFs and SPACs included) and writes a compact
JSON directory used by ticker search. Run from CI (GitHub Actions has the
network access that corporate desktops may lack):

    python scripts/build_kr_ticker_directory.py [--min-rows 1500] [--out path]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.dataflows.kr_ticker_directory import DIRECTORY_PATH, DirectoryEntry, write_directory  # noqa: E402
from tradingagents.screener.universe import load_naver_market_snapshot  # noqa: E402


NAVER_SECTOR_LIST = "https://finance.naver.com/sise/sise_group.naver"
NAVER_SECTOR_DETAIL = "https://finance.naver.com/sise/sise_group_detail.naver"
NAVER_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TradingAgents screener)"}


def _sector_map_from_naver() -> dict[str, str]:
    """Industry per ticker from Naver's 업종 pages.

    KRX's own classification endpoint refuses cloud addresses, which is where
    this rebuild runs. Naver groups the same listings by industry across about
    seventy pages, which is one request per industry rather than one per stock.
    """

    import re

    import requests

    mapping: dict[str, str] = {}
    try:
        listing = requests.get(NAVER_SECTOR_LIST, params={"type": "upjong"}, headers=NAVER_HEADERS, timeout=15)
        listing.encoding = "euc-kr"
        listing.raise_for_status()
    except Exception as exc:
        print(f"sector list unavailable ({exc.__class__.__name__})")
        return {}

    groups = re.findall(r'sise_group_detail\.naver\?type=upjong&amp;no=(\d+)"[^>]*>([^<]+)<', listing.text)
    print(f"sector groups: {len(groups)}")
    for number, raw_name in groups:
        name = " ".join(raw_name.split())
        if not name:
            continue
        try:
            detail = requests.get(NAVER_SECTOR_DETAIL, params={"type": "upjong", "no": number}, headers=NAVER_HEADERS, timeout=15)
            detail.encoding = "euc-kr"
            detail.raise_for_status()
        except Exception:
            continue
        for code in re.findall(r"/item/main\.naver\?code=(\d{6})", detail.text):
            mapping.setdefault(code, name)
    return mapping


def _sector_map() -> dict[str, str]:
    """Industry group per ticker from KRX, or an empty map when it is unreachable.

    A missing sector must never fail the rebuild: the directory's job is names
    and codes, and the sector is an extra the concentration rule can do without.
    """

    try:
        from pykrx import stock
    except Exception as exc:
        print(f"sector lookup unavailable ({exc.__class__.__name__}); continuing without sectors")
        return {}
    mapping: dict[str, str] = {}
    dates = [(datetime.now() - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(0, 6)]

    # First choice: KRX's own classification table.
    for market in ("KOSPI", "KOSDAQ"):
        for day in dates:
            try:
                frame = stock.get_market_sector_classifications(day, market)
            except Exception:
                continue
            if frame is None or getattr(frame, "empty", True):
                continue
            column = next((name for name in ("업종명", "지수명", "SectorName") if name in frame.columns), None)
            if column is None:
                continue
            for code, value in zip(frame.index, frame[column]):
                text = str(value or "").strip()
                if text:
                    mapping.setdefault(str(code).zfill(6), text)
            break
    if mapping:
        return mapping

    print("KRX sector table unavailable; reading Naver 업종 pages instead")
    return _sector_map_from_naver()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-rows", type=int, default=1500, help="fail if fewer rows were collected (guards against a broken page)")
    parser.add_argument("--out", type=Path, default=DIRECTORY_PATH)
    args = parser.parse_args()

    snapshot = load_naver_market_snapshot(markets=("KOSPI", "KOSDAQ"), max_rows_per_market=5000, include_non_equity=True)
    sectors = _sector_map()
    entries = [DirectoryEntry(code=row.code, name=row.name, market=row.market, sector=sectors.get(row.code, "")) for row in snapshot.rows]
    print(f"sector labels: {sum(1 for e in entries if e.sector)}/{len(entries)}")
    kospi = sum(1 for e in entries if e.market == "KOSPI")
    kosdaq = sum(1 for e in entries if e.market == "KOSDAQ")
    print(f"collected {len(entries)} rows (KOSPI {kospi}, KOSDAQ {kosdaq}) from {snapshot.vendor}")
    if len(entries) < args.min_rows:
        print(f"too few rows (< {args.min_rows}); keeping the existing directory", file=sys.stderr)
        return 2
    target = write_directory(entries, args.out)
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
