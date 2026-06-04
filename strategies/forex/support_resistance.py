"""
Support / Resistance Breakout — Majors (.m)
Pivot-based S/R detection on H1/H4.
Long above resistance + EMV trend; short below support.
"""

from __future__ import annotations

import pandas as pd

from strategies.shared.indicators import ema, atr, detect_support_resistance
from strategies.base import BaseStrategy, Signal, StrategyMeta, Side
from strategies.registry import register


@register
class ForexSRBreakout(BaseStrategy):
    meta = StrategyMeta(
        name="Forex S/R Breakout",
        asset_class="forex",
        symbol="EURUSD.m",
        timeframes=["H1", "H4"],
        params={
            "sr_window": 30,
            "min_touches": 2,
            "atr_period": 14,
            "sl_atr_mult": 1.0,
            "tp_rr": 1.8,
            "min_rr": 1.5,
            "ema_period": 50,
            "min_confidence": 0.45,
            "enabled": True,
        },
    )

    def generate_signal(self, data: dict[str, pd.DataFrame]) -> Signal | None:
        p = self.meta.params
        tf = "H4" if "H4" in data else "H1"
        df = data.get(tf)
        if df is None or len(df) < p["sr_window"] + 10:
            return None

        supports, resistances = detect_support_resistance(
            df["high"], df["low"], p["sr_window"], p["min_touches"]
        )
        if not supports and not resistances:
            return None

        ema50 = ema(df["close"], p["ema_period"])
        trend_bull = ema50.iloc[-1] > ema50.iloc[-3] if len(ema50) > 3 else True
        atr_val = atr(df["high"], df["low"], df["close"], p["atr_period"]).iloc[-1]

        close = df["close"].iloc[-1]
        high = df["high"].iloc[-1]
        low = df["low"].iloc[-1]
        sym = self.meta.symbol

        # Resistance breakout (long)
        for res in resistances:
            if high >= res and close > res and trend_bull:
                sl = res - atr_val * p["sl_atr_mult"]
                tp = close + (close - res) * p["tp_rr"]
                rr = abs(tp - close) / max(abs(close - sl), 0.0001)
                if rr < p["min_rr"]:
                    tp = close + abs(close - sl) * p["min_rr"]
                return Signal(
                    side=Side.BUY, entry=round(close, 5), sl=round(sl, 5), tp=round(tp, 5),
                    confidence=0.55,
                    reason=f"S/R breakout above resistance {res:.5f}",
                    tag=sym,
                )

        # Support breakdown (short)
        for sup in supports:
            if low <= sup and close < sup and not trend_bull:
                sl = sup + atr_val * p["sl_atr_mult"]
                tp = close - (sup - close) * p["tp_rr"]
                rr = abs(close - tp) / max(abs(sl - close), 0.0001)
                if rr < p["min_rr"]:
                    tp = close - abs(sl - close) * p["min_rr"]
                return Signal(
                    side=Side.SELL, entry=round(close, 5), sl=round(sl, 5), tp=round(tp, 5),
                    confidence=0.55,
                    reason=f"S/R breakdown below support {sup:.5f}",
                    tag=sym,
                )

        return None
