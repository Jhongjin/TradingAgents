"""Execution foundation for paper trading and backtesting.

This package intentionally starts with paper execution only. Live broker
adapters should plug into these models after credentials, account-level risk
limits, and independent validation are in place.
"""

from .audit import AuditLedger, AuditRecord
from .backtest import BacktestEngine, BacktestResult
from .broker import BrokerAccountSnapshot, BrokerAdapter, BrokerOrderResult, PaperBrokerAdapter
from .kis import KISConfig
from .kis_client import KISBrokerAdapter, KISClient, KISError, LiveTradingDisabledError, live_trading_enabled
from .kr_rules import KoreaTradingRules
from .mandate import MandateContext, MandateDecision, MandateGate, TradingMandate
from .models import Fill, OrderIntent, OrderSide, TradeSignal
from .paper_broker import PaperBroker
from .portfolio import Portfolio, Position
from .position_sizing import PositionSizePlan, PositionSizeRequest, size_position, stop_from_atr
from .risk import RiskLimits, RiskManager
from .simulator import PaperSimulationConfig, PaperSimulationResult, simulate_single_position
from .signals import SignalPolicy, signal_from_decision

__all__ = [
    "AuditLedger",
    "AuditRecord",
    "BacktestEngine",
    "BacktestResult",
    "BrokerAccountSnapshot",
    "BrokerAdapter",
    "BrokerOrderResult",
    "Fill",
    "KISBrokerAdapter",
    "KISClient",
    "KISConfig",
    "KISError",
    "KoreaTradingRules",
    "LiveTradingDisabledError",
    "MandateContext",
    "MandateDecision",
    "MandateGate",
    "OrderIntent",
    "OrderSide",
    "PaperBroker",
    "PaperBrokerAdapter",
    "PaperSimulationConfig",
    "PaperSimulationResult",
    "Portfolio",
    "Position",
    "PositionSizePlan",
    "PositionSizeRequest",
    "RiskLimits",
    "RiskManager",
    "SignalPolicy",
    "TradeSignal",
    "TradingMandate",
    "live_trading_enabled",
    "signal_from_decision",
    "simulate_single_position",
    "size_position",
    "stop_from_atr",
]
