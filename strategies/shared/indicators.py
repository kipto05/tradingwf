"""
Shared technical indicators — thin wrapper over pandas so strategies
stay clean and testable without TA-Lib dependency.
"""

import pandas as pd
import numpy as np


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(series: pd.Series, window: int = 20, num_std: float = 2.0):
    mid = sma(series, window)
    std = series.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return upper, mid, lower


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff())
    obv = (direction * volume).fillna(0).cumsum()
    return obv


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    plus_dm[plus_dm < minus_dm] = 0
    minus_dm[minus_dm <= plus_dm] = 0

    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(span=period, adjust=False).mean()


def detect_support_resistance(
    high: pd.Series,
    low: pd.Series,
    window: int = 20,
    num_touches: int = 2
) -> tuple[list[float], list[float]]:
    """
    Simple pivot-based S/R detection.
    A level is valid if price touched it ≥ num_touches times in the window.
    """
    pivot_high = (high.shift(1) > high.shift(2)) & (high.shift(1) > high)
    pivot_low = (low.shift(1) < low.shift(2)) & (low.shift(1) < low)

    resistance_levels = []
    support_levels = []

    for i in range(window, len(high)):
        window_highs = high.iloc[i - window : i + 1]
        window_lows = low.iloc[i - window : i + 1]

        # Cluster highs into levels
        resistance_candidates = window_highs[pivot_high.iloc[i - window : i + 1]]
        for level in resistance_candidates:
            touches = (window_highs - level).abs().lt(window_highs.std() * 0.1).sum()
            if touches >= num_touches:
                resistance_levels.append(level)

        support_candidates = window_lows[pivot_low.iloc[i - window : i + 1]]
        for level in support_candidates:
            touches = (window_lows - level).abs().lt(window_lows.std() * 0.1).sum()
            if touches >= num_touches:
                support_levels.append(level)

    # Deduplicate
    resistance_levels = sorted(set(round(x, 4) for x in resistance_levels))
    support_levels = sorted(set(round(x, 4) for x in support_levels))
    return support_levels, resistance_levels


def volume_profile(close: pd.Series, volume: pd.Series, bins: int = 24) -> pd.DataFrame:
    """Returns price levels sorted by traded volume (POC, VAH, VAL)."""
    df = pd.DataFrame({"price": close, "volume": volume}).dropna()
    if len(df) == 0:
        return pd.DataFrame(columns=["price_bin", "volume", "cum_volume"])
    df["price_bin"] = pd.cut(df["price"], bins=bins)
    vp = df.groupby("price_bin", observed=True)["volume"].sum().reset_index()
    vp["price_bin"] = vp["price_bin"].astype(str)
    vp["cum_volume"] = vp["volume"].cumsum()
    return vp
