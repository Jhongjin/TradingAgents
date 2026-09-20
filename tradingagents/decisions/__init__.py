"""Typed decisions, recorded and never acted on.

Nothing in this package places an order. It exists to find out whether a
decision model that answers with a probability distribution says anything
useful about an instrument, by writing down what it would have said and
grading that later against what happened.
"""

from .shadow import (
    DIRECTION_OPTIONS,
    INSTRUMENTS,
    ShadowRecord,
    decide,
    make_record,
    read_log,
    record,
)
from .typed import Choice, TypedDecisionClient, TypedDecisionError

__all__ = [
    "Choice",
    "DIRECTION_OPTIONS",
    "INSTRUMENTS",
    "ShadowRecord",
    "TypedDecisionClient",
    "TypedDecisionError",
    "decide",
    "make_record",
    "read_log",
    "record",
]
