"""Run a goldlab command with this machine's .env loaded.

The scheduled task calls this rather than ``python -m goldlab`` because the
lab's CLI reads DATABASE_URL from the environment and the task starts with
none of the repository's settings.
"""

import os
import runpy
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.chdir(REPO)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(REPO, ".env"))
sys.argv = ["goldlab", *sys.argv[1:]]
runpy.run_module("goldlab", run_name="__main__")
