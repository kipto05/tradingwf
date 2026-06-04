"""
MA Cross Ribbon — Gold/Silver (XAUUSD.m / XAGUSD.m)
Fast EMA 20 × Slow EMA 50 + H4 trend filter + ATR position sizing.
M30, H1, H4 — trend-following across timeframes.
"""

from __future__ import annotations

import pandas as pd

from strategies.shared.indicators import ema, atr
from strategies.base import BaseStrategy, Signal, StrategyMeta, Side
from strategies.registry import register


@register
class MACrossRibbon(BaseStrategy):
    meta = StrategyMeta(
        name="MA Cross Ribbon (Gold/Silver)",
        asset_class="gold",
        symbol="XAUUSD.m",
        timeframes=["M30", "H1", "H4"],
        params={
            "fast": 20,
            "slow": 50,
            "atr_period": 14,
            "sl_atr_mult": 1.2,
            "tp_atr_mult": 2.5,
            "trend_filter_tf": "H4",
            "min_confidence": 0.4,
            "enabled": True,
        },
    )

    def generate_signal(self, data: dict[str, pd.DataFrame]) -> Signal | None:
        # Pick the highest available TF as primary
        tf_priority = ["H4", "H1", "M30"]
        tf = next((t for t in tf_priority if t in data), list(data.keys())[-1])
        df = data.get(tf)
        if df is None or len(df) < 80:
            return None

        p = self.meta.params
        close = df["close"]
        fast = ema(close, p["fast"])
        slow = ema(close, p["slow"])

        if len(fast) < 3 or len(slow) < 3:
            return None

        f_prev, f_curr = fast.iloc[-2], fast.iloc[-1]
        s_prev, s_curr = slow.iloc[-2], slow.iloc[-1]
        atr_val = atr(df["high"], df["low"], df["close"], p["atr_period"]).iloc[-1]

        # Trend filter from higher TF
        h4_trend = True
        if p["trend_filter_tf"] in data:
            h4 = data[p["trend_filter_tf"]]
            h4_ema = ema(h4["close"], p["slow"])
            if len(h4_ema) > 2:
                h4_trend = h4_ema.iloc[-1] > h4_ema.iloc[-5]

        symbol = self.meta.symbol

        # Golden cross
        if f_prev <= s_prev and f_curr > s_curr and h4_trend:
            entry = f_curr
            sl = entry - atr_val * p["sl_atr_mult"]
            tp = entry + atr_val * p["tp_atr_mult"]
            return Signal(
                side=Side.BUY, entry=round(entry, 2), sl=round(sl, 2), tp=round(tp, 2),
                confidence=0.7,
                reason=f"EMA {p['fast']} × {p['slow']} golden cross — {tf}",
                tag=symbol,
            )

        # Death cross
        if f_prev >= s_prev and f_curr < s_curr and not h4_trend:
            entry = f_curr
            sl = entry + atr_val * p["sl_atr_mult"]
            tp = entry - atr_val * p["tp_atr_mult"]
            return Signal(
                side=Side.SELL, entry=round(entry, 2), sl=round(sl, 2), tp=round(tp, 2),
                confidence=0.7,
                reason=f"EMA {p['fast']} × {p['slow']} death cross — {tf}",
                tag=symbol,
            )

        return None
