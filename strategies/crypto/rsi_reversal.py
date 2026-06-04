"""
RSI Reversal — BTCUSD.m, ETHUSD.m
Oversold bounce / overbought rejection with Bollinger Band confirmation.
M15/H1 for day-trade entries — requires RSI divergence.
"""

from __future__ import annotations

import pandas as pd

from strategies.shared.indicators import rsi, bollinger_bands, ema, atr
from strategies.base import BaseStrategy, Signal, StrategyMeta, Side
from strategies.registry import register


_CRYPTO_REVERSAL = ["BTCUSD.m", "ETHUSD.m"]


@register
class RSIReversalCrypto(BaseStrategy):
    meta = StrategyMeta(
        name="RSI Reversal (Crypto)",
        asset_class="crypto",
        symbol="BTCUSD.m",
        timeframes=["M15", "H1"],
        params={
            "rsi_period": 14,
            "rsi_oversold": 30,
            "rsi_overbought": 70,
            "bb_period": 20,
            "bb_std": 2.0,
            "atr_period": 14,
            "sl_atr_mult": 1.0,
            "tp_rr": 1.5,
            "divergence_lookback": 14,
            "min_confidence": 0.4,
            "enabled": True,
        },
    )

    def generate_signal(self, data: dict[str, pd.DataFrame]) -> Signal | None:
        p = self.meta.params
        tf = "M15" if "M15" in data else "H1"
        df = data.get(tf)
        if df is None or len(df) < 50:
            return None

        close = df["close"]
        r = rsi(close, p["rsi_period"])
        bb_up, bb_mid, bb_lo = bollinger_bands(close, p["bb_period"], p["bb_std"])
        atr_val = atr(df["high"], df["low"], df["close"], p["atr_period"]).iloc[-1]
        rsi_v = r.iloc[-1]
        ema50 = ema(close, 50).iloc[-1]
        sym = self.meta.symbol

        # Bullish reversal: RSI < oversold, price below lower BB, RSI divergence
        if rsi_v < p["rsi_oversold"] and close.iloc[-1] < bb_lo.iloc[-1]:
            if self._bull_divergence(close, r, p["divergence_lookback"]):
                entry = close.iloc[-1]
                sl = entry - atr_val * p["sl_atr_mult"]
                tp = entry + (entry - sl) * p["tp_rr"]
                rr = abs(tp - entry) / max(abs(entry - sl), 0.01)
                if rr < p["min_rr"]:
                    tp = entry + abs(entry - sl) * p["min_rr"]
                conf = min(0.4 + rr * 0.1 + (0.1 if entry > ema50 else 0), 0.85)
                return Signal(
                    side=Side.BUY, entry=round(entry, 2), sl=round(sl, 2), tp=round(tp, 2),
                    confidence=conf,
                    reason=f"RSI oversold ({rsi_v:.0f}) + BB lower band — bullish div",
                    tag=sym,
                )

        # Bearish reversal
        if rsi_v > p["rsi_overbought"] and close.iloc[-1] > bb_up.iloc[-1]:
            if self._bear_divergence(close, r, p["divergence_lookback"]):
                entry = close.iloc[-1]
                sl = entry + atr_val * p["sl_atr_mult"]
                tp = entry - (sl - entry) * p["tp_rr"]
                rr = abs(entry - tp) / max(abs(sl - entry), 0.01)
                if rr < p["min_rr"]:
                    tp = entry - abs(sl - entry) * p["min_rr"]
                conf = min(0.4 + rr * 0.1 + (0.1 if entry < ema50 else 0), 0.85)
                return Signal(
                    side=Side.SELL, entry=round(entry, 2), sl=round(sl, 2), tp=round(tp, 2),
                    confidence=conf,
                    reason=f"RSI overbought ({rsi_v:.0f}) + BB upper band — bearish div",
                    tag=sym,
                )

        return None

    @staticmethod
    def _bull_divergence(close: pd.Series, rsi: pd.Series, lookback: int) -> bool:
        if len(close) < lookback + 2:
            return False
        prev_p, cur_p = close.iloc[-lookback - 1], close.iloc[-1]
        prev_r, cur_r = rsi.iloc[-lookback - 1], rsi.iloc[-1]
        return cur_p < prev_p and cur_r > prev_r

    @staticmethod
    def _bear_divergence(close: pd.Series, rsi: pd.Series, lookback: int) -> bool:
        if len(close) < lookback + 2:
            return False
        prev_p, cur_p = close.iloc[-lookback - 1], close.iloc[-1]
        prev_r, cur_r = rsi.iloc[-lookback - 1], rsi.iloc[-1]
        return cur_p > prev_p and cur_r < prev_r
