"""
London Breakout — XAUUSD Gold
Uses Asian session range; enters on London breakout with retest.
Latest SMC/ICT revision: breakout must close beyond range + ATR confirmation.
Timeframes: M15 (entry), H1 (filter).
"""

from __future__ import annotations

import pandas as pd

from strategies.shared.indicators import ema, atr, adx
from strategies.base import BaseStrategy, Signal, StrategyMeta, Side
from strategies.registry import register


@register
class LondonBreakoutGold(BaseStrategy):
    meta = StrategyMeta(
        name="London Breakout (Gold)",
        asset_class="gold",
        symbol="XAUUSD.m",
        timeframes=["M15", "H1"],
        params={
            "asian_start_utc": 0,
            "asian_end_utc": 7,
            "london_open_utc": 8,
            "london_close_utc": 16,
            "min_range_points": 3.0,
            "rr_multiplier": 2.0,
            "atr_period": 14,
            "adx_period": 14,
            "min_adx": 20,
            "ema_filter_period": 50,
            "max_retest_bars": 6,
            "min_confidence": 0.4,
            "enabled": True,
        },
    )

    def generate_signal(self, data: dict[str, pd.DataFrame]) -> Signal | None:
        m15 = data.get("M15")
        h1 = data.get("H1")
        if m15 is None or h1 is None or len(m15) < 200:
            return None

        p = self.meta.params
        now_utc = m15["time"].iloc[-1]
        current_hour = now_utc.hour

        # Asian range
        asian = m15[
            (m15["time"].dt.hour >= p["asian_start_utc"])
            & (m15["time"].dt.hour < p["asian_end_utc"])
            & (m15["time"].dt.date == now_utc.date())
        ]
        if len(asian) < 24:
            return None

        asian_high = asian["high"].max()
        asian_low = asian["low"].min()
        asian_range = asian_high - asian_low

        if asian_range < p["min_range_points"]:
            return None

        atr_val = atr(m15["high"], m15["low"], m15["close"], p["atr_period"]).iloc[-1]
        adx_val = adx(m15["high"], m15["low"], m15["close"], p["adx_period"]).iloc[-1]
        ema50 = ema(m15["close"], p["ema_filter_period"]).iloc[-1]
        last = m15.iloc[-1]
        close = last["close"]

        # Only during London session
        if not (p["london_open_utc"] <= current_hour < p["london_close_utc"]):
            return None

        if adx_val < p["min_adx"]:
            return None  # chop

        # Bullish breakout
        if close > asian_high and close > ema50:
            sl = asian_low - atr_val * 0.3
            tp = close + asian_range * p["rr_multiplier"]
            return Signal(
                side=Side.BUY,
                entry=round(close, 2),
                sl=round(sl, 2),
                tp=round(tp, 2),
                confidence=min(0.5 + adx_val / 200, 0.85),
                reason=f"London breakout above Asian high ({asian_high:.2f})",
                tag="XAUUSD.m",
            )

        # Bearish breakout
        if close < asian_low and close < ema50:
            sl = asian_high + atr_val * 0.3
            tp = close - asian_range * p["rr_multiplier"]
            return Signal(
                side=Side.SELL,
                entry=round(close, 2),
                sl=round(sl, 2),
                tp=round(tp, 2),
                confidence=min(0.5 + adx_val / 200, 0.85),
                reason=f"London breakdown below Asian low ({asian_low:.2f})",
                tag="XAUUSD.m",
            )

        return None
