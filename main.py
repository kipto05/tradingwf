"""Trading engine: scans strategies, executes trades, logs to CSV."""
from __future__ import annotations

import argparse
import csv
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from config.schedule import ScheduleMode, in_active_session

log = logging.getLogger("engine")
BASE_DIR = Path(__file__).resolve().parent

# ---- logging setup ----
_LOG = BASE_DIR / "logs" / "engine.log"
_LOG.parent.mkdir(parents=True, exist_ok=True)
_h = logging.FileHandler(_LOG, encoding="utf-8")
_h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[_h, logging.StreamHandler()])

HEARTBEAT_FILE = BASE_DIR / "logs" / "engine_heartbeat"
TRADES_CSV = BASE_DIR / "logs" / "trades.csv"
_CSV_FIELDS = [
    "timestamp_open", "timestamp_close", "strategy", "asset_class",
    "symbol", "timeframe", "side", "entry_price", "exit_price",
    "sl", "tp", "lot_size", "pnl_usd", "commission", "balance_after", "notes",
]


def _touch_heartbeat() -> None:
    try:
        HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.write_text(str(time.time()), encoding="utf-8")
    except Exception as exc:
        log.debug("Heartbeat write failed: %s", exc)


def _csv_val(v):
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if v is None:
        return ""
    return v


def _trade_log(record) -> None:
    """Append a TradeRecord (dataclass or dict) to trades.csv."""
    TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(record, "to_csv_row"):
        row = record.to_csv_row()
    elif hasattr(record, "__dict__"):
        row = {f: _csv_val(getattr(record, f, "")) for f in _CSV_FIELDS}
    else:
        row = {f: _csv_val(record.get(f, "")) for f in _CSV_FIELDS}
    write_header = not TRADES_CSV.exists() or TRADES_CSV.stat().st_size == 0
    with open(TRADES_CSV, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    log.info(
        "CSV written: %s %s pnl=%s",
        row.get("symbol"), row.get("side"), row.get("pnl_usd"),
    )


def _resolve_adapter():
    from execution.mt5_adapter import MT5Adapter, MT5Config
    try:
        import metatrader5 as _mt5  # noqa: F401
        return MT5Adapter, MT5Config
    except (ImportError, ModuleNotFoundError):
        log.warning("metatrader5 unavailable -- using MockMT5Adapter")
        from execution.mock_mt5 import MockMT5Adapter, MT5Config
        return MockMT5Adapter, MT5Config


class TradingEngine:
    def __init__(self):
        self.running = False
        self.mode = ScheduleMode.CONTINUOUS
        self.poll_interval = 60
        self._thread = None
        self.adapter = None
        self.risk = None
        self.order = None
        self.strategies = {}
        self._closed_count = 0

    def init_mt5(self, login=0, password="", server=""):
        from execution.order_manager import OrderManager
        from execution.risk_manager import RiskManager
        from strategies.registry import get_enabled
        AdapterCls, ConfigCls = _resolve_adapter()
        cfg = ConfigCls(
            path=r"C:\Program Files\JustMarkets MetaTrader 5\terminal64.exe",
            login=login,
            password=password,
            server=server,
        )
        self.adapter = AdapterCls(cfg)
        mode = "[MOCK]" if AdapterCls.__name__ == "MockMT5Adapter" else ""
        if not self.adapter.connect():
            raise RuntimeError(f"{mode} Cannot connect -- is MetaTrader 5 open?")
        self.risk = RiskManager(self.adapter)

        class _CSVShim:
            def log_trade(self, record):
                _trade_log(record)

        self.order = OrderManager(self.adapter, self.risk, _CSVShim())
        self.strategies = {name: cls() for name, cls in get_enabled().items()}
        log.info(
            "%s Connected -- %d strategies, adapter=%s",
            mode, len(self.strategies), AdapterCls.__name__,
        )

    def start(self):
        if self.running:
            log.warning("Already running")
            return
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info(
            "Trading engine started (mode=%s, interval=%ds)",
            self.mode, self.poll_interval,
        )

    def stop(self):
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        if self.adapter:
            self.adapter.shutdown()
        log.info("Trading engine stopped")

    def _loop(self):
        import pandas as pd
        from strategies.registry import get_enabled
        _touch_heartbeat()
        while self.running:
            try:
                if not self.adapter or not self.adapter.check_connection():
                    log.error("MT5 disconnected -- pausing")
                    time.sleep(30)
                    continue
                _touch_heartbeat()
                if self.order:
                    closed = self.order.close_at_tp_or_sl()
                    if closed:
                        self._closed_count += len(closed)
                        log.info(
                            "Closed %d position(s) this cycle (total closed: %d)",
                            len(closed), self._closed_count,
                        )
                if self.risk:
                    self.risk.sync_session()
                for name, cls in get_enabled().items():
                    strat = self.strategies.get(name) or cls()
                    self.strategies[name] = strat
                    if not in_active_session(self.mode, strat.meta.asset_class):
                        continue
                    data = {}
                    for tf in strat.meta.timeframes:
                        df = self.adapter.get_ohlc(strat.meta.symbol, tf, 1000)
                        if not df.empty:
                            data[tf] = df
                    if not data:
                        continue
                    signal = strat.generate_signal(data)
                    if signal is None:
                        continue
                    log.info(
                        "Signal [%s]: %s -> %s %s @ %.5f SL %.5f TP %.5f",
                        name, signal.side.value, signal.tag,
                        strat.meta.symbol, signal.entry, signal.sl, signal.tp,
                    )
                    if self.order:
                        rec = self.order.execute(
                            signal=signal,
                            strategy_name=name,
                            asset_class=strat.meta.asset_class,
                            timeframe=strat.meta.timeframes[-1],
                        )
                        if rec:
                            log.info("Trade logged: %s", rec.symbol)
                        else:
                            log.info(
                                "Trade NOT executed [%s]: risk limit or validation",
                                strat.meta.symbol,
                            )
            except Exception as exc:
                log.exception("Loop error: %s", exc)
            time.sleep(self.poll_interval)


engine = TradingEngine()

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="continuous",
                    choices=["continuous", "session_aware"])
    ap.add_argument("--interval", type=int, default=60)
    ap.add_argument("--login", type=int, default=0)
    ap.add_argument("--password", default="")
    ap.add_argument("--server", default="")
    ap.add_argument("--dashboard-only", action="store_true")
    args = ap.parse_args()

    mode_map = {
        "continuous": ScheduleMode.CONTINUOUS,
        "session_aware": ScheduleMode.SESSION_AWARE,
    }
    engine_mode = mode_map.get(args.mode, ScheduleMode.CONTINUOUS)

    if not args.dashboard_only:
        engine.mode = engine_mode
        engine.poll_interval = args.interval
        try:
            engine.init_mt5(login=args.login, password=args.password, server=args.server)
        except Exception as exc:
            log.error("MT5 init failed (%s) -- dashboard will still start", exc)
        try:
            engine.start()
        except Exception as exc:
            log.error("Engine start failed (%s)", exc)
    else:
        log.info("Dashboard-only mode -- skipping MT5 connection")

    import uvicorn
    uvicorn.run(
        "dashboard.app:app", host="127.0.0.1", port=8000, log_level="info",
    )
