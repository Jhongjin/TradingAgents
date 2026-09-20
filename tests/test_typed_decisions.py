"""A distribution that is validated, not trusted.

The confirmer we already run reads a confidence the model wrote about itself,
and over 61 decisions it never left 0.72–0.91. The value of a typed answer is
the spread across declared options — so an answer whose spread contradicts its
own stated choice is worse than no answer, and must not reach the record.
"""

import pytest

from tradingagents.decisions.typed import (
    Choice,
    TypedDecisionClient,
    TypedDecisionError,
    direction_question,
)


def _answer(probabilities, choice, confidence=0.8):
    return {"answers": {"direction": {
        "type": "choice", "choice": choice,
        "probabilities": probabilities, "confidence": confidence,
    }}}


def _client(payload, *, seen=None):
    def transport(url, headers, body):
        if seen is not None:
            seen.append((url, dict(headers), dict(body)))
        return payload
    return TypedDecisionClient(api_key="K", transport=transport)


QUESTIONS = {"direction": direction_question(
    (("buy", "-"), ("wait", "-"), ("avoid", "-")), "…")}


def test_a_well_formed_answer_carries_its_spread():
    client = _client(_answer({"buy": 0.7, "wait": 0.2, "avoid": 0.1}, "buy", 0.66))
    answer = client.ask("state", QUESTIONS)["direction"]

    assert answer.choice == "buy"
    assert answer.confidence == 0.66
    assert answer.spread == pytest.approx(0.6)          # 0.7 - 0.1


def test_a_choice_that_is_not_the_most_likely_option_is_refused():
    """However confident it claims to be, the distribution contradicts it."""

    client = _client(_answer({"buy": 0.2, "wait": 0.7, "avoid": 0.1}, "buy", 0.99))
    with pytest.raises(TypedDecisionError, match="more likely"):
        client.ask("state", QUESTIONS)


def test_probabilities_that_do_not_sum_to_one_are_refused():
    client = _client(_answer({"buy": 0.5, "wait": 0.2, "avoid": 0.1}, "buy"))
    with pytest.raises(TypedDecisionError, match="sum to"):
        client.ask("state", QUESTIONS)


def test_a_probability_outside_zero_to_one_is_refused():
    client = _client(_answer({"buy": 1.4, "wait": -0.4, "avoid": 0.0}, "buy"))
    with pytest.raises(TypedDecisionError, match="probability"):
        client.ask("state", QUESTIONS)


def test_a_choice_outside_the_declared_options_is_refused():
    client = _client(_answer({"buy": 0.7, "wait": 0.2, "avoid": 0.1}, "short"))
    with pytest.raises(TypedDecisionError, match="not an option"):
        client.ask("state", QUESTIONS)


def test_a_missing_distribution_is_refused_rather_than_defaulted():
    client = _client({"answers": {"direction": {"type": "choice", "choice": "buy",
                                               "confidence": 0.9}}})
    with pytest.raises(TypedDecisionError, match="no probabilities"):
        client.ask("state", QUESTIONS)


def test_a_confidence_outside_zero_to_one_is_refused():
    client = _client(_answer({"buy": 0.7, "wait": 0.2, "avoid": 0.1}, "buy", 1.8))
    with pytest.raises(TypedDecisionError, match="confidence"):
        client.ask("state", QUESTIONS)


def test_the_request_is_the_shape_the_api_documents():
    seen = []
    client = _client(_answer({"buy": 0.7, "wait": 0.2, "avoid": 0.1}, "buy"), seen=seen)
    client.ask({"latest_close": 1}, QUESTIONS)

    url, headers, body = seen[0]
    assert headers["Authorization"] == "Bearer K"
    assert set(body) == {"state", "model", "questions"}
    assert body["questions"]["direction"]["type"] == "choice"
    assert set(body["questions"]["direction"]["criteria"]) == {"buy", "wait", "avoid"}


def test_without_a_key_it_says_so_rather_than_calling():
    with pytest.raises(TypedDecisionError, match="TYPESAFE_API_KEY"):
        TypedDecisionClient().ask("state", QUESTIONS)


def test_an_answer_of_another_primitive_is_ignored_not_misread():
    payload = {"answers": {
        "urgent": {"type": "noul", "noul": 0.9},
        "direction": {"type": "choice", "choice": "wait",
                      "probabilities": {"buy": 0.2, "wait": 0.6, "avoid": 0.2},
                      "confidence": 0.5},
    }}
    answers = _client(payload).ask("state", QUESTIONS)
    assert set(answers) == {"direction"}
