"""
EMA Cross — Majors + Minors (.m suffix)
Fast EMA 10 × Slow EMA 50 with H4 trend filter.
M30, H1, H4 timeframes.
"""

from __future__ import annotations

import pandas as pd

from strategies.shared.indicators import ema, atr
from strategies.base import BaseStrategy, Signal, StrategyMeta, Side
from strategies.registry import register


_FOREX_PAIRS = [
    "EURUSD.m", "GBPUSD.m", "USDJPY.m", "AUDUSD.m", "USDCAD.m",
    "GBPJPY.m", "EURJPY.m", "CHFJPY.m", "EURAUD.m", "AUDJPY.m",
]


@register
class ForexEMACross(BaseStrategy):
    meta = StrategyMeta(
        name="Forex EMA Cross",
        asset_class="forex",
        symbol="EURUSD.m",
        timeframes=["M30", "H1", "H4"],
        symbols=["EURUSD.m"],
    params={
            "fast": 10,
            "slow": 50,
            "atr_period": 14,
            "sl_atr_mult": 1.0,
            "tp_atr_mult": 2.0,
            "symbols": _FOREX_PAIRS,
            "min_confidence": 0.35,
            "enabled": True,
        },
    )

    def generate_signal(self, data: dict[str, pd.DataFrame]) -> Signal | None:
        p = self.meta.params
        tf = next((t for t in ["H4", "H1", "M30"] if t in data), list(data.keys())[-1])
        df = data.get(tf)
        if df is None or len(df) < 80:
            return None

        close = df["close"]
        fast = ema(close, p["fast"])
        slow = ema(close, p["slow"])
        atr_val = atr(df["high"], df["low"], df["close"], p["atr_period"]).iloc[-1]

        if len(fast) < 3 or len(slow) < 3:
            return None

        f_p, f_c = fast.iloc[-2], fast.iloc[-1]
        s_p, s_c = slow.iloc[-2], slow.iloc[-1]
        h4_filter = data.get("H4")
        trend_bull = True
        if h4_filter is not None and len(h4_filter) > 10:
            h4_ema = ema(h4_filter["close"], 20)
            trend_bull = h4_ema.iloc[-1] > h4_ema.iloc[-5]

        sym = self.meta.symbol

        if f_p <= s_p and f_c > s_c and trend_bull:
            entry = f_c
            sl = entry - atr_val * p["sl_atr_mult"]
            tp = entry + atr_val * p["tp_atr_mult"]
            return Signal(
                side=Side.BUY, entry=round(entry, 5), sl=round(sl, 5), tp=round(tp, 5),
                confidence=0.6,
                reason=f"EMA {p['fast']}/{p['slow']} bullish cross — {tf}",
                tag=sym,
            )

        if f_p >= s_p and f_c < s_c and not trend_bull:
            entry = f_c
            sl = entry + atr_val * p["sl_atr_mult"]
            tp = entry - atr_val * p["tp_atr_mult"]
            return Signal(
                side=Side.SELL, entry=round(entry, 5), sl=round(sl, 5), tp=round(tp, 5),
                confidence=0.6,
                reason=f"EMA {p['fast']}/{p['slow']} bearish cross — {tf}",
                tag=sym,
            )

        return None
