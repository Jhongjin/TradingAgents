"""A decision that arrives as a distribution rather than a sentence.

The confirmer we already run asks an LLM for JSON and reads ``confidence`` out
of it — a number the model writes about itself. Over 61 recorded decisions it
never left 0.72–0.91. Nineteen points of range across every buy and every
rejection, which is not enough to threshold on, size on, or calibrate against,
whatever it correlates with.

TypeSafe's Jev answers a different shape: you declare the options, and it
returns a probability for each of them plus a confidence, with no sentence to
parse. Whether that turns out to be better here is a question for the record,
not for an argument — which is why nothing in this package is allowed to
trade. It records what it would have said, and the existing outcome scoring
grades it.

The same contract is implemented by SemIf and others against open models on a
local GPU. The client is written to the HTTP shape so the engine underneath
can be swapped once there is a reason to prefer one.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from tradingagents.execution.throttle import Throttle

BASE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"

#: Published limits are not documented, so this is deliberately timid: the
#: whole point of a shadow log is that being slow costs nothing.
CALLS_PER_SECOND = 2
_THROTTLE = Throttle(CALLS_PER_SECOND)

#: 429 asks for backoff; 529 is "temporarily overloaded, retry shortly".
RETRY_STATUSES = (429, 529)
MAX_ATTEMPTS = 3

Transport = Callable[[str, Mapping[str, str], Mapping[str, Any]], Mapping[str, Any]]


class TypedDecisionError(RuntimeError):
    """Raised when the decision service cannot answer."""


@dataclass(frozen=True)
class Score:
    """A rating on an ordered rubric, with the spread that produced it."""

    name: str
    score: float
    legend: dict[str, str]
    probabilities: dict[str, float]
    confidence: float

    @property
    def levels(self) -> int:
        return len(self.legend) or len(self.probabilities)

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": "score",
            "name": self.name,
            "score": self.score,
            "levels": self.levels,
            "legend": dict(self.legend),
            "probabilities": dict(self.probabilities),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class Noul:
    """One statement, and how true it is. No confidence: the value is the answer."""

    name: str
    noul: float

    def as_dict(self) -> dict[str, Any]:
        return {"type": "noul", "name": self.name, "noul": self.noul}


@dataclass(frozen=True)
class Choice:
    """One answer: the option picked, the spread over all options, a confidence."""

    name: str
    choice: str
    probabilities: dict[str, float]
    confidence: float

    @property
    def spread(self) -> float:
        """Highest minus lowest probability — how opinionated the answer is."""

        if not self.probabilities:
            return 0.0
        return max(self.probabilities.values()) - min(self.probabilities.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": "choice",
            "name": self.name,
            "choice": self.choice,
            "probabilities": dict(self.probabilities),
            "confidence": self.confidence,
            "spread": round(self.spread, 6),
        }


@dataclass
class TypedDecisionClient:
    """Thin client for the System One HTTP contract."""

    api_key: str = ""
    base_url: str = BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = 20.0
    transport: Transport | None = None
    throttle: Throttle = field(default=_THROTTLE, repr=False)

    @classmethod
    def from_env(cls, **overrides: Any) -> "TypedDecisionClient":
        return cls(
            api_key=(os.getenv("TYPESAFE_API_KEY") or "").strip(),
            base_url=(os.getenv("TYPESAFE_BASE_URL") or BASE_URL).strip().rstrip("/"),
            model=(os.getenv("TYPESAFE_MODEL") or DEFAULT_MODEL).strip(),
            **overrides,
        )

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def ask(self, state: Any, questions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        """Put one state and several questions, get one answer each.

        Every question is answered against the same state in one request, which
        is the shape the service is built for — asking them separately would
        pay for the state repeatedly and answer each one blind to the others.
        """

        if not self.configured:
            raise TypedDecisionError("TYPESAFE_API_KEY is not set")
        if not questions:
            raise ValueError("at least one question is required")

        body = {"state": state, "model": self.model, "questions": dict(questions)}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._post(headers, body)
        answers = payload.get("answers")
        if not isinstance(answers, Mapping):
            raise TypedDecisionError(f"no answers in response: {str(payload)[:200]}")

        out: dict[str, Any] = {}
        for name, answer in answers.items():
            parsed = _parse_answer(str(name), answer)
            if parsed is not None:
                out[str(name)] = parsed
        if not out:
            raise TypedDecisionError("no usable answers in response")
        return out

    def _post(self, headers: Mapping[str, str], body: Mapping[str, Any]) -> Mapping[str, Any]:
        if self.transport is not None:
            return self.transport(self.base_url, headers, body)

        import requests

        from tradingagents.dataflows.http_trust import apply_system_truststore_if_available

        apply_system_truststore_if_available()
        last = ""
        for attempt in range(MAX_ATTEMPTS):
            self.throttle.wait()
            try:
                response = requests.post(self.base_url, headers=dict(headers), json=dict(body),
                                         timeout=self.timeout)
            except Exception as exc:                    # noqa: BLE001 - reported to one caller
                raise TypedDecisionError(f"{type(exc).__name__}: {exc}") from exc

            if response.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS - 1:
                # Documented as "use exponential backoff" and "retry after a
                # short delay" respectively.
                time.sleep(2.0 ** attempt)
                last = f"HTTP {response.status_code}"
                continue
            if response.status_code >= 400:
                raise TypedDecisionError(f"HTTP {response.status_code}: {response.text[:300]}")
            try:
                return response.json()
            except ValueError as exc:
                raise TypedDecisionError(f"non-JSON response: {response.text[:200]}") from exc
        raise TypedDecisionError(last or "no response")


def _parse_answer(name: str, answer: Any) -> Any:
    """One answer of whichever primitive it declares itself to be."""

    if not isinstance(answer, Mapping):
        return None
    kind = str(answer.get("type") or "")
    if kind == "choice":
        return _parse_choice(name, answer)
    if kind == "score":
        return _parse_score(name, answer)
    if kind == "noul":
        return _parse_noul(name, answer)
    return None


def _distribution(name: str, raw: Any) -> dict[str, float]:
    """Probabilities that cover their options, sit in [0,1] and sum to one."""

    if not isinstance(raw, Mapping) or not raw:
        raise TypedDecisionError(f"{name}: answer carried no probabilities")
    out: dict[str, float] = {}
    for option, value in raw.items():
        try:
            probability = float(value)
        except (TypeError, ValueError) as exc:
            raise TypedDecisionError(f"{name}: probability for {option!r} is not a number") from exc
        if not 0.0 <= probability <= 1.0:
            raise TypedDecisionError(f"{name}: probability for {option!r} is {probability}")
        out[str(option)] = probability
    total = sum(out.values())
    if abs(total - 1.0) > 0.01:
        raise TypedDecisionError(f"{name}: probabilities sum to {total:.4f}")
    return out


def _confidence(name: str, value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise TypedDecisionError(f"{name}: confidence is not a number") from exc
    if not 0.0 <= confidence <= 1.0:
        raise TypedDecisionError(f"{name}: confidence is {confidence}")
    return confidence


def _parse_score(name: str, answer: Mapping[str, Any]) -> Score:
    """A score has to sit inside the rubric it was asked about."""

    probabilities = _distribution(name, answer.get("probabilities"))
    legend = {str(key): str(value) for key, value in (answer.get("legend") or {}).items()}
    try:
        score = float(answer.get("score"))
    except (TypeError, ValueError) as exc:
        raise TypedDecisionError(f"{name}: score is not a number") from exc
    levels = len(legend) or len(probabilities)
    if levels and not -0.001 <= score <= levels - 1 + 0.001:
        raise TypedDecisionError(f"{name}: score {score} is outside a {levels}-level rubric")
    return Score(name=name, score=score, legend=legend, probabilities=probabilities,
                 confidence=_confidence(name, answer.get("confidence")))


def _parse_noul(name: str, answer: Mapping[str, Any]) -> Noul:
    try:
        value = float(answer.get("noul"))
    except (TypeError, ValueError) as exc:
        raise TypedDecisionError(f"{name}: noul is not a number") from exc
    if not 0.0 <= value <= 1.0:
        raise TypedDecisionError(f"{name}: noul is {value}")
    return Noul(name=name, noul=value)


def _parse_choice(name: str, answer: Any) -> Choice | None:
    """A choice answer, or None for the other primitives.

    Validated rather than trusted. A stated choice that is not the most likely
    option is a broken answer however confident it claims to be, and letting it
    through would put a number in the record that the distribution contradicts.
    """

    if not isinstance(answer, Mapping) or str(answer.get("type")) != "choice":
        return None

    probabilities = _distribution(name, answer.get("probabilities"))

    choice = str(answer.get("choice") or "")
    if choice not in probabilities:
        raise TypedDecisionError(f"{name}: chose {choice!r}, which is not an option")
    if probabilities[choice] < max(probabilities.values()) - 1e-9:
        raise TypedDecisionError(
            f"{name}: chose {choice!r} at {probabilities[choice]:.3f} "
            f"while {max(probabilities, key=probabilities.get)!r} is more likely"
        )

    return Choice(name=name, choice=choice, probabilities=probabilities,
                  confidence=_confidence(name, answer.get("confidence")))


def direction_question(options: Sequence[tuple[str, str]], instructions: str) -> dict[str, Any]:
    """A Choice question in the shape the API documents."""

    return {
        "type": "choice",
        "instructions": instructions,
        "criteria": {key: description for key, description in options},
    }


def score_question(levels: Sequence[str], instructions: str) -> dict[str, Any]:
    """A Score question: an ordered rubric, lowest first."""

    return {"type": "score", "instructions": instructions, "criteria": list(levels)}


def noul_question(instructions: str, *, when_true: str, when_false: str) -> dict[str, Any]:
    """A Noul question: one statement, answered as how true it is."""

    return {
        "type": "noul",
        "instructions": instructions,
        "criteria": {"true": when_true, "false": when_false},
    }
