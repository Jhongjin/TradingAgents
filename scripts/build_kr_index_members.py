"""Regenerate data/kr_index_members.json from the index ETFs' holdings.

An index ETF holds the index, so NH's ETF constituent call answers "who is in
KOSPI200/KOSDAQ150" without a KRX data-portal account. Membership changes at
the quarterly rebalance, so running this monthly is plenty.

    .codex-test-venv/Scripts/python.exe scripts/build_kr_index_members.py

Needs NH_APP_KEY / NH_APP_SECRET_KEY in .env. Writes nothing when a fetch comes
back short, so a bad afternoon at the gateway cannot shrink the universe.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradingagents.dataflows.kr_index_members import (  # noqa: E402
    INDEX_ETFS,
    MEMBERS_PATH,
    MIN_PLAUSIBLE,
    is_tradeable_code,
)

COMPONENTS_PATH = "/krstock/quote/v1/etfComponents"
COMPONENTS_TR = "IVOETPREQ10"


def fetch(client, etf_code: str) -> list[dict[str, str]]:
    """One ETF's holdings, minus the cash line every ETF carries."""

    raw = client._call(COMPONENTS_PATH, COMPONENTS_TR, {"iem_cd": etf_code}, live_only=True)  # noqa: SLF001
    members = []
    for row in raw.get("Output_0") or []:
        code = str(row.get("iem_cd") or "").strip()
        if not is_tradeable_code(code):        # the 현금(원) row has no code
            continue
        members.append({"code": code, "name": str(row.get("iem_nm") or "").strip().lstrip("*")})
    return members


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv()
    from tradingagents.execution.nh_client import NHClient, NHConfig

    # Quotes only exist on the live host, whichever account is configured.
    client = NHClient(config=NHConfig.from_env(paper=False))
    today = date.today().isoformat()

    indices: dict[str, dict] = {}
    for index, (etf_code, etf_name) in INDEX_ETFS.items():
        members = fetch(client, etf_code)
        floor = MIN_PLAUSIBLE.get(index, 1)
        if len(members) < floor:
            print(f"{index}: only {len(members)} members (floor {floor}) — nothing written")
            return 1
        indices[index] = {
            "as_of": today,
            "source": f"{etf_name} ({etf_code}) holdings via NH etfComponents",
            "members": sorted(members, key=lambda row: row["code"]),
        }
        print(f"{index}: {len(members)} members from {etf_name}")
        time.sleep(1)                          # the gateway allows five a second

    MEMBERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    MEMBERS_PATH.write_text(
        json.dumps({"generated_on": today, "indices": indices}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("wrote", MEMBERS_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
