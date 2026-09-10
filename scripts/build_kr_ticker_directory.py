"""Regenerate tradingagents/dataflows/data/kr_tickers.json from Naver's market-cap listing.

Walks every KOSPI and KOSDAQ page (ETFs and SPACs included) and writes a compact
JSON directory used by ticker search. Run from CI (GitHub Actions has the
network access that corporate desktops may lack):

    python scripts/build_kr_ticker_directory.py [--min-rows 1500] [--out path]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.dataflows.kr_ticker_directory import DIRECTORY_PATH, DirectoryEntry, write_directory  # noqa: E402
from tradingagents.screener.universe import load_naver_market_snapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-rows", type=int, default=1500, help="fail if fewer rows were collected (guards against a broken page)")
    parser.add_argument("--out", type=Path, default=DIRECTORY_PATH)
    args = parser.parse_args()

    snapshot = load_naver_market_snapshot(markets=("KOSPI", "KOSDAQ"), max_rows_per_market=5000, include_non_equity=True)
    entries = [DirectoryEntry(code=row.code, name=row.name, market=row.market) for row in snapshot.rows]
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
