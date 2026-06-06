"""Abstract base strategy used by all concrete strategies."""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import pandas as pd


class Side(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class Signal:
    side: Side
    entry: float
    sl: float
    tp: float
    confidence: float = 0.0
    reason: str = ""
    tag: str = ""


@dataclass
class StrategyMeta:
    name: str
    asset_class: str
    symbol: str
    timeframes: list[str]
    default_risk: float = 0.02
    enabled: bool = True
    symbols: list[str] | None = None  # multi-asset list; None or [symbol] = single
    params: dict = field(default_factory=dict)


class BaseStrategy(ABC):
    meta: StrategyMeta

    @abstractmethod
    def generate_signal(self, data: dict[str, pd.DataFrame]) -> Optional[Signal]:
        ...

    def on_trade_closed(self, trade) -> None:
        pass

    def validate(self, signal: Signal) -> bool:
        if signal and signal.side == Side.HOLD:
            return False
        if signal and signal.confidence < (self.meta.params.get("min_confidence", 0.3)):
            return False
        if signal and signal.entry <= 0:
            return False
        if signal and getattr(signal, "sl", 0) and getattr(signal, "tp", 0):
            rr = abs(signal.tp - signal.entry) / abs(signal.entry - signal.sl)
            if rr < self.meta.params.get("min_risk_reward", 1.0):
                return False
        return True
