"""Gold futures pattern lab: a private workbench, separate from the site.

Nothing here is wired into the public product. It exists to answer one question
honestly: when a chart pattern appears on gold futures, what actually happened
next, and was it different from what happens on any other bar?

The order of work matters. A pattern is defined as a rule, counted across years
of bars, measured against the base rate of the same instrument, and only then
considered for a trading rule. A pattern that beats nothing is reported as
beating nothing.
"""

from .contracts import GOLD_FUTURES, ContractSpec
from .data import BarSeries, load_bars
from .patterns import PATTERN_REGISTRY, PatternHit, detect_patterns
from .study import PatternStat, StudyResult, run_pattern_study

__all__ = [
    "BarSeries",
    "ContractSpec",
    "GOLD_FUTURES",
    "PATTERN_REGISTRY",
    "PatternHit",
    "PatternStat",
    "StudyResult",
    "detect_patterns",
    "load_bars",
    "run_pattern_study",
]
