"""Trade logging helper — fixes log_trade() TypeError."""
from __future__ import annotations

import csv
import logging
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("trade_log")

BASE = Path(r"C:\Users\hp\tradingwf")
TRADES_CSV = BASE / "logs" / "trades.csv"
_FIELDS = [
    "timestamp_open", "timestamp_close", "strategy",
    "asset_class", "symbol", "timeframe", "side",
    "entry_price", "exit_price", "sl", "tp",
    "lot_size", "pnl_usd", "commission", "balance_after",
    "notes",
]
_lock = threading.Lock()

# Ensure file + header exists
TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
if not TRADES_CSV.exists():
    with TRADES_CSV.open("w", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=_FIELDS).writeheader()
    logger.info("Created trades.csv header")


def log_trade(record) -> None:
    if hasattr(record, "__dataclass_fields__"):
        record = {
            k: getattr(record, k, "")
            for k in _FIELDS
            if k in record.__dataclass_fields__
        }
    if not isinstance(record, dict):
        logger.error("log_trade() received non-dict / non-dataclass: %r", type(record))
        return
    with _lock:
        with TRADES_CSV.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=_FIELDS)
            w.writerow({k: record.get(k, "") for k in _FIELDS})
    logger.info("Logged trade: %s %s %.4f lots @ %.5f",
                record.get("side"), record.get("symbol"),
                record.get("lot_size"), record.get("entry_price"))
