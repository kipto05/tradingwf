"""
Fallback MT5 adapter — used when the real metatrader5 package
cannot be imported (e.g. missing VC++ runtime, wrong Python version).

Generates realistic OHLCV data from a seed walk, plus fake but
realistic account/order behaviour so the full dashboard and
backtesting work end-to-end.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("mock_mt5")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class MT5Config:
    login: int = 0
    password: str = ""
    server: str = ""
    path: str = ""
    timeout: int = 60000
    magic_number: int = 123456
    max_retries: int = 3
    retry_delay: float = 1.0
    headless: bool = False


# ---------------------------------------------------------------------------
# Price generators (seeded so backtests are reproducible)
# ---------------------------------------------------------------------------

_SEED_STATE: dict[str, float] = {}


def _init_seed(symbol: str) -> None:
    if symbol not in _SEED_STATE:
        # Different base prices per asset class
        bases = {
            "XAUUSD.m": 2350.0,
            "XAGUSD.m": 28.0,
            "USOIL.m": 78.0,
            "UKOIL.m": 82.0,
            "BTCUSD.m": 67000.0,
            "ETHUSD.m": 3500.0,
            "SOLUSD.m": 170.0,
            "EURUSD.m": 1.08,
            "GBPUSD.m": 1.27,
            "USDJPY.m": 157.0,
            "AUDUSD.m": 0.66,
            "NZDUSD.m": 0.60,
            "USDCAD.m": 1.37,
            "USDCHF.m": 0.88,
            "EURGBP.m": 0.85,
            "EURJPY.m": 169.0,
            "GBPJPY.m": 198.0,
            "EURAUD.m": 0.97,
            "GBPAUD.m": 1.48,
            "AUDJPY.m": 103.5,
            "CADJPY.m": 114.5,
            "CHFJPY.m": 178.5,
            "AUDCAD.m": 0.90,
            "AAPL.m": 210.0,
            "TSLA.m": 248.0,
            "NVDA.m": 125.0,
            "MSFT.m": 435.0,
            "AMZN.m": 200.0,
            "GOOGL.m": 175.0,
        }
        _SEED_STATE[symbol] = bases.get(symbol, 100.0)
    random.seed(hash(symbol) % 2**32)


def _gen_ohlcv(symbol: str, tf: str, n_bars: int = 1000) -> pd.DataFrame:
    """Generate a deterministic random-walk OHLCV series."""
    _init_seed(symbol)

    tf_minutes = {
        "M1": 1,
        "M5": 5,
        "M15": 15,
        "M30": 30,
        "H1": 60,
        "H4": 240,
        "D1": 1440,
    }
    step = tf_minutes.get(tf, 60)
    vol_map = {
        "XAUUSD.m": 0.4,
        "XAGUSD.m": 0.08,
        "BTCUSD.m": 800.0,
        "ETHUSD.m": 40.0,
        "SOLUSD.m": 3.0,
        "USOIL.m": 0.5,
        "UKOIL.m": 0.6,
        "AAPL.m": 1.5,
        "TSLA.m": 3.0,
        "NVDA.m": 2.0,
        "MSFT.m": 1.2,
        "AMZN.m": 1.8,
        "GOOGL.m": 1.0,
    }
    base_vol = vol_map.get(symbol, 0.01)

    price = _SEED_STATE[symbol]
    rng = random.Random(hash(symbol + tf) % 2**32)

    now = datetime.utcnow()
    start = now - timedelta(minutes=step * n_bars)

    times = [start + timedelta(minutes=step * i) for i in range(n_bars)]
    rows = []
    for t in times:
        drift = rng.uniform(-0.002, 0.002) * price
        noise = rng.gauss(0, base_vol)
        price = max(price + drift + noise, 0.01)

        o = price
        c = price * rng.uniform(0.9995, 1.0005)
        h = max(o, c) * rng.uniform(1.0001, 1.0015)
        l = min(o, c) * rng.uniform(0.9985, 0.9999)
        v = rng.randint(50, 5000)
        rows.append(
            {
                "time": t,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )
        price = c

    df = pd.DataFrame(rows)
    return df


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class MockMT5Adapter:
    """
    Drop-in replacement for MT5Adapter when the real metatrader5 package
    cannot be imported. All public methods match the real adapter's API.
    """

    def __init__(self, config: MT5Config | None = None) -> None:
        self.cfg = config or MT5Config()
        self._connected: bool = False
        self._balance: float = 1000.0
        self._equity: float = 1000.0
        self._positions: list[dict] = []
        self._next_ticket: int = 1000

    # ---- lifecycle ----

    def connect(self) -> bool:
        self._connected = True
        logger.info(
            "[MOCK] MockMT5Adapter initialised — %s",
            datetime.utcnow().isoformat(),
        )
        return True

    def shutdown(self) -> None:
        self._connected = False
        logger.info("[MOCK] Shut down")

    def check_connection(self) -> bool:
        return self._connected

    # ---- account ----

    def get_account_info(self) -> dict:
        self._equity = self._balance + sum(
            (p.get("current_price", p["tp"]) - p["entry"]) * p["lot"]
            * (1 if p["side"] == "BUY" else -1)
            for p in self._positions
        )
        return {
            "balance": round(self._balance, 2),
            "equity": round(self._equity, 2),
            "margin": 0.0,
            "free_margin": round(self._equity, 2),
            "leverage": 1000,
            "currency": "USD",
        }

    # ---- data ----

    def get_rates(
        self, symbol: str, tf: str, n_bars: int = 1000
    ) -> pd.DataFrame:
        return _gen_ohlcv(symbol, tf, n_bars)

    # Alias so code that calls get_ohlc(...) works the same way.
    def get_ohlc(
        self, symbol: str, tf: str, n_bars: int = 500
    ) -> pd.DataFrame:
        return self.get_rates(symbol, tf, n_bars)

    def get_symbol_info(self, symbol: str) -> dict:
        digits = {
            "XAUUSD.m": 2,
            "XAGUSD.m": 3,
            "BTCUSD.m": 2,
            "ETHUSD.m": 2,
            "SOLUSD.m": 2,
            "USOIL.m": 2,
            "UKOIL.m": 2,
            "AAPL.m": 2,
            "TSLA.m": 2,
            "NVDA.m": 2,
            "MSFT.m": 2,
            "AMZN.m": 2,
            "GOOGL.m": 2,
        }.get(symbol, 2)
        return {
            "symbol": symbol,
            "digits": digits,
            "point": 10 ** (-digits),
            "lot_min": 0.01,
            "lot_max": 10.0,
            "lot_step": 0.01,
            "contract_size": 100
            if "XAU" in symbol
            else (5000 if "XAG" in symbol else 1),
            "spread": 1,
        }

    # ---- orders ----

    def place_order(
        self,
        symbol: str,
        side: str,
        lot: float,
        sl: float,
        tp: float,
        deviation: int = 10,
        comment: str = "",
    ) -> dict:
        price = _SEED_STATE.get(symbol, 100.0) * (
            1.0 + random.uniform(-0.0001, 0.0001)
        )
        ticket = self._next_ticket
        self._next_ticket += 1
        pos = {
            "ticket": ticket,
            "symbol": symbol,
            "type": side,
            "volume": lot,
            "entry": round(price, 2),
            "sl": round(sl, 2),
            "tp": round(tp, 2),
            "current_price": round(price, 2),
            "comment": comment,
            "time": datetime.utcnow().isoformat(),
            "magic": self.cfg.magic_number,
        }
        self._positions.append(pos)
        logger.info(
            "[MOCK] Order placed: %s %s %.4f lots @ %.5f ticket=%d",
            side,
            symbol,
            lot,
            price,
            ticket,
        )
        return {
            "retcode": 10009,
            "order": ticket,
            "price": price,
            "comment": "mock_executed",
        }

    def close_position(
        self, ticket: int, lot: float | None = None
    ) -> dict:
        for i, p in enumerate(self._positions):
            if p["ticket"] == ticket:
                price = p["current_price"] * (
                    1.0 + random.uniform(-0.0005, 0.0005)
                )
                pnl = (price - p["entry"]) * p["volume"] * (
                    1 if p["type"] == "BUY" else -1
                )
                self._balance += pnl
                closed = dict(
                    p, exit_price=round(price, 2), pnl=round(pnl, 2)
                )
                del self._positions[i]
                logger.info(
                    "[MOCK] Closed position #%d pnl=%.2f",
                    ticket,
                    pnl,
                )
                return {
                    "retcode": 10009,
                    "price": price,
                    "pnl": pnl,
                }
        raise ValueError(f"No position #{ticket}")

    def get_open_positions(self) -> list[dict]:
        return list(self._positions)
