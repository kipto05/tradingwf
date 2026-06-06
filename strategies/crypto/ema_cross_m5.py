"""
Crypto EMA Cross M5 — BTCUSD & ETHUSD
Fast EMA 8 × Slow EMA 21 on M5 with H1 trend filter.
Designed for capturing momentum moves on major crypto pairs.
"""

from __future__ import annotations

import pandas as pd

from strategies.shared.indicators import ema, atr
from strategies.base import BaseStrategy, Signal, StrategyMeta, Side
from strategies.registry import register


@register
class CryptoEMACrossM5(BaseStrategy):
    meta = StrategyMeta(
        name="Crypto EMA Cross M5",
        asset_class="crypto",
        symbol="BTCUSD.m",
        timeframes=["M5", "H1"],
        params={
            "fast": 8,
            "slow": 21,
            "atr_period": 14,
            "sl_atr_mult": 2.0,
            "tp_atr_mult": 3.0,
            "symbols": ["BTCUSD.m", "ETHUSD.m"],
            "min_confidence": 0.35,
            "enabled": True,
        },
    )

    def generate_signal(self, data: dict[str, pd.DataFrame]) -> Signal | None:
        p = self.meta.params
        m5 = data.get("M5")
        h1 = data.get("H1")

        if m5 is None or h1 is None or len(m5) < 60 or len(h1) < 30:
            return None

        close = m5["close"]
        fast = ema(close, p["fast"])
        slow = ema(close, p["slow"])
        atr_val = atr(m5["high"], m5["low"], m5["close"], p["atr_period"]).iloc[-1]

        if len(fast) < 3 or len(slow) < 3:
            return None

        f_p, f_c = fast.iloc[-2], fast.iloc[-1]
        s_p, s_c = slow.iloc[-2], slow.iloc[-1]

        # H1 trend filter: H1 EMA20 rising = bullish bias
        h1_ema = ema(h1["close"], 20)
        trend_bull = h1_ema.iloc[-1] > h1_ema.iloc[-3]

        # Bullish cross (requires bullish H1 trend)
        if f_p <= s_p and f_c > s_c and trend_bull:
            entry = f_c
            sl = entry - atr_val * p["sl_atr_mult"]
            tp = entry + atr_val * p["tp_atr_mult"]
            return Signal(
                side=Side.BUY,
                entry=round(entry, 2),
                sl=round(sl, 2),
                tp=round(tp, 2),
                confidence=p["min_confidence"],
                reason=f"EMA {p['fast']}/{p['slow']} bullish cross on M5",
                tag="BTCUSD.m",
            )

        # Bearish cross (requires bearish H1 trend)
        if f_p >= s_p and f_c < s_c and not trend_bull:
            entry = f_c
            sl = entry + atr_val * p["sl_atr_mult"]
            tp = entry - atr_val * p["tp_atr_mult"]
            return Signal(
                side=Side.SELL,
                entry=round(entry, 2),
                sl=round(sl, 2),
                tp=round(tp, 2),
                confidence=p["min_confidence"],
                reason=f"EMA {p['fast']}/{p['slow']} bearish cross on M5",
                tag="BTCUSD.m",
            )

        return None
