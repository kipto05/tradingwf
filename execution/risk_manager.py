"""Risk Manager - enforces ALL portfolio-level safeguards.

Reads config/risk.yaml for defaults; dashboard can override at runtime.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from execution.mt5_adapter import MT5Adapter  # noqa: F401

logger = logging.getLogger("risk_manager")

# ---------------------------------------------------------------------------
# Runtime config (editable via dashboard)
# ---------------------------------------------------------------------------

class RiskConfig:
    per_trade_risk_pct: float = 0.02        # 2 % per trade
    max_open_trades: int = 5                 # total open positions
    max_open_per_strategy: int = 2           # per strategy
    max_open_per_symbol: int = 1             # ONE trade per symbol at a time
    max_trades_per_day: int = 10
    daily_drawdown_pct: float = 3.0
    max_weekly_loss_pct: float = 5.0
    min_risk_reward: float = 1.0

    def update(self, **kwargs):
        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
        logger.info("RiskConfig updated: %s", list(kwargs.keys()))

RISK = RiskConfig()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _positions_by_symbol(positions: list[dict]) -> dict[str, list[dict]]:
    """Group open positions by their symbol."""
    by_sym: dict[str, list[dict]] = {}
    for p in positions:
        sym = p.get("symbol", "")
        by_sym.setdefault(sym, []).append(p)
    return by_sym

def _positions_by_comment_prefix(
    positions: list[dict], prefix: str
) -> list[dict]:
    """Return positions whose comment starts with *prefix* (case-insensitive)."""
    prefix_lower = prefix.lower()
    return [
        p for p in positions
        if (p.get("comment", "") or "").lower().startswith(prefix_lower)
    ]

# ---------------------------------------------------------------------------
# RiskManager
# ---------------------------------------------------------------------------

class RiskManager:
    def __init__(self, adapter: "MT5Adapter"):
        self.adapter = adapter
        self.day_start_equity: float = 0.0
        self.week_start_equity: float = 0.0
        self.day_start: datetime | None = None
        self.week_start: datetime | None = None
        self.trades_today: int = 0

    # ---- session bookkeeping ----

    def sync_session(self):
        """Reset daily/weekly counters at appropriate boundaries."""
        now = datetime.now()
        info = self.adapter.get_account_info()
        equity = getattr(info, "equity", 0.0) if info else 0.0

        if self.day_start is None or now.date() != self.day_start.date():
            self.day_start = now
            self.day_start_equity = equity
            self.trades_today = 0
            logger.info("New trading day — equity baseline: %.2f", equity)

        if self.week_start is None or now.isocalendar().week != self.week_start.isocalendar().week:
            self.week_start = now
            self.week_start_equity = equity

    # ---- can I open a trade? ----

    def can_open_trade(self, symbol: str = "", strategy_comment: str = "") -> tuple[bool, str]:
        """Return (allowed, reason).

        Checks in order:
        1. Daily / weekly drawdown
        2. Max trades per day
        3. Max open positions total (max_open_trades)
        4. Max open per symbol (max_open_per_symbol) — prevents duplicate pair entries
        5. Max open per strategy (max_open_per_strategy)
        """
        self.sync_session()
        info = self.adapter.get_account_info()
        equity = getattr(info, "equity", 0.0) if info else 0.0
        positions = self.adapter.get_open_positions()

        # --- drawdown guards ---
        if self.day_start_equity > 0:
            dd = (self.day_start_equity - equity) / self.day_start_equity * 100
            if dd >= RISK.daily_drawdown_pct:
                return False, f"Daily drawdown {dd:.1f}% >= {RISK.daily_drawdown_pct}%"

        if self.week_start_equity > 0:
            wd = (self.week_start_equity - equity) / self.week_start_equity * 100
            if wd >= RISK.max_weekly_loss_pct:
                return False, f"Weekly loss {wd:.1f}% >= {RISK.max_weekly_loss_pct}%"

        # --- trade count guards ---
        if self.trades_today >= RISK.max_trades_per_day:
            return False, f"Max daily trades ({RISK.max_trades_per_day})"

        total_open = len(positions)
        if total_open >= RISK.max_open_trades:
            return False, f"Max open trades ({RISK.max_open_trades}/{total_open})"

        # --- per-symbol guard (key fix: 1 trade per pair) ---
        if symbol:
            by_sym = _positions_by_symbol(positions)
            sym_open = len(by_sym.get(symbol, []))
            if sym_open >= RISK.max_open_per_symbol:
                return (
                    False,
                    f"Symbol {symbol} already has {sym_open} open position(s)",
                )

        # --- per-strategy guard ---
        if strategy_comment:
            strat_positions = _positions_by_comment_prefix(positions, strategy_comment)
            if len(strat_positions) >= RISK.max_open_per_strategy:
                return (
                    False,
                    f"Strategy '{strategy_comment}' at cap ({len(strat_positions)}/{RISK.max_open_per_strategy})",
                )

        return True, "OK"

    def can_open_for_strategy(self, strategy_name: str) -> tuple[bool, str]:
        """Legacy per-strategy check kept for backward compat."""
        positions = self.adapter.get_open_positions()
        count = len(_positions_by_comment_prefix(positions, strategy_name))
        if count >= RISK.max_open_per_strategy:
            return False, f"Strategy '{strategy_name}' cap ({count}/{RISK.max_open_per_strategy})"
        return True, "OK"

    # ---- position sizing ----

    def calc_lot_size(self, symbol, entry, sl, balance=None):
        """Fixed-fraction sizing: risk `per_trade_risk_pct` of balance per trade."""
        if balance is None:
            info = self.adapter.get_account_info()
            balance = getattr(info, "balance", 1000.0) if info else 1000.0
        sym_info = self.adapter.get_symbol_info(symbol)
        contract = sym_info.get("contract_size") or sym_info.get("trade_contract_size", 100000)
        point = sym_info.get("point", 0.00001)
        digits = sym_info.get("digits", 5)
        lot_min = sym_info.get("volume_min", 0.01)
        lot_max = sym_info.get("volume_max", 100.0)
        lot_step = sym_info.get("volume_step", 0.01)

        risk_usd = balance * RISK.per_trade_risk_pct
        sl_dist = abs(entry - sl)
        if sl_dist == 0:
            return lot_min
        raw_lots = risk_usd / (sl_dist * contract)
        steps = round(raw_lots / lot_step)
        lots = max(lot_min, min(steps * lot_step, lot_max))
        logger.debug(
            "Sized %s: bal=%.2f risk=%.2f%% sl=%.5f contract=%d -> %.4f lots",
            symbol, balance, RISK.per_trade_risk_pct * 100, sl_dist, contract, lots,
        )
        return round(lots, 2)

    # ---- bookkeeping ----

    def record_trade(self):
        self.trades_today += 1

    def get_state(self) -> dict:
        info = self.adapter.get_account_info()
        if info is None:
            return {"balance": 0.0, "equity": 0.0}
        if hasattr(info, "_asdict"):
            d = info._asdict()
        elif isinstance(info, dict):
            d = info
        else:
            d = {k: getattr(info, k) for k in (
                "login", "balance", "equity", "margin", "free_margin",
                "currency", "leverage", "name", "server",
            ) if hasattr(info, k)}
        d["risk_config"] = {
            "per_trade_risk_pct": RISK.per_trade_risk_pct,
            "max_open_trades": RISK.max_open_trades,
            "max_open_per_strategy": RISK.max_open_per_strategy,
            "max_open_per_symbol": RISK.max_open_per_symbol,
            "max_trades_per_day": RISK.max_trades_per_day,
            "daily_drawdown_pct": RISK.daily_drawdown_pct,
            "max_weekly_loss_pct": RISK.max_weekly_loss_pct,
            "min_risk_reward": RISK.min_risk_reward,
        }
        d["trades_today"] = self.trades_today
        return d
