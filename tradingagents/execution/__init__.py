"""Execution foundation for paper trading and backtesting.

This package intentionally starts with paper execution only. Live broker
adapters should plug into these models after credentials, account-level risk
limits, and independent validation are in place.
"""

from .backtest import BacktestEngine, BacktestResult
from .kis import KISConfig
from .kr_rules import KoreaTradingRules
from .models import Fill, OrderIntent, OrderSide, TradeSignal
from .paper_broker import PaperBroker
from .portfolio import Portfolio, Position
from .risk import RiskLimits, RiskManager
from .simulator import PaperSimulationConfig, PaperSimulationResult, simulate_single_position
from .signals import SignalPolicy, signal_from_decision

__all__ = [
    "BacktestEngine",
    "BacktestResult",
    "Fill",
    "KISConfig",
    "KoreaTradingRules",
    "OrderIntent",
    "OrderSide",
    "PaperBroker",
    "PaperSimulationConfig",
    "PaperSimulationResult",
    "Portfolio",
    "Position",
    "RiskLimits",
    "RiskManager",
    "SignalPolicy",
    "TradeSignal",
    "signal_from_decision",
    "simulate_single_position",
]
