"""
Engine settings + database helpers.

Provides what percent of the engine + backtester need:

from config.settings import get_database, get_engine_config
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger("config.settings")

_BASE_DIR = Path(__file__).resolve().parent
_DB_PATH = _BASE_DIR / "trade_history.db"


def get_database(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Return an open sqlite connection with row factory + WAL mode."""
    path = Path(db_path) if db_path else _DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_open TEXT,
            timestamp_close TEXT,
            strategy TEXT,
            asset_class TEXT,
            symbol TEXT,
            timeframe TEXT,
            side TEXT,
            entry_price REAL,
            exit_price REAL,
            sl REAL,
            tp REAL,
            lot_size REAL,
            pnl_usd REAL,
            commission REAL,
            balance_after REAL,
            notes TEXT
        )
        """
    )
    conn.commit()
    return conn


@dataclass
class EngineConfig:
    """Central config for the trading engine — yaml overrides are read at call time."""

    USE_MOCK_MT5: bool = False
    mt5_path: str = r"C:\Program Files\JustMarkets MetaTrader 5\terminal64.exe"
    login: int = 0
    password: str = ""
    server: str = ""
    default_mode: str = "continuous"
    poll_interval: int = 60

    def to_dict(self) -> dict:
        return {
            "use_mock_mt5": self.USE_MOCK_MT5,
            "mt5_path": self.mt5_path,
            "login": self.login,
            "server": self.server,
            "default_mode": self.default_mode,
            "poll_interval": self.poll_interval,
        }


def get_engine_config() -> EngineConfig:
    """Return the singleton engine config — dashboard can mutate in-process."""
    return EngineConfig()
