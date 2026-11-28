"""Open the private gold chart (/lab/gold) on this machine.

Loads the repository's .env (DATABASE_URL: the same bars, signals, similar
charts and AI notes the live site shows), points the lab at the local bar store,
starts the site on 127.0.0.1 only and opens the browser. Close the window to stop.

    automation\\gold-local.cmd            (double-click)
    python automation/gold_local.py [--port 8765] [--no-browser]
"""

import argparse
import os
import sys
import threading
import webbrowser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO, ".env"))
if not os.environ.get("GOLDLAB_CACHE_DIR"):
    os.environ["GOLDLAB_CACHE_DIR"] = r"D:\Codex\goldlab-store"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    ns = parser.parse_args()
    url = f"http://127.0.0.1:{ns.port}/lab/gold"
    print(f"금 차트: {url}")
    print(f"나스닥:  {url}?symbol=NQ=F")
    print("끄려면 이 창을 닫거나 Ctrl+C")
    if not ns.no_browser:
        threading.Timer(2.5, lambda: webbrowser.open(url)).start()
    import uvicorn

    uvicorn.run("tradingagents.site.api_app:app", host="127.0.0.1", port=ns.port, log_level="warning")


if __name__ == "__main__":
    main()
