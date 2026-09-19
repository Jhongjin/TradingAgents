"""A shared ceiling on how fast a broker gateway may be asked.

Both brokers answer an over-eager caller with an error rather than data: NH
with IGW42903 and KIS with "초당 거래건수를 초과하였습니다". Each documents its
own limit, and each was being exceeded by ordinary use — the desk opening six
panels at once, an exits pass walking a book of eighteen positions.

Process-wide by default rather than per client, because one key talks to one
gateway however many objects hold it.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class Throttle:
    """At most ``limit`` calls in any trailing second, across every client.

    Process-wide and deliberately so. The desk, the CLI and the harness all
    speak to one gateway with one key, and a limiter per client object would
    let two of them together do what neither does alone.
    """

    def __init__(self, limit: int, per_seconds: float = 1.0) -> None:
        self.limit = max(1, int(limit))
        self.window = float(per_seconds)
        self._recent: deque[float] = deque()
        self._lock = threading.Lock()

    def wait(self) -> float:
        """Block until there is room. Returns how long that took."""

        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                while self._recent and now - self._recent[0] >= self.window:
                    self._recent.popleft()
                if len(self._recent) < self.limit:
                    self._recent.append(now)
                    return waited
                sleep_for = self.window - (now - self._recent[0])
            sleep_for = max(sleep_for, 0.005)
            time.sleep(sleep_for)
            waited += sleep_for


