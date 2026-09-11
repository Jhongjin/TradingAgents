"""What a gold futures contract actually costs and pays.

A percentage return says little about a futures position. One COMEX gold
contract controls 100 troy ounces, so a one dollar move in the price is one
hundred dollars in the account, and the margin posted is a fraction of the
notional. Every number this lab reports in money runs through here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    name: str
    multiplier: float          # account currency per 1.0 of price
    tick_size: float           # smallest price increment
    currency: str = "USD"
    typical_slippage_ticks: float = 1.0
    commission_per_side: float = 2.5   # round turn is twice this
    initial_margin: float | None = None

    @property
    def tick_value(self) -> float:
        return self.tick_size * self.multiplier

    def round_to_tick(self, price: float) -> float:
        steps = round(float(price) / self.tick_size)
        return round(steps * self.tick_size, 10)

    def pnl(self, entry: float, exit_price: float, *, contracts: int = 1, long: bool = True) -> float:
        """Money made or lost, after slippage on both sides and commission."""

        direction = 1.0 if long else -1.0
        slippage = self.typical_slippage_ticks * self.tick_size
        filled_entry = entry + direction * slippage
        filled_exit = exit_price - direction * slippage
        gross = (filled_exit - filled_entry) * direction * self.multiplier * contracts
        return gross - (self.commission_per_side * 2 * contracts)

    def contracts_for_risk(self, *, risk_amount: float, entry: float, stop: float) -> int:
        """How many contracts put ``risk_amount`` at stake between entry and stop."""

        distance = abs(float(entry) - float(stop))
        if distance <= 0:
            return 0
        per_contract = distance * self.multiplier
        if per_contract <= 0:
            return 0
        return max(int(risk_amount // per_contract), 0)


# COMEX gold. The micro contract is one tenth the size and trades the same chart.
GOLD_FUTURES = ContractSpec(
    symbol="GC=F",
    name="COMEX Gold (100 oz)",
    multiplier=100.0,
    tick_size=0.10,
    typical_slippage_ticks=1.0,
    commission_per_side=2.5,
    initial_margin=12_000.0,
)

MICRO_GOLD_FUTURES = ContractSpec(
    symbol="MGC=F",
    name="COMEX Micro Gold (10 oz)",
    multiplier=10.0,
    tick_size=0.10,
    typical_slippage_ticks=1.0,
    commission_per_side=1.0,
    initial_margin=1_200.0,
)

CONTRACTS = {spec.symbol: spec for spec in (GOLD_FUTURES, MICRO_GOLD_FUTURES)}
