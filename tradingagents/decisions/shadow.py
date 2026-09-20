"""A daily opinion that is written down and never acted on.

The point of this package is to find out whether a typed decision model says
anything useful about an instrument, and the only honest way to find that out
is to let it be wrong for a few weeks at no cost. So: one question a day per
instrument, the full distribution stored, the price stored beside it, and the
answer graded later against what actually happened.

Nothing here places an order, and nothing here is wired into the harness.
Wiring it in is a separate decision to be made from the record it produces.

Why these instruments rather than the stock book: the screener's real job is
to rank three hundred and fifty names, and a choice between three options does
not rank anything. It answers "this one, or not" — which is the shape of a
single instrument with its own trend. KRX gold and bitcoin are each one thing
with one daily bar, already priced by code that exists, and neither touches
the published equity record while the question is still open.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .typed import (
    Choice,
    TypedDecisionClient,
    direction_question,
    noul_question,
    score_question,
)

#: Long-only, because the accounts behind this are. "avoid" means stay in cash,
#: never short — naming it "short" would invite reading a record of trades
#: nobody could have made.
DIRECTION_OPTIONS = (
    ("buy", "추세와 수급이 매수에 유리하다"),
    ("wait", "방향이 분명하지 않아 기다리는 편이 낫다"),
    ("avoid", "추세가 꺾였으므로 현금으로 비켜 있어야 한다"),
)

DIRECTION_INSTRUCTIONS = (
    "아래 가격 기록만 보고, 지금 이 자산을 새로 사도 좋은 자리인지 판단하세요. "
    "공매도는 선택지가 아닙니다."
)

#: Asked in the same request as the direction, because the service answers
#: every question against one state in parallel and the docs say adding
#: questions barely moves the response time. Each one is separately gradeable
#: later, which a single verdict is not: if the direction turns out useless but
#: "is the trend intact" is reliable, that is worth knowing separately.
SUPPORTING_QUESTIONS: dict[str, Any] = {
    "regime": direction_question(
        (
            ("advancing", "꾸준히 오르는 구간"),
            ("declining", "꾸준히 내리는 구간"),
            ("ranging", "방향 없이 오르내리는 구간"),
            ("volatile", "폭이 크고 방향이 자주 바뀌는 구간"),
        ),
        "지금 이 자산이 어떤 국면에 있는지 고르세요.",
    ),
    "trend_strength": score_question(
        ["없음", "약함", "보통", "강함"],
        "추세가 얼마나 뚜렷한지 평가하세요.",
    ),
    "pullback_risk": score_question(
        ["낮음", "보통", "높음"],
        "지금 들어갔을 때 곧바로 되돌림을 맞을 위험을 평가하세요.",
    ),
    "above_trend": noul_question(
        "현재가가 최근 60일 흐름의 위쪽에 있습니까?",
        when_true="최근 범위의 위쪽",
        when_false="최근 범위의 아래쪽",
    ),
    "extended": noul_question(
        "최근 상승폭이 지나쳐서 쉬어갈 자리입니까?",
        when_true="단기 과열",
        when_false="과열이 아님",
    ),
}

#: The instruments this runs on, and where their bars come from.
INSTRUMENTS: dict[str, dict[str, str]] = {
    "KRXGOLD": {"label": "KRX 금현물", "symbol": "KRXGOLD", "unit": "원/g"},
    "BTC": {"label": "비트코인", "symbol": "BTC-USD", "unit": "USD"},
    "COMEXGOLD": {"label": "COMEX 금", "symbol": "GC=F", "unit": "USD/oz"},
}

DEFAULT_LOG = Path.home() / ".tradingagents" / "decisions" / "shadow.jsonl"


@dataclass(frozen=True)
class ShadowRecord:
    as_of: str
    instrument: str
    label: str
    price: float
    answers: dict[str, dict[str, Any]]
    model: str
    recorded_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "instrument": self.instrument,
            "label": self.label,
            "price": self.price,
            "answers": self.answers,
            "model": self.model,
            "recorded_at": self.recorded_at,
            # Said out loud in every row, because a file of directional calls
            # with prices beside them is exactly what somebody skims later and
            # mistakes for a track record.
            "traded": False,
            "note": "기록만 했고 주문은 없었습니다",
        }


def log_path() -> Path:
    configured = (os.getenv("TRADINGAGENTS_SHADOW_LOG") or "").strip()
    return Path(configured) if configured else DEFAULT_LOG


def build_state(bars: Iterable[Any], *, label: str, unit: str, window: int = 60) -> dict[str, Any]:
    """The price history the question is asked against.

    Only closes, volumes and the dates. No indicator the model might weigh the
    way we would rather than the way it would, and nothing derived that could
    smuggle in today's answer.
    """

    rows = list(bars)[-window:]
    if len(rows) < 20:
        raise ValueError(f"{label}: {len(rows)} bars is too few to ask about")

    closes = [float(bar.close) for bar in rows]
    return {
        "instrument": label,
        "unit": unit,
        "as_of": rows[-1].timestamp.date().isoformat(),
        "latest_close": closes[-1],
        "change_1d_pct": _pct(closes[-1], closes[-2]) if len(closes) > 1 else None,
        "change_5d_pct": _pct(closes[-1], closes[-6]) if len(closes) > 5 else None,
        "change_20d_pct": _pct(closes[-1], closes[-21]) if len(closes) > 20 else None,
        "high_60d": max(closes),
        "low_60d": min(closes),
        "closes": [round(value, 4) for value in closes],
    }


def decide(
    client: TypedDecisionClient,
    bars: Iterable[Any],
    *,
    instrument: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Ask every question about one instrument, in one request. Places no order."""

    meta = INSTRUMENTS.get(instrument)
    if meta is None:
        raise ValueError(f"unknown instrument {instrument!r}")

    state = build_state(bars, label=meta["label"], unit=meta["unit"])
    questions: dict[str, Any] = {
        "direction": direction_question(DIRECTION_OPTIONS, DIRECTION_INSTRUCTIONS),
    }
    questions.update(SUPPORTING_QUESTIONS)
    return client.ask(state, questions), state


def record(records: Iterable[ShadowRecord], *, path: Path | None = None) -> int:
    """Append to the log. One line per instrument per day, never rewritten."""

    target = Path(path) if path else log_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with target.open("a", encoding="utf-8") as handle:
        for row in records:
            handle.write(json.dumps(row.as_dict(), ensure_ascii=False) + "\n")
            written += 1
    return written


def already_recorded(as_of: str, instrument: str, *, path: Path | None = None) -> bool:
    """Whether today's answer for this instrument is already down.

    Asking twice in a day and keeping both would let a re-run quietly pick the
    answer it preferred.
    """

    target = Path(path) if path else log_path()
    if not target.exists():
        return False
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("as_of") == as_of and row.get("instrument") == instrument:
                return True
    except (OSError, ValueError):
        return False
    return False


def read_log(*, path: Path | None = None) -> list[dict[str, Any]]:
    target = Path(path) if path else log_path()
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def make_record(
    *,
    instrument: str,
    state: Mapping[str, Any],
    answers: Mapping[str, Any],
    model: str,
) -> ShadowRecord:
    meta = INSTRUMENTS[instrument]
    return ShadowRecord(
        as_of=str(state.get("as_of") or date.today().isoformat()),
        instrument=instrument,
        label=meta["label"],
        price=float(state.get("latest_close") or 0.0),
        answers={name: answer.as_dict() for name, answer in answers.items()},
        model=model,
        recorded_at=datetime.now(timezone.utc).isoformat(),
    )


def _pct(now: float, then: float) -> float | None:
    if not then:
        return None
    return round(((now / then) - 1) * 100, 4)
