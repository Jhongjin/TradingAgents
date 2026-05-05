"""Run non-secret preflight checks for the Korean-market setup."""

from __future__ import annotations

from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradingagents.ops.korea_doctor import format_results, has_failures, run_korea_market_checks


def main() -> int:
    load_dotenv(ROOT / ".env")
    results = run_korea_market_checks()
    print(format_results(results))
    return 1 if has_failures(results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
