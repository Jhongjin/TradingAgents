"""Regenerate tradingagents/dataflows/data/kr_tickers.json from Naver's market-cap listing.

Walks every KOSPI and KOSDAQ page (ETFs and SPACs included) and writes a compact
JSON directory used by ticker search. Run from CI (GitHub Actions has the
network access that corporate desktops may lack):

    python scripts/build_kr_ticker_directory.py [--min-rows 1500] [--out path]
"""

from __future__ import annotations

import argparse
from datetime import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.dataflows.kr_ticker_directory import DIRECTORY_PATH, DirectoryEntry, write_directory  # noqa: E402
from tradingagents.screener.universe import load_naver_market_snapshot  # noqa: E402


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
    today = datetime.now().strftime("%Y%m%d")
    for market in ("KOSPI", "KOSDAQ"):
        try:
            frame = stock.get_market_sector_classifications(today, market)
        except Exception as exc:
            print(f"sector lookup failed for {market} ({exc.__class__.__name__})")
            continue
        if frame is None or frame.empty:
            continue
        column = next((name for name in ("업종명", "지수명", "SectorName") if name in frame.columns), None)
        if column is None:
            continue
        for code, value in zip(frame.index, frame[column]):
            text = str(value or "").strip()
            if text:
                mapping[str(code).zfill(6)] = text
    return mapping


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
