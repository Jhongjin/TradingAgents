"""Pull request/response examples for a set of NAMUH PLUG endpoints.

Kept next to the catalogue it reads so the next round of endpoints does not
start by reconstructing the fetch. Edit WANT and run it from the repo root.
"""

import json
import pathlib
import time

import requests

from tradingagents.dataflows.http_trust import apply_system_truststore_if_available

WANT = {
    "/krstock/inquiry/v1/assetStatus",
    "/krstock/inquiry/v1/integratedMargin",
    "/krstock/inquiry/v1/rightsHeld",
    "/krstock/inquiry/v1/rightsScheduled",
    "/common/inquiry/v1/depositWithdrawal",
    "/common/inquiry/v1/totalTransaction",
    "/n2/acctinfo",
    "/krstock/quote/v1/currentExecution",
    "/krstock/quote/v1/period",
    "/krstock/quote/v1/etfCurrent",
    "/krstock/quote/v1/etfComponents",
    "/krstock/quote/v1/afterHoursCurrent",
    "/krgold/quote/v1/goldCurrent",
    "/krgold/quote/v1/goldDailyTrend",
    "/krgold/inquiry/v1/goldDepositAndBalance",
    "/krgold/order/v1/goldBuy",
}
OUT = pathlib.Path("shorts-out/nh/spec7.txt")   # gitignored build output


def main() -> None:
    apply_system_truststore_if_available()
    catalogue = json.loads(pathlib.Path("shorts-out/nh/catalog.json").read_text(encoding="utf-8"))
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json"})

    lines: list[str] = []
    for entry in catalogue:
        if entry["url"] not in WANT:
            continue
        spec = session.get(f"https://www.nhplug.com/api/apis/public/{entry['id']}", timeout=15).json()
        guide = session.get(f"https://www.nhplug.com/api/apis/guide/tr/{entry['id']}", timeout=15).json()
        tr = (guide or [{}])[0]
        lines.append(f"### {entry['name']}  [{entry['url']}]")
        lines.append(f"tr_cd: {(json.loads(spec.get('extraParam') or '{}') or {}).get('tr_cd')}")
        lines.append("요청: " + str(tr.get("reqExample"))[:420])
        lines.append("응답: " + str(tr.get("resExample"))[:700])
        lines.append("")
        time.sleep(0.15)

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("saved", sum(1 for line in lines if line.startswith("###")), "APIs to", OUT)


if __name__ == "__main__":
    main()
