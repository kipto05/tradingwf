# Trading Workflow Dashboard — To-Do List

**Created:** 2025-06-05  
**Last updated:** 2025-06-05  
**Status:** Pending (for @dev)

---

## Backtesting Lab

### BT1. Fix "MT5Adapter has no attribute get_rates"
- **Issue:** Clicking "Run Backtest" throws `AttributeError: 'MT5Adapter' has no attribute 'get_rates'`
- **Fix:** Ensure `MT5Adapter` implements `get_rates(symbol, timeframe, n_bars)` or the backtester is calling the correct method name (`get_historical_data`, `get_bars`, etc.)
- **Owner:** @dev

### BT2. Persist backtest results to CSV file
- **Requirement:** Every backtest run must write results to a CSV file on disk
  - Columns: `strategy, symbol, timeframe, total_trades, win_rate, net_pnl, sharpe_approx, profit_factor, max_drawdown_pct, avg_win, avg_loss, timestamp`
  - File: `results/backtest_results.csv` (append mode, create dir if missing)
- **Owner:** @dev

### BT3. Display persistent backtest results on dashboard
- **Requirement:** The Backtesting tab must show all past backtest runs (from CSV), not just the most recent
  - Add a results table/list widget in the Backtest tab
  - Re-populate from `backtest_results.csv` on dashboard load
- **Owner:** @dev

### BT4. Equity curve on clicking a backtested strategy
- **Requirement:** When user clicks a strategy from the backtested list, show:
  - An equity curve chart (Plotly) for that backtest
  - Stats below: total trades, win rate, net PnL, max drawdown, Sharpe approx, profit factor
  - Use the `equity_curve` field from `BacktestResult`
- **Owner:** @dev

### BT5. Backtesting lab logical correctness & thorough check
- **Requirement:** Full audit of the backtesting pipeline:
  - Verify `run_backtest()` in `execution/backtester.py` correctly handles all strategy types
  - Check `BacktestResult` dataclass fits: `strategy`, `symbol`, `timeframe`, `total_trades`, `win_rate`, `net_pnl`, `equity_curve`, `max_drawdown_pct`, `sharpe_approx`, `profit_factor`, `avg_win`, `avg_loss`
  - Verify the `/api/backtest` endpoint correctly calls and returns results
  - Check timeframe vs bars calculation in backtester
  - Verify fill-model assumptions (close-of-bar vs next-bar open)
  - Edge cases: zero trades, single trade, all losses, all wins
- **Owner:** @dev

---

## Dashboard Cards & Overview

### D1. Fix open trades count / live MT5 positions
- **Issue:** Open trade count doesn't update; shows stale value or 0
- **Fix:** Ensure `/api/open-positions` endpoint reads live MT5 positions via `MT5Adapter.get_open_positions()`. Handle reconnection if MT5 is disconnected. Display correct count in the status bar badge.
- **Owner:** @dev

### D2. Current balance card (8th card)
- **Requirement:** Add a "Current Balance" card alongside the existing 7 stats cards
  - Source: `MT5Adapter.get_account_info()['balance']` or fallback from trades.csv/heartbeat
  - Position: Between "Net Profit" and "Win/Loss" cards (or as shown in design)
- **Owner:** @dev

### D3. Current drawdown card (8th pair: replace Max Balance)
- **Requirement:** Replace the "Max Balance" card with two cards:
  1. **Current Drawdown ($)** — absolute drawdown from peak balance: `peak_balance - current_balance`
  2. **Current Drawdown (%)** — percentage: `(peak_balance - current_balance) / peak_balance * 100`
  - Peak balance tracked from trade history or computed from balance history
  - Total cards: 8 (Trades, Win Rate, Net PnL, **Current Balance**, **Drawdown $**, **Drawdown %**, Wins/Losses, Avg Win/Loss)
- **Owner:** @dev

---

## Recent Trades Widget

### RT1. Fix recent trades widget text
- **Issue:** Widget subtitle says "Last 25 trades from trades.csv" — should reflect live data source
- **Fix:** Update subtitle to say "Last 25 trades" or dynamically show the actual source (live MT5 / backtest / CSV)
- **Owner:** @dev

### RT2. Verify trade data correctness
- **Optional:** Ensure the widget shows correct trades (not stale, correct order — most recent first)
- **Owner:** @dev

---

## Strategy Toggle (Strategy Manager)

### ST1. Fix non-working strategy toggles
- **Issue:** Some strategy toggles in the Strategies tab don't work (click to enable/disable doesn't persist or doesn't trigger state change)
- **Fix:** Debug:
  - Check `/api/strategies/{name}/toggle` receives correct `enabled` parameter
  - Check strategy state persistence in `strategies/registry.py` (`set_state`, `_save_states`)
  - Check `_stratEnabled` module-level cache is updated after toggle
  - Check `renderStrategyTable()` re-renders correctly
  - Check that toggled strategies are included/excluded from `get_registered()` / `get_enabled()` filtering
- **Owner:** @dev

### ST2. Verify toggle persistence across restarts
- **Requirement:** Toggled strategies should remain on/off after server restart
  - State saved to `config/strategy_states.json`
  - On startup, `_load_states()` reads and applies the saved states
- **Owner:** @dev

---

## Charts & Analytics

### CA1. Better formatting for "no trades for strategy" message
- **Requirement:** When a strategy has no trades in the charts tab:
  - The "no trades" message should be formatted more prominently (larger font, centered, styled card)
  - Current implementation is a simple text placeholder
- **Owner:** @dev

### CA2. Overlay zero-trade message on chart window
- **Requirement:** When there are no trades for a selected strategy:
  - Display the "no trades available" message AS AN OVERLAY on the chart area itself (where the chart would be)
  - Do NOT show an empty chart with a separate message below it
  - Effect: chart area is empty, but a styled overlay text says "No trades for [strategy] in selected period"
- **Owner:** @dev

---

## Summary

| ID | Task | Priority |
|----|------|----------|
| BT1 | Fix MT5Adapter.get_rates error | High | ✅ done ✅ done
| BT2 | Persist backtest results to CSV | High | ✅ done
| BT2.5 | Deduplication + multi-asset selector | High | ✅ done
| BT5 | Thorough backtesting lab audit | High |
| BT3 | Display persistent results on dashboard | High |
| BT4 | Equity curve on strategy click | High |
| D1 | Fix open trades count (live MT5) | High |
| D2 | Current balance card | Medium |
| D3 | Drawdown cards (replace Max Balance) | Medium |
| ST1 | Fix non-working strategy toggles | Medium |
| ST2 | Verify toggle persistence | Medium |
| RT1 | Fix recent trades widget text | Low |
| RT2 | Verify trade data correctness | Low |
| CA1 | Better "no trades" message formatting | Low |
| CA2 | Overlay zero-trade message on chart | Low |

**Total tasks:** 14
