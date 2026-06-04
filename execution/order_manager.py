"""Order Manager - bridges RiskManager signals to MT5Adapter orders."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from execution.mt5_adapter import MT5Adapter
from execution.risk_manager import RiskManager, RISK
from strategies.base import Signal, Side

logger = logging.getLogger("order_manager")


@dataclass
class TradeRecord:
    timestamp_open: datetime
    timestamp_close: Optional[datetime]
    strategy: str
    asset_class: str
    symbol: str
    timeframe: str
    side: str
    entry_price: float
    exit_price: Optional[float]
    sl: float
    tp: float
    lot_size: float
    pnl_usd: Optional[float]
    commission: float
    balance_after: Optional[float]
    ticket: Optional[int]
    notes: str

    def to_csv_row(self) -> dict:
        return {
            "timestamp_open": self.timestamp_open.isoformat(),
            "timestamp_close": self.timestamp_close.isoformat() if self.timestamp_close else "",
            "strategy": self.strategy,
            "asset_class": self.asset_class,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "side": self.side,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price if self.exit_price is not None else "",
            "sl": self.sl,
            "tp": self.tp,
            "lot_size": self.lot_size,
            "pnl_usd": self.pnl_usd if self.pnl_usd is not None else "",
            "commission": self.commission,
            "balance_after": self.balance_after if self.balance_after is not None else "",
            "notes": self.notes,
        }


class OrderManager:
    def __init__(
        self,
        adapter: MT5Adapter,
        risk_mgr: RiskManager,
        csv_logger: object,
    ):
        self.adapter = adapter
        self.risk = risk_mgr
        self.csv = csv_logger

    # ---- main entry point ----

    def execute(
        self,
        signal: Signal,
        strategy_name: str,
        asset_class: str,
        timeframe: str,
    ) -> TradeRecord | None:
        """Validate signal -> check live MT5 risk limits -> size -> place -> log."""
        symbol = signal.tag

        if not self._validate_signal(signal):
            logger.info("Signal rejected: %s", signal.reason)
            return None

        # 1. Global portfolio guard (includes per-symbol, per-strategy, total cap)
        ok, reason = self.risk.can_open_trade(
            symbol=symbol,
            strategy_comment=strategy_name,
        )
        if not ok:
            logger.info("Trade blocked [%s]: %s", symbol, reason)
            return None

        # 2. Size position
        info = self.adapter.get_account_info()
        balance = getattr(info, "balance", 1000.0) if info else 1000.0
        lot = self.risk.calc_lot_size(
            symbol=symbol,
            entry=signal.entry,
            sl=signal.sl,
            balance=balance,
        )

        # 3. Place order
        try:
            result = self.adapter.place_order(
                symbol=symbol,
                side=signal.side.value,
                lot=lot,
                sl=signal.sl,
                tp=signal.tp,
                comment=f"{strategy_name}|{asset_class}|{timeframe}"[:32],
            )
        except Exception as exc:
            logger.error("Order placement failed [%s]: %s", symbol, exc)
            return None

        ticket = result.get("order")
        self.risk.record_trade()

        record = TradeRecord(
            timestamp_open=datetime.now(),
            timestamp_close=None,
            strategy=strategy_name,
            asset_class=asset_class,
            symbol=symbol,
            timeframe=timeframe,
            side=signal.side.value,
            entry_price=signal.entry,
            exit_price=None,
            sl=signal.sl,
            tp=signal.tp,
            lot_size=lot,
            pnl_usd=None,
            commission=0.0,
            balance_after=balance,
            ticket=ticket,
            notes=signal.reason,
        )
        self.csv.log_trade(record)
        logger.info(
            "Executed [%s] %s %.4f lots ticket=%s balance=%.2f",
            symbol, signal.side.value, lot, ticket, balance,
        )
        return record

    def close_at_tp_or_sl(self) -> list[TradeRecord]:
        """Check all open positions: if SL/TP hit, close and log PnL to CSV.

        Returns a list of newly closed TradeRecords (empty if none closed).
        This is called once per engine loop cycle so win/loss is always recorded.
        """
        closed: list[TradeRecord] = []
        positions = self.adapter.get_open_positions()
        if not positions:
            return closed

        account = self.adapter.get_account_info()
        balance = getattr(account, "balance", 0.0) if account else 0.0
        equity = getattr(account, "equity", 0.0) if account else 0.0

        for pos in positions:
            ticket = pos.get("ticket")
            symbol = pos.get("symbol", "")
            profit = float(pos.get("profit", 0.0))
            sl = float(pos.get("sl", 0.0))
            tp = float(pos.get("tp", 0.0))
            current = float(pos.get("price_current", 0.0))
            pos_type = pos.get("type", 0)
            is_buy = pos_type == 0  # ORDER_TYPE_BUY

            # Detect SL/TP hit: current price touched or crossed the level
            sl_hit = (is_buy and current <= sl) or (not is_buy and current >= sl)
            tp_hit = (is_buy and current >= tp) or (not is_buy and current <= tp)

            if not (sl_hit or tp_hit):
                continue

            try:
                close_result = self.adapter.close_position(ticket)
            except Exception as exc:
                logger.error("Close position #%s failed: %s", ticket, exc)
                continue

            # Build a partial TradeRecord from what we know
            entry = float(pos.get("price_open", 0.0))
            record = TradeRecord(
                timestamp_open=datetime.fromtimestamp(
                    float(pos.get("time", 0))
                ),
                timestamp_close=datetime.now(),
                strategy=self._comment_to_strategy(pos.get("comment", "")),
                asset_class="",
                symbol=symbol,
                timeframe="",
                side="BUY" if is_buy else "SELL",
                entry_price=entry,
                exit_price=close_result.get("price", current),
                sl=sl,
                tp=tp,
                lot_size=float(pos.get("volume", 0.0)),
                pnl_usd=round(profit, 2),
                commission=0.0,
                balance_after=round(balance, 2),
                ticket=ticket,
                notes=f"Closed {'SL' if sl_hit else 'TP'}",
            )
            self.csv.log_trade(record)
            closed.append(record)
            logger.info(
                "Closed #%s %s pnl=%.2f balance=%.2f (new balance)",
                ticket, symbol, profit, balance,
            )

        return closed

    def _validate_signal(self, signal: Signal) -> bool:
        if signal.side == Side.HOLD:
            return False
        if signal.confidence < 0.3:
            return False
        if RISK.min_risk_reward > 0:
            rr = abs(signal.tp - signal.entry) / abs(signal.entry - signal.sl)
            if rr < RISK.min_risk_reward:
                logger.info(
                    "R:R %.2f below minimum %.2f — rejected",
                    rr, RISK.min_risk_reward,
                )
                return False
        return True

    @staticmethod
    def _comment_to_strategy(comment: str) -> str:
        """Extract strategy name from 'StrategyName|asset|tf' comment."""
        parts = (comment or "").split("|")
        return parts[0] if parts else comment
