"""
Crypto Trend Following — BTCUSD.m, ETHUSD.m, SOLUSD.m
Dual SMA (20/50) crossover on H1/H4 with RSI + MACD confluence filter.
D1 trend filter to cut counter-trend entries.
"""

from __future__ import annotations

import pandas as pd

from strategies.shared.indicators import ema, rsi, atr, macd
from strategies.base import BaseStrategy, Signal, StrategyMeta, Side
from strategies.registry import register


_CRYPTO_SYMBOLS = ["BTCUSD.m", "ETHUSD.m", "SOLUSD.m"]


@register
class CryptoTrendFollowing(BaseStrategy):
    meta = StrategyMeta(
        name="Crypto Trend Following",
        asset_class="crypto",
        symbol="BTCUSD.m",
        timeframes=["H1", "H4", "D1"],
        params={
            "sma_fast": 20,
            "sma_slow": 50,
            "rsi_period": 14,
            "rsi_guard_low": 30,
            "rsi_guard_high": 70,
            "atr_period": 14,
            "sl_atr_mult": 1.5,
            "tp_rr": 2.0,
            "trend_filter_tf": "D1",
            "symbols": _CRYPTO_SYMBOLS,
            "min_confidence": 0.4,
            "enabled": True,
        },
    )

    def generate_signal(self, data: dict[str, pd.DataFrame]) -> Signal | None:
        p = self.meta.params
        tf = next((t for t in ["H4", "H1", "D1"] if t in data), list(data.keys())[-1])
        df = data.get(tf)
        if df is None or len(df) < 80:
            return None

        close = df["close"]
        sma_f = close.rolling(p["sma_fast"]).mean()
        sma_s = close.rolling(p["sma_slow"]).mean()
        rsi_v = rsi(close, p["rsi_period"]).iloc[-1]
        _, _, hist = macd(close)
        atr_val = atr(df["high"], df["low"], df["close"], p["atr_period"]).iloc[-1]
        sym = self.meta.symbol

        if len(sma_f) < 3 or len(sma_s) < 3:
            return None

        f_p, f_c = sma_f.iloc[-2], sma_f.iloc[-1]
        s_p, s_c = sma_s.iloc[-2], sma_s.iloc[-1]
        hist_val = hist.iloc[-1]

        # D1 trend alignment
        d1 = data.get("D1")
        d1_bull = True
        if d1 is not None and len(d1) > 10:
            d1_ema = ema(d1["close"], 50)
            d1_bull = d1_ema.iloc[-1] > d1_ema.iloc[-5]

        if f_p <= s_p and f_c > s_c and d1_bull:
            if rsi_v > p["rsi_guard_high"]:
                return None  # overbought — skip
            entry = f_c
            sl = entry - atr_val * p["sl_atr_mult"]
            tp = entry + (entry - sl) * p["tp_rr"]
            return Signal(
                side=Side.BUY, entry=round(entry, 2), sl=round(sl, 2), tp=round(tp, 2),
                confidence=min(0.4 + abs(hist_val) * 0.1 + (0.1 if d1_bull else 0), 0.9),
                reason=f"SMA {p['sma_fast']}/{p['sma_slow']} bullish cross — {tf}",
                tag=sym,
            )

        if f_p >= s_p and f_c < s_c and not d1_bull:
            if rsi_v < p["rsi_guard_low"]:
                return None  # oversold — skip
            entry = f_c
            sl = entry + atr_val * p["sl_atr_mult"]
            tp = entry - (sl - entry) * p["tp_rr"]
            return Signal(
                side=Side.SELL, entry=round(entry, 2), sl=round(sl, 2), tp=round(tp, 2),
                confidence=min(0.4 + abs(hist_val) * 0.1 + (0.1 if not d1_bull else 0), 0.9),
                reason=f"SMA {p['sma_fast']}/{p['sma_slow']} bearish cross — {tf}",
                tag=sym,
            )

        return None
