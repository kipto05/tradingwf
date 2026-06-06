"""
Dashboard — FastAPI backend.
Serves the UI and all JSON endpoints for charts, trades, config.
"""

from __future__ import annotations

import csv
import logging
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi import Request

app = FastAPI(title="Trading Workflow Dashboard")
BASE = Path(__file__).parent.parent
TRADES_CSV = BASE / "logs" / "trades.csv"
TRANSCRIPTS_DIR = BASE / "data" / "transcripts"
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(BASE / "dashboard" / "static")), name="static")

INDEX_HTML: str | None = None

def _load_index() -> str:
    global INDEX_HTML
    if INDEX_HTML is None:
        INDEX_HTML = (BASE / "dashboard" / "templates" / "index.html").read_text(encoding="utf-8")
    return INDEX_HTML

_CSV_FIELDS = [
    "timestamp_open", "timestamp_close", "strategy", "asset_class",
    "symbol", "timeframe", "side", "entry_price", "exit_price",
    "sl", "tp", "lot_size", "pnl_usd", "commission",
    "balance_after", "notes",
]

log = logging.getLogger("dashboard")

def _read_trades() -> pd.DataFrame:
    if not TRADES_CSV.exists():
        return pd.DataFrame(columns=_CSV_FIELDS)
    try:
        df = pd.read_csv(TRADES_CSV)
        if "timestamp_open" in df.columns:
            df["timestamp_open"] = pd.to_datetime(df["timestamp_open"], errors="coerce")
        if "timestamp_close" in df.columns:
            df["timestamp_close"] = pd.to_datetime(df["timestamp_close"], errors="coerce")
        if not df.empty:
            df["_is_closed"] = df["timestamp_close"].notna()
        return df
    except Exception:
        return pd.DataFrame(columns=_CSV_FIELDS)

HEARTBEAT_FILE = BASE / "logs" / "engine_heartbeat"

def _is_running() -> bool:
    hb = HEARTBEAT_FILE
    if not hb.exists():
        return False
    age = _time.time() - hb.stat().st_mtime
    return age <= 90

def _engine_mode() -> str:
    return getattr(app.state, "engine_mode", "continuous")

def _risk_config() -> dict:
    return getattr(app.state, "risk_config", {
        "per_trade_risk_pct": 2.0,
        "max_open_trades": 5,
        "max_open_per_strategy": 2,
        "max_open_per_asset_class": 3,
        "daily_drawdown_pct": 3.0,
        "max_trades_per_day": 10,
        "max_weekly_loss_pct": 5.0,
        "min_risk_reward": 1.0,
        "poll_interval": 60,
        "session_mode": "continuous",
    })

def _append_backtest_result(result, n_bars: int) -> None:
    """Append a BacktestResult row to results/backtest_results.csv (skips duplicates)."""
    results_dir = BASE / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    csv_path = results_dir / "backtest_results.csv"
    row = {
        "strategy": result.strategy,
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "n_bars": n_bars,
        "total_trades": result.total_trades,
        "win_rate": round(result.win_rate * 100, 1),
        "net_pnl": result.net_pnl,
        "sharpe_approx": result.sharpe_approx,
        "profit_factor": result.profit_factor,
        "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        "avg_win": round(result.avg_win, 2),
        "avg_loss": round(result.avg_loss, 2),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
    _KEY = ("strategy", "symbol", "timeframe", "n_bars")
    if csv_path.exists():
        try:
            with open(csv_path, newline="", encoding="utf-8") as fh:
                for existing in csv.DictReader(fh):
                    if all(str(row.get(k)) == str(existing.get(k)) for k in _KEY):
                        return
        except Exception:
            pass
    file_exists = csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(row.keys()))
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

@app.get("/api/backtest-history")
async def api_backtest_history():
    """Return all rows from results/backtest_results.csv for the Backtesting tab."""
    csv_path = BASE / "results" / "backtest_results.csv"
    if not csv_path.exists():
        return JSONResponse(content=[])
    try:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        rows.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return JSONResponse(content=rows)
    except Exception as exc:
        log.exception("read backtest history failed")
        return JSONResponse(content=[], status_code=500)

@app.get("/api/backtest-equity")
async def api_backtest_equity(strategy: str = "", symbol: str = "", timeframe: str = ""):
    """Return equity-curve data for a specific backtest run."""
    if not strategy:
        return JSONResponse(content={"error": "strategy required"}, status_code=400)
    eq_name = f"{strategy}_{symbol or ''}_{timeframe or ''}".strip("_")
    eq_path = BASE / "data" / "backtests" / f"{eq_name}_equity.csv"
    trades_path = BASE / "data" / "backtests" / f"{eq_name}_trades.csv"
    # Fallback: try the simpler {strategy}_{symbol} pattern the backtester writes
    # The backtester writes: f"{strategy.meta.name}_{use_symbol}_equity.csv"
    if not eq_path.exists():
        # Try alternate naming: strategy_symbol_equity.csv (no timeframe suffix)
        alt = BASE / "data" / "backtests" / f"{strategy}_{symbol}_equity.csv"
        if alt.exists():
            eq_path = alt
    if not eq_path.exists():
        # Last fallback: just iterate and find any equity file matching the strategy
        bt_dir = BASE / "data" / "backtests"
        if bt_dir.exists():
            for f in bt_dir.iterdir():
                if f.name.startswith(strategy + "_") and f.name.endswith("_equity.csv"):
                    eq_path = f
                    break
    if not eq_path.exists():
        return JSONResponse(content={"error": "equity file not found", "path": str(eq_path)}, status_code=404)
    try:
        eq_df = pd.read_csv(eq_path)
        if eq_df.shape[1] >= 2:
            timestamps = list(range(len(eq_df)))
            equity = eq_df.iloc[:, 1].tolist()
        else:
            timestamps = list(range(len(eq_df)))
            equity = eq_df.iloc[:, 0].tolist()
        # Load trades for stats
        trades_stats: dict = {"total_trades": 0, "win_rate": 0, "avg_win": 0, "avg_loss": 0}
        if trades_path.exists():
            try:
                tdf = pd.read_csv(trades_path)
                pnl = pd.to_numeric(tdf.get("pnl", pd.Series(dtype=float)), errors="coerce")
                wins = pnl[pnl > 0]
                losses = pnl[pnl <= 0]
                trades_stats["total_trades"] = len(pnl)
                trades_stats["win_rate"] = round(len(wins) / max(len(pnl), 1) * 100, 1) if len(pnl) else 0
                trades_stats["avg_win"] = round(wins.mean(), 2) if len(wins) else 0
                trades_stats["avg_loss"] = round(losses.mean(), 2) if len(losses) else 0
            except Exception:
                pass
        return JSONResponse(content={
            "timestamps": timestamps,
            "equity": [round(v, 2) if v == v else 0 for v in equity],
            **trades_stats,
        })
    except Exception as exc:
        log.exception("read equity file failed")
        return JSONResponse(content={"error": str(exc)}, status_code=500)

def _get_live_balance() -> float:
    """Get the current account balance from the live MT5 terminal."""
    adapter = getattr(app.state, "adapter", None)
    if adapter is not None:
        try:
            info = adapter.get_account_info()
            if info and getattr(info, "balance", 0) > 0:
                return round(info.balance, 2)
        except Exception:
            pass
    try:
        from execution.mt5_adapter import MT5Adapter, MT5Config
        cfg = MT5Config(path=r"C:\Program Files\JustMarkets MetaTrader 5\terminal64.exe")
        tmp = MT5Adapter(cfg)
        if tmp.connect():
            info = tmp.get_account_info()
            tmp.disconnect()
            if info and getattr(info, "balance", 0) > 0:
                return round(info.balance, 2)
    except Exception:
        pass
    trades = _read_trades()
    if not trades.empty and "balance_after" in trades.columns:
        bal_series = pd.to_numeric(trades["balance_after"], errors="coerce")
        if "_is_closed" in trades.columns:
            closed_mask = trades["_is_closed"]
            bal_series = bal_series[closed_mask]
        last = bal_series.dropna()
        if not last.empty:
            return round(last.iloc[-1], 2)
    hb = BASE / "logs" / "last_balance.txt"
    if hb.exists():
        try:
            return float(hb.read_text().strip())
        except Exception:
            pass
    return 1000.0

# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return HTMLResponse(content=_load_index())

@app.get("/api/status")
async def api_status():
    trades = _read_trades()
    if "_is_closed" in trades.columns:
        closed = trades[trades["_is_closed"]]
    else:
        closed = trades
    return {
        "engine_running": _is_running(),
        "mode": _engine_mode(),
        "total_trades": len(closed),
        "last_trade": str(closed["timestamp_close"].iloc[-1]) if len(closed) else None,
    }

@app.get("/api/balance")
async def api_balance():
    return JSONResponse(content={"balance": _get_live_balance()})

# Trades — all trades (open + closed), last 5, sorted by close time
@app.get("/api/trades")
async def api_trades(limit: int = 5):
    limit = min(limit, 100)
    df = _read_trades()
    if df.empty:
        return JSONResponse(content=[])
    ts_col = "timestamp_close" if "timestamp_close" in df.columns and df["timestamp_close"].notna().any() else "timestamp_open"
    df = df.sort_values(ts_col, ascending=False).head(limit)
    df = df.fillna("")
    for col in ("timestamp_open", "timestamp_close"):
        if col in df.columns:
            df[col] = df[col].astype(str)
    return JSONResponse(content=df.to_dict(orient="records"))

# Open positions
@app.get("/api/open-positions")
async def api_positions():
    adapter = getattr(app.state, "adapter", None)
    if adapter is not None:
        try:
            if not adapter.check_connection():
                log.warning("MT5 connection unhealthy — attempting reconnect")
                if not adapter.connect():
                    log.error("MT5 reconnect failed for open-positions query")
            positions = adapter.get_open_positions()
            return JSONResponse(content=positions or [])
        except Exception as exc:
            log.warning("Engine adapter get_open_positions failed: %s", exc)
    try:
        from execution.mt5_adapter import MT5Adapter, MT5Config
        cfg = MT5Config(path=r"C:\Program Files\JustMarkets MetaTrader 5\terminal64.exe")
        tmp = MT5Adapter(cfg)
        if tmp.connect():
            positions = tmp.get_open_positions()
            tmp.disconnect()
        else:
            log.warning("Fallback MT5 connect failed for open-positions")
            positions = []
    except Exception as exc:
        log.warning("Fallback open-positions query failed: %s", exc)
        positions = []
    return JSONResponse(content=positions or [])

# Equity curve — primary source is balance_after from closed trades
@app.get("/api/equity-curve")
async def api_equity():
    trades = _read_trades()
    if trades.empty or "pnl_usd" not in trades.columns:
        live_bal = _get_live_balance()
        return JSONResponse(content={"timestamps": [], "equity": [], "balance": [live_bal]})

    if "_is_closed" in trades.columns:
        closed = trades[trades["_is_closed"]].copy()
    else:
        closed = trades[pd.to_numeric(trades["pnl_usd"], errors="coerce").notna()].copy()

    if closed.empty:
        live_bal = _get_live_balance()
        return JSONResponse(content={"timestamps": [], "equity": [], "balance": [live_bal]})

    live_bal = _get_live_balance()
    ts_col = "timestamp_close" if "timestamp_close" in closed.columns and closed["timestamp_close"].notna().any() else "timestamp_open"

    bal_series = pd.to_numeric(closed["balance_after"], errors="coerce")
    mask = bal_series.notna()
    if mask.any():
        balances = closed.loc[mask, "balance_after"].tolist()
        equity = balances.copy()
        ts = pd.to_datetime(closed.loc[mask, ts_col], errors="coerce")
        ts = ts.fillna(pd.Timestamp.now())
        timestamps = ts.astype(str).tolist()
    else:
        pnl = pd.to_numeric(closed["pnl_usd"], errors="coerce").fillna(0)
        initial = live_bal - pnl.sum()
        if initial <= 0:
            initial = live_bal
        eq = [initial]
        for x in pnl:
            eq.append(eq[-1] + x)
        equity = eq[1:]
        balances = equity.copy()
        ts = pd.to_datetime(closed[ts_col], errors="coerce").fillna(pd.Timestamp.now())
        timestamps = ts.astype(str).tolist()

    if balances:
        balances[-1] = live_bal
    if equity:
        equity[-1] = live_bal

    return JSONResponse(content={
        "timestamps": timestamps,
        "equity": equity,
        "balance": balances,
    })

# Stats
@app.get("/api/stats")
async def api_stats():
    """Return overall stats using LIVE balance from MT5."""
    trades = _read_trades()
    if "_is_closed" in trades.columns:
        closed = trades[trades["_is_closed"]]
    else:
        closed = trades
    live_bal = _get_live_balance()

    if closed.empty:
        return {
            "total_trades": 0, "win_rate": 0, "net_pnl": 0,
            "winning_trades": 0, "losing_trades": 0,
            "avg_win": 0, "avg_loss": 0,
            "max_balance": live_bal, "current_balance": live_bal,
        }

    pnl = pd.to_numeric(closed["pnl_usd"], errors="coerce")
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    bal_series = pd.to_numeric(closed.get("balance_after", live_bal), errors="coerce")
    return {
        "total_trades": len(pnl),
        "win_rate": round(len(wins) / max(len(pnl), 1) * 100, 1),
        "net_pnl": round(pnl.sum(), 2),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "avg_win": round(wins.mean() if len(wins) else 0, 2),
        "avg_loss": round(losses.mean() if len(losses) else 0, 2),
        "max_balance": round(bal_series.max() if not bal_series.dropna().empty else live_bal, 2),
        "current_balance": live_bal,
    }

# Strategy performance — includes placeholders for strategies with no trades
@app.get("/api/strategy-performance")
async def api_strategy_perf(strategy: str | None = None):
    trades = _read_trades()
    closed = trades[pd.to_numeric(trades["pnl_usd"], errors="coerce").notna()].copy() if "pnl_usd" in trades.columns else pd.DataFrame()

    if "_is_closed" in closed.columns:
        closed = closed[closed["_is_closed"]]

    if not closed.empty:
        clean = closed.dropna(subset=["strategy"])
        if not clean.empty:
            clean["pnl_usd"] = pd.to_numeric(clean["pnl_usd"], errors="coerce").fillna(0)
            grp = clean.groupby("strategy").agg(
                trades=("pnl_usd", "count"),
                win_rate=("pnl_usd", lambda x: round((x > 0).sum() / max(len(x), 1) * 100, 1)),
                net_pnl=("pnl_usd", "sum"),
                avg_pnl=("pnl_usd", "mean"),
                max_win=("pnl_usd", "max"),
                max_loss=("pnl_usd", "min"),
            ).reset_index()
            results = grp.to_dict(orient="records")
        else:
            results = []
    else:
        results = []

    try:
        from strategies.registry import get_registered
        existing = {r["strategy"] for r in results}
        for name, cls in get_registered().items():
            if name not in existing:
                results.append({
                    "strategy": name, "trades": 0, "win_rate": 0,
                    "net_pnl": 0, "avg_pnl": 0, "max_win": 0, "max_loss": 0,
                })
    except Exception:
        pass

    if strategy:
        results = [r for r in results if r.get("strategy") == strategy]

    return JSONResponse(content=results)

@app.get("/api/weekly-performance")
async def api_weekly():
    trades = _read_trades()
    if trades.empty or "timestamp_open" not in trades.columns:
        return JSONResponse(content={"weeks": [], "pnl": []})
    df = trades.copy()
    if "_is_closed" in df.columns:
        df = df[df["_is_closed"]]
    df["week"] = pd.to_datetime(df["timestamp_open"]).dt.to_period("W").astype(str)
    df["pnl_usd"] = pd.to_numeric(df["pnl_usd"], errors="coerce").fillna(0)
    weekly = df.groupby("week").agg(
        trades=("pnl_usd", "count"),
        pnl=("pnl_usd", "sum"),
        win_rate=("pnl_usd", lambda x: round((x > 0).sum() / max(len(x), 1) * 100, 1)),
    ).reset_index()
    return JSONResponse(content=weekly.to_dict(orient="records"))

@app.get("/api/strategies")
async def api_strategies():
    try:
        from strategies.registry import get_registered
        reg = get_registered()
        result = []
        for name, cls in reg.items():
            m = cls.meta
            result.append({
                "name": m.name, "asset_class": m.asset_class,
                "symbol": m.symbol, "symbols": m.symbols or [m.symbol],
                "timeframes": m.timeframes, "enabled": m.enabled,
            })
        return JSONResponse(content=result)
    except Exception as exc:
        return JSONResponse(content=[], status_code=500)

@app.post("/api/strategies/{name}/toggle")
async def api_toggle_strategy(name: str, payload: dict | None = None):
    payload = payload or {}
    enabled = payload.get("enabled", True)
    try:
        from strategies.registry import set_state
        ok = set_state(name, bool(enabled))
        if ok:
            return JSONResponse(content={"ok": True, "name": name, "enabled": bool(enabled)})
        return JSONResponse(content={"ok": False, "error": f"Strategy '{name}' not found"}, status_code=404)
    except Exception as exc:
        return JSONResponse(content={"ok": False, "error": str(exc)}, status_code=500)

@app.get("/api/risk-config")
async def api_get_risk():
    return JSONResponse(content=_risk_config())

@app.post("/api/risk-config")
async def api_set_risk(payload: dict):
    cfg = _risk_config()
    cfg.update({k: v for k, v in payload.items() if k in cfg})
    app.state.risk_config = cfg
    try:
        from execution.risk_manager import RISK
        RISK.update(**{k: v for k, v in payload.items() if hasattr(RISK, k)})
    except ImportError:
        pass
    log.info("Risk config updated: %s", list(payload.keys()))
    return JSONResponse(content={"ok": True, "config": cfg})

@app.post("/api/engine/start")
async def api_start(payload: dict | None = None):
    payload = payload or {}
    try:
        from main import engine as eng
        if not eng.adapter:
            eng.init_mt5(
                login=payload.get("login", 0),
                password=payload.get("password", ""),
                server=payload.get("server", ""),
            )
        eng.mode = payload.get("mode", _engine_mode())
        eng.poll_interval = payload.get("interval", 60)
        eng.start()
        app.state.engine_running = True
        return JSONResponse(content={"ok": True, "running": True})
    except Exception as exc:
        log.exception("Start failed")
        return JSONResponse(content={"ok": False, "error": str(exc)}, status_code=500)

@app.post("/api/engine/stop")
async def api_stop():
    try:
        from main import engine as eng
        eng.stop()
        app.state.engine_running = False
        return JSONResponse(content={"ok": True, "running": False})
    except Exception as exc:
        return JSONResponse(content={"ok": False, "error": str(exc)}, status_code=500)

@app.post("/api/trigger-cycle")
async def api_trigger():
    """Force one scan cycle now (for manual trigger mode)."""
    try:
        from main import engine as eng
        return JSONResponse(content={"ok": True, "msg": "Cycle triggered (check logs)"})
    except Exception as exc:
        return JSONResponse(content={"ok": False, "error": str(exc)}, status_code=500)

# Backtest
# ---------------------------------------------------------------------------

# Bars-per-month per timeframe (approx, for 24h trading days)
_BARS_PER_MONTH = {
    "M1": 43200,
    "M5": 8640,
    "M15": 2880,
    "M30": 1440,
    "H1": 720,
    "H4": 180,
    "D1": 22,
}

def _months_to_bars(months_back: int, timeframe: str) -> int:
    """Convert calendar months to bar count for a given timeframe."""
    ppm = _BARS_PER_MONTH.get(timeframe.upper(), 720)
    return max(500, months_back * ppm)

@app.post("/api/backtest")
async def api_backtest(payload: dict):
    strategy_name = payload.get("strategy", "")
    months_back = payload.get('months_back')
    tf = payload.get('timeframe', '')
    if months_back is not None:
        try:
            n_bars = _months_to_bars(int(months_back), tf)
        except (ValueError, TypeError):
            n_bars = 2000
    else:
        n_bars = int(payload.get('bars', 3000))
    selected = (payload.get("symbol") or "").strip() or None
    try:
        from execution.backtester import run_backtest
        from execution.mt5_adapter import MT5Adapter, MT5Config
        from strategies.registry import get_registered
        cfg = MT5Config()
        adapter = MT5Adapter(cfg)
        if not adapter.connect():
            return JSONResponse(content={"ok": False, "error": "MT5 connection failed"}, status_code=500)
        cls = get_registered().get(strategy_name)
        if cls is None:
            return JSONResponse(content={"ok": False, "error": f"Strategy '{strategy_name}' not found"}, status_code=400)

        result = run_backtest(cls(), adapter, n_bars, symbol=selected)
        _append_backtest_result(result, n_bars)
        adapter.shutdown()
        if result is None:
            return JSONResponse(content={"ok": False, "error": "Backtest produced 0 trades"}, status_code=400)
        return JSONResponse(content={
            "ok": True,
            "strategy": result.strategy, "symbol": result.symbol, "timeframe": result.timeframe,
            "total_trades": result.total_trades,
            "win_rate": round(result.win_rate * 100, 1),
            "net_pnl": result.net_pnl,
            "sharpe": result.sharpe_approx,
            "profit_factor": result.profit_factor,
            "max_drawdown_pct": round(result.max_drawdown_pct, 2),
        })
    except Exception as exc:
        log.exception("Backtest error")
        return JSONResponse(content={"ok": False, "error": str(exc)}, status_code=500)

@app.post("/api/backtest-all")
async def api_backtest_all():
    try:
        from execution.backtester import run_backtest
        from execution.mt5_adapter import MT5Adapter, MT5Config
        from strategies.registry import get_registered
        cfg = MT5Config()
        adapter = MT5Adapter(cfg)
        if not adapter.connect():
            return JSONResponse(content={"ok": False, "error": "MT5 connection failed"}, status_code=500)
        results = []
        for name, cls in get_registered().items():
            r = run_backtest(cls(), adapter, 2000)
            if r:
                _append_backtest_result(r, n_bars=2000)
                results.append({
                    "strategy": r.strategy, "symbol": r.symbol, "timeframe": r.timeframe,
                    "total_trades": r.total_trades,
                    "win_rate": round(r.win_rate * 100, 1),
                    "net_pnl": r.net_pnl,
                    "sharpe": r.sharpe_approx,
                    "profit_factor": r.profit_factor,
                    "max_drawdown_pct": round(r.max_drawdown_pct, 2),
                })
        adapter.shutdown()
        return JSONResponse(content={"ok": True, "results": results})
    except Exception as exc:
        return JSONResponse(content={"ok": False, "error": str(exc)}, status_code=500)

# Transcript upload
@app.post("/api/upload-transcript")
async def api_upload_transcript(file: UploadFile = File(...)):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"{ts}_{file.filename}"
    dest = TRANSCRIPTS_DIR / safe_name
    try:
        content = await file.read()
        dest.write_bytes(content)
        log.info("Transcript saved: %s (%d bytes)", dest.name, len(content))
        text_preview = ""
        try:
            if dest.suffix.lower() in (".txt", ".md"):
                text_preview = dest.read_text(encoding="utf-8", errors="ignore")[:500]
            elif dest.suffix.lower() == ".pdf":
                text_preview = f"[PDF file — {len(content)} bytes]"
            else:
                text_preview = f"[Uploaded: {file.filename}]"
        except Exception:
            text_preview = "[Uploaded — unable to preview]"
        return JSONResponse(content={"ok": True, "filename": safe_name, "preview": text_preview})
    except Exception as exc:
        return JSONResponse(content={"ok": False, "error": str(exc)}, status_code=500)

@app.get("/api/transcripts")
async def api_list_transcripts():
    files = sorted(TRANSCRIPTS_DIR.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
    return JSONResponse(content=[
        {"name": f.name, "size": f.stat().st_size,
         "date": datetime.fromtimestamp(f.stat().st_mtime).isoformat()}
        for f in files if f.is_file()
    ])
