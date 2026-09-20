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

    def ask(self, state: Any, questions: Mapping[str, Mapping[str, Any]]) -> dict[str, Choice]:
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

        out: dict[str, Choice] = {}
        for name, answer in answers.items():
            parsed = _parse_choice(str(name), answer)
            if parsed is not None:
                out[str(name)] = parsed
        if not out:
            raise TypedDecisionError("no choice answers in response")
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


def _parse_choice(name: str, answer: Any) -> Choice | None:
    """A choice answer, or None for the other primitives.

    Validated rather than trusted. A stated choice that is not the most likely
    option is a broken answer however confident it claims to be, and letting it
    through would put a number in the record that the distribution contradicts.
    """

    if not isinstance(answer, Mapping) or str(answer.get("type")) != "choice":
        return None

    raw = answer.get("probabilities")
    if not isinstance(raw, Mapping) or not raw:
        raise TypedDecisionError(f"{name}: choice answer carried no probabilities")

    probabilities: dict[str, float] = {}
    for option, value in raw.items():
        try:
            probability = float(value)
        except (TypeError, ValueError) as exc:
            raise TypedDecisionError(f"{name}: probability for {option!r} is not a number") from exc
        if not 0.0 <= probability <= 1.0:
            raise TypedDecisionError(f"{name}: probability for {option!r} is {probability}")
        probabilities[str(option)] = probability

    total = sum(probabilities.values())
    if abs(total - 1.0) > 0.01:
        raise TypedDecisionError(f"{name}: probabilities sum to {total:.4f}")

    choice = str(answer.get("choice") or "")
    if choice not in probabilities:
        raise TypedDecisionError(f"{name}: chose {choice!r}, which is not an option")
    if probabilities[choice] < max(probabilities.values()) - 1e-9:
        raise TypedDecisionError(
            f"{name}: chose {choice!r} at {probabilities[choice]:.3f} "
            f"while {max(probabilities, key=probabilities.get)!r} is more likely"
        )

    try:
        confidence = float(answer.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise TypedDecisionError(f"{name}: confidence is not a number") from exc
    if not 0.0 <= confidence <= 1.0:
        raise TypedDecisionError(f"{name}: confidence is {confidence}")

    return Choice(name=name, choice=choice, probabilities=probabilities, confidence=confidence)


def direction_question(options: Sequence[tuple[str, str]], instructions: str) -> dict[str, Any]:
    """A Choice question in the shape the API documents."""

    return {
        "type": "choice",
        "instructions": instructions,
        "criteria": {key: description for key, description in options},
    }
