"""
Stock Breakout — AAPL.m, TSLA.m, NVDA.m, MSFT.m, AMZN.m, GOOGL.m
Price breaking above 20-day high on volume surge + 50 EMA alignment.
H4 for swing entries; H1 for more active day-trade entries.
Based on the most commonly cited US stock breakout strategies from recent trading content.
"""

from __future__ import annotations

import pandas as pd

from strategies.shared.indicators import ema, sma, atr, rsi, bollinger_bands
from strategies.base import BaseStrategy, Signal, StrategyMeta, Side
from strategies.registry import register


_STOCK_PAIRS = ["AAPL.m", "TSLA.m", "NVDA.m", "MSFT.m", "AMZN.m", "GOOGL.m"]


@register
class StockBreakout(BaseStrategy):
    meta = StrategyMeta(
        name="Stock Breakout (AAPL/tech)",
        asset_class="stocks",
        symbol="AAPL.m",
        timeframes=["H1", "H4"],
        params={
            "lookback_high": 20,        # N-day high for breakout
            "lookback_low": 20,         # N-day low for breakdown
            "vol_sma_period": 20,       # volume SMA for volume surge check
            "vol_multiplier": 1.5,      # volume must be X × avg
            "ema_trend_period": 50,     # price must be above/below this
            "ema_trend_offset": 5,      # compare EMA now vs 5 bars ago
            "atr_period": 14,
            "sl_atr_mult": 1.0,
            "tp_rr": 1.8,
            "rsi_max_long": 65,         # avoid overbought longs
            "rsi_min_short": 35,        # avoid oversold shorts
            "bb_squeeze_filter": False, # require BB width > threshold
            "min_confidence": 0.4,
            "enabled": True,
        },
    )

    def generate_signal(self, data: dict[str, pd.DataFrame]) -> Signal | None:
        p = self.meta.params
        tf = next((t for t in ["H4", "H1"] if t in data), list(data.keys())[-1])
        df = data.get(tf)
        if df is None or len(df) < 80:
            return None

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df.get("volume", pd.Series(dtype=float))
        atr_val = atr(high, low, close, p["atr_period"]).iloc[-1]
        ema_trend = ema(close, p["ema_trend_period"])
        trend_bull = ema_trend.iloc[-1] > ema_trend.iloc[-p["ema_trend_offset"]] if len(ema_trend) > p["ema_trend_offset"] else True
        sym = self.meta.symbol

        lookback = min(p["lookback_high"], len(df) - 1)
        if lookback < 5:
            return None

        n_day_high = high.iloc[-lookback:-1].max()
        n_day_low = low.iloc[-lookback:-1].min()
        last_close = close.iloc[-1]
        last_high = high.iloc[-1]
        last_low = low.iloc[-1]
        last_vol = volume.iloc[-1] if len(volume) > 0 else 0

        # Volume surge check
        vol_ok = True
        if len(volume) > p["vol_sma_period"]:
            avg_vol = sma(volume, p["vol_sma_period"]).iloc[-1]
            vol_ok = avg_vol > 0 and last_vol > avg_vol * p["vol_multiplier"]

        rsi_v = rsi(close, 14).iloc[-1] if len(close) > 14 else 50

        # Bullish breakout
        if last_high > n_day_high and last_close > n_day_high and trend_bull and vol_ok and rsi_v < p["rsi_max_long"]:
            entry = last_close
            sl = entry - atr_val * p["sl_atr_mult"]
            tp = entry + (entry - sl) * p["tp_rr"]
            return Signal(
                side=Side.BUY, entry=round(entry, 2), sl=round(sl, 2), tp=round(tp, 2),
                confidence=0.7,
                reason=f"20-day high breakout | vol surge | EMA trend bullish",
                tag=sym,
            )

        # Bearish breakdown
        if last_low < n_day_low and last_close < n_day_low and not trend_bull and vol_ok and rsi_v > p["rsi_min_short"]:
            entry = last_close
            sl = entry + atr_val * p["sl_atr_mult"]
            tp = entry - (sl - entry) * p["tp_rr"]
            return Signal(
                side=Side.SELL, entry=round(entry, 2), sl=round(sl, 2), tp=round(tp, 2),
                confidence=0.7,
                reason=f"20-day low breakdown | vol surge | EMA trend bearish",
                tag=sym,
            )

        return None
