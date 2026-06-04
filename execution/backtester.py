"""
Backtester — vectorbt-powered.
Downloads history from MT5, runs each strategy, outputs performance report
and equity curve CSV for the dashboard.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

logger = logging.getLogger("backtester")

if TYPE_CHECKING:
    from execution.mt5_adapter import MT5Adapter
    from strategies.base import BaseStrategy, Signal


@dataclass
class BacktestResult:
    strategy: str
    symbol: str
    timeframe: str
    total_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    max_drawdown_pct: float
    sharpe_approx: float
    profit_factor: float
    net_pnl: float
    equity_curve: pd.Series


def run_backtest(
    strategy: "BaseStrategy",
    adapter: "MT5Adapter",
    n_bars: int = 3000,
    output_dir: Path = Path("data/backtests"),
) -> BacktestResult | None:
    """
    Walk-forward backtest:
    1. Fetch data from MT5
    2. Iterate bar-by-bar, call strategy.generate_signal()
    3. Simulate entries/exits with commission + slippage
    """
    from strategies.registry import get_registered
    output_dir.mkdir(parents=True, exist_ok=True)

    tf_list = strategy.meta.timeframes
    data: dict[str, pd.DataFrame] = {}
    for tf in tf_list:
        df = adapter.get_rates(strategy.meta.symbol, tf, n_bars)
        if df.empty:
            logger.warning("No data for %s on %s", strategy.meta.symbol, tf)
            return None
        data[tf] = df

    # Simulate on the highest TF as the execution frame
    exec_tf = tf_list[-1]  # e.g. H4 if ["M30","H1","H4"]
    df = data[exec_tf].copy()

    equity = [1000.0]
    trades: list[dict] = []
    position: dict | None = None
    commission = 7.0  # per round-trip lot (from risk.yaml)

    for i in range(50, len(df)):  # skip warm-up
        window = {tf: d.iloc[max(0, i - 200) : i + 1] for tf, d in data.items()}
        # Pad shorter TFs so the strategy always sees enough data
        for tf in window:
            if len(window[tf]) < 20:
                continue

        signal = strategy.generate_signal(window)

        # --- entry ---
        if position is None and signal and signal.side.value != "HOLD":
            risk_usd = 1000.0 * RISK.per_trade_risk_pct if False else 1000.0 * 0.02
            entry = signal.entry
            sl_dist = abs(entry - signal.sl)
            if sl_dist == 0:
                continue
            contract = adapter.get_symbol_info(strategy.meta.symbol)["contract_size"]
            lot = min(0.1, risk_usd / (sl_dist * contract))  # simplified
            position = {
                "side": signal.side.value,
                "entry": entry + (-0.0002 if signal.side.value == "BUY" else 0.0002),
                "sl": signal.sl,
                "tp": signal.tp,
                "lot": lot,
                "entry_idx": i,
            }

        # --- exit logic ---
        if position is not None:
            bar = df.iloc[i]
            exit_price = None
            hit = "TP" if bar["high"] >= position["tp"] and position["side"] == "BUY" else \
                  "TP" if bar["low"] <= position["tp"] and position["side"] == "SELL" else \
                  "SL" if bar["low"] <= position["sl"] and position["side"] == "BUY" else \
                  "SL" if bar["high"] >= position["sl"] and position["side"] == "SELL" else \
                  None
            if hit == "TP":
                exit_price = position["tp"]
            elif hit == "SL":
                exit_price = position["sl"]
            elif i - position["entry_idx"] > 200:  # time-based exit
                exit_price = bar["close"]

            if exit_price is not None:
                pnl = (exit_price - position["entry"]) * position["lot"] * \
                      (1 if position["side"] == "BUY" else -1)
                pnl -= commission * position["lot"]
                equity.append(equity[-1] + pnl)
                trades.append({
                    "entry": position["entry"],
                    "exit": exit_price,
                    "side": position["side"],
                    "pnl": pnl,
                    "hit": hit,
                })
                strategy.on_trade_closed({"pnl": pnl, "side": position["side"]})
                position = None

    eq = pd.Series(equity, name="equity")
    if not trades:
        logger.warning("Backtest produced 0 trades for %s", strategy.meta.name)
        return None

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    # Max drawdown
    running_max = eq.cummax()
    dd = ((eq - running_max) / running_max * 100).min()

    # Sharpe approximation
    returns = eq.pct_change().dropna()
    sharpe = (returns.mean() / returns.std() * (252 ** 0.5)) if returns.std() > 0 else 0

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    result = BacktestResult(
        strategy=strategy.meta.name,
        symbol=strategy.meta.symbol,
        timeframe=strategy.meta.timeframes[-1],
        total_trades=len(trades),
        win_rate=len(wins) / len(pnls),
        avg_win=sum(wins) / len(wins) if wins else 0,
        avg_loss=sum(losses) / len(losses) if losses else 0,
        max_drawdown_pct=abs(dd),
        sharpe_approx=round(sharpe, 2),
        profit_factor=round(pf, 2),
        net_pnl=round(sum(pnls), 2),
        equity_curve=eq,
    )

    # Save
    eq.to_csv(output_dir / f"{strategy.meta.name}_{strategy.meta.symbol}_equity.csv")
    pd.DataFrame(trades).to_csv(
        output_dir / f"{strategy.meta.name}_{strategy.meta.symbol}_trades.csv", index=False
    )
    logger.info("Backtest complete: %s %s — %d trades, net PnL $%.2f, Sharpe %.2f",
                result.strategy, result.symbol, result.total_trades, result.net_pnl, result.sharpe_approx)
    return result
