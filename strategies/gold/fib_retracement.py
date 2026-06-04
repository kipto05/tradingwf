"""
Gold Fib Retracement — XAUUSD
Picks significant swing H/L on H4, enters pullbacks to Fib levels on H1.
RSI filter + ATR-based SL.
"""

from __future__ import annotations

import pandas as pd

from strategies.shared.indicators import rsi, atr
from strategies.base import BaseStrategy, Signal, StrategyMeta, Side
from strategies.registry import register


FIB_LEVELS = [0.382, 0.5, 0.618]


def _find_swing_range(df: pd.DataFrame, lookback: int = 30) -> tuple[float, float]:
    w = df.iloc[-lookback:]
    return w["low"].min(), w["high"].max()


@register
class GoldFibRetracement(BaseStrategy):
    meta = StrategyMeta(
        name="Fib Retracement (Gold)",
        asset_class="gold",
        symbol="XAUUSD.m",
        timeframes=["H1", "H4"],
        params={
            "swing_lookback_h4": 30,
            "atr_period": 14,
            "rsi_period": 14,
            "rsi_oversold": 40,
            "rsi_overbought": 60,
            "fib_levels_buy": [0.382, 0.618],
            "fib_levels_sell": [0.382, 0.618],
            "sl_atr_mult": 1.5,
            "tp_atr_mult": 2.0,
            "min_rr": 1.6,
            "min_confidence": 0.45,
            "enabled": True,
        },
    )

    def generate_signal(self, data: dict[str, pd.DataFrame]) -> Signal | None:
        h1 = data.get("H1")
        h4 = data.get("H4")
        if h1 is None or h4 is None or len(h4) < 40:
            return None

        p = self.meta.params
        last_h1 = h1.iloc[-1]
        price = last_h1["close"]

        swing_low, swing_high = _find_swing_range(h4, p["swing_lookback_h4"])
        if swing_high <= swing_low:
            return None
        range_ = swing_high - swing_low

        atr_val = atr(h1["high"], h1["low"], h1["close"], p["atr_period"]).iloc[-1]
        rsi_val = rsi(h1["close"], p["rsi_period"]).iloc[-1]

        # Bullish Fib
        for lvl in p["fib_levels_buy"]:
            fib = swing_high - range_ * lvl
            if abs(price - fib) < atr_val * 0.5 and rsi_val < p["rsi_oversold"]:
                sl = fib - atr_val * p["sl_atr_mult"]
                tp = fib + range_ * lvl * p["tp_atr_mult"]
                if abs(tp - fib) / max(abs(fib - sl), 0.01) < p["min_rr"]:
                    continue
                conf = min(0.4 + (p["rsi_oversold"] - rsi_val) / 80, 0.85)
                return Signal(
                    side=Side.BUY, entry=round(fib, 2), sl=round(sl, 2), tp=round(tp, 2),
                    confidence=conf, reason=f"Fib {lvl:.1%} pullback buy | RSI {rsi_val:.0f}",
                    tag="XAUUSD.m",
                )

        # Bearish Fib
        for lvl in p["fib_levels_sell"]:
            fib = swing_low + range_ * lvl
            if abs(price - fib) < atr_val * 0.5 and rsi_val > p["rsi_overbought"]:
                sl = fib + atr_val * p["sl_atr_mult"]
                tp = fib - range_ * lvl * p["tp_atr_mult"]
                if abs(fib - tp) / max(abs(sl - fib), 0.01) < p["min_rr"]:
                    continue
                conf = min(0.4 + (rsi_val - p["rsi_overbought"]) / 80, 0.85)
                return Signal(
                    side=Side.SELL, entry=round(fib, 2), sl=round(sl, 2), tp=round(tp, 2),
                    confidence=conf, reason=f"Fib {lvl:.1%} pullback sell | RSI {rsi_val:.0f}",
                    tag="XAUUSD.m",
                )

        return None
