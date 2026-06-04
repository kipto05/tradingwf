"""Thin real-MT5 adapter wrapping the MetaTrader 5 Python SDK."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("mt5_adapter")


@dataclass
class MT5Config:
    path: str = ""
    login: int = 0
    password: str = ""
    server: str = ""
    timeout: int = 10_000
    deviation: int = 20


class MT5Error(Exception):
    pass


class MT5Adapter:
    def __init__(self, config: Optional[MT5Config] = None):
        self.cfg = config or MT5Config()
        self._connected: bool = False

    def connect(self) -> bool:
        import metatrader5 as mt5

        init_kwargs: dict = {"timeout": self.cfg.timeout}
        if self.cfg.path:
            init_kwargs["path"] = self.cfg.path
        if self.cfg.login:
            init_kwargs["login"] = self.cfg.login
        if self.cfg.password:
            init_kwargs["password"] = self.cfg.password
        if self.cfg.server:
            init_kwargs["server"] = self.cfg.server

        ok = mt5.initialize(**init_kwargs)
        if not ok:
            err = mt5.last_error()
            logger.error("MT5 initialize failed: %s", err)
            return False

        acct = mt5.account_info()
        if acct is not None:
            self._connected = True
            logger.info(
                "Connected account #%d (%s) balance=%.2f equity=%.2f",
                acct.login, acct.server, acct.balance, acct.equity,
            )
            self._autoselect_symbols()
            return True

        logger.error("MT5 init: account_info() returned None")
        return False

    def _autoselect_symbols(self):
        """Mark known symbols as visible so OHLC data is available."""
        import metatrader5 as mt5
        for sym in (
            "XAUUSD", "XAUUSD.m", "XAGUSD", "XAGUSD.m",
            "BTCUSD", "BTCUSD.m", "ETHUSD", "ETHUSD.m",
            "EURUSD", "EURUSD.m", "GBPUSD", "GBPUSD.m",
            "USDJPY", "USDJPY.m", "AUDUSD", "AUDUSD.m",
            "USOIL", "USOIL.m", "UKOIL", "UKOIL.m",
            "AAPL", "AAPL.m", "TSLA", "TSLA.m", "NVDA", "NVDA.m",
            "MSFT", "MSFT.m", "AMZN", "AMZN.m", "GOOGL", "GOOGL.m",
        ):
            try:
                mt5.symbol_select(sym, True)
            except Exception:
                pass

    def disconnect(self) -> None:
        import metatrader5 as mt5
        mt5.shutdown()
        self._connected = False
        logger.info("Disconnected from MT5")

    def _hard_reinit(self) -> bool:
        """Drop and re-create the MT5 IPC connection."""
        import metatrader5 as mt5
        try:
            mt5.shutdown()
        except Exception:
            pass
        return self.connect()

    def check_connection(self) -> bool:
        if not self._connected:
            return self.connect()
        import metatrader5 as mt5
        err = mt5.last_error()
        if err and err[0] in (-10004, -10005):
            logger.warning("IPC broken (%s) — hard re-init", err)
            self._connected = False
            return self._hard_reinit()
        return True

    # ---- market data ----

    @classmethod
    def _resolve_tf(cls, timeframe):
        import metatrader5 as mt5
        if hasattr(timeframe, "value"):
            timeframe = timeframe.value
        if isinstance(timeframe, int):
            return timeframe
        key = str(timeframe).upper()
        _TF_MAP = {
            "M1": mt5.TIMEFRAME_M1, "M2": mt5.TIMEFRAME_M2,
            "M3": mt5.TIMEFRAME_M3, "M5": mt5.TIMEFRAME_M5,
            "M10": mt5.TIMEFRAME_M10, "M12": mt5.TIMEFRAME_M12,
            "M15": mt5.TIMEFRAME_M15, "M20": mt5.TIMEFRAME_M20,
            "M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1,
            "H2": mt5.TIMEFRAME_H2, "H3": mt5.TIMEFRAME_H3,
            "H4": mt5.TIMEFRAME_H4, "H6": mt5.TIMEFRAME_H6,
            "H8": mt5.TIMEFRAME_H8, "H12": mt5.TIMEFRAME_H12,
            "D1": mt5.TIMEFRAME_D1, "W1": mt5.TIMEFRAME_W1,
            "MN1": mt5.TIMEFRAME_MN1,
        }
        return _TF_MAP.get(key, timeframe)

    def get_ohlc(self, symbol, timeframe, n_bars=500):
        import metatrader5 as mt5
        import pandas as pd
        if not self._connected:
            raise MT5Error("Not connected — call connect() first")
        tf = self._resolve_tf(timeframe)
        rates = mt5.copy_rates_from_pos(symbol, tf, 0, n_bars)
        if rates is None or len(rates) == 0:
            logger.warning("No OHLC data for %s tf=%s", symbol, timeframe)
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(rates)
        df.rename(
            columns={
                "time": "time", "open": "open", "high": "high",
                "low": "low", "close": "close", "tick_volume": "volume",
            },
            inplace=True,
        )
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    def get_current_price(self, symbol: str):
        import metatrader5 as mt5
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5Error(f"Cannot get tick for {symbol}: {mt5.last_error()}")
        return tick.bid, tick.ask

    def get_symbol_info(self, symbol: str) -> dict:
        import metatrader5 as mt5
        info = mt5.symbol_info(symbol)
        if info is None:
            raise MT5Error(f"Cannot get symbol info for {symbol}: {mt5.last_error()}")
        if hasattr(info, "_asdict"):
            d = info._asdict()
            if "contract_size" not in d or not d.get("contract_size"):
                d["contract_size"] = d.get("trade_contract_size", 100000)
            if "point" not in d:
                d["point"] = 10 ** (-d.get("digits", 5))
            return d
        return {
            k: getattr(info, k)
            for k in (
                "point", "digits", "volume_min", "volume_max", "volume_step",
                "trade_contract_size", "trade_tick_value", "trade_tick_size",
                "margin_initial", "margin_maintenance", "trade_mode",
            )
            if hasattr(info, k)
        }

    # ---- trading ----

    def place_order(self, symbol, side, lot, sl, tp, comment="", entry=0.0):
        import metatrader5 as mt5
        if not self._connected:
            raise MT5Error("Not connected — call connect() first")
        order_type = mt5.ORDER_TYPE_BUY if side.upper() == "BUY" else mt5.ORDER_TYPE_SELL
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5Error(f"Cannot get tick for {symbol}: {mt5.last_error()}")
        price = tick.ask if side.upper() == "BUY" else tick.bid
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "type": order_type,
            "volume": lot,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": self.cfg.deviation,
            "comment": comment[:32],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        result = mt5.order_send(req)
        if result is None:
            raise MT5Error(f"Order send returned None: {mt5.last_error()}")
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise MT5Error(f"Order failed [{result.retcode}]: {result.comment}")
        logger.info(
            "Order placed: %s %s %.4f lots @ %.5f ticket=%s",
            side, symbol, lot, price, result.order,
        )
        return {
            "order": result.order, "price": price,
            "volume": lot, "retcode": result.retcode, "comment": result.comment,
        }

    def close_position(self, ticket: int, lot=None):
        """Close an open position by ticket. Returns {retcode, price, pnl}."""
        import metatrader5 as mt5
        positions = mt5.positions_get()
        if positions is None:
            raise MT5Error(f"positions_get failed: {mt5.last_error()}")
        target = None
        for p in positions:
            if p.ticket == ticket:
                target = p
                break
        if target is None:
            raise MT5Error(f"Position #{ticket} not found")

        order_type = (
            mt5.ORDER_TYPE_SELL if target.type == mt5.ORDER_TYPE_BUY
            else mt5.ORDER_TYPE_BUY
        )
        tick = mt5.symbol_info_tick(target.symbol)
        if tick is None:
            raise MT5Error(f"Cannot get tick for {target.symbol}: {mt5.last_error()}")
        price = tick.bid if target.type == mt5.ORDER_TYPE_BUY else tick.ask
        close_vol = lot if lot else target.volume
        req = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": target.symbol,
            "type": order_type,
            "volume": close_vol,
            "price": price,
            "position": ticket,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_RETURN,
        }
        result = mt5.order_send(req)
        if result is None:
            raise MT5Error(f"Close order returned None: {mt5.last_error()}")
        pnl = target.profit
        logger.info("Closed position #%d pnl=%.2f", ticket, pnl)
        return {"retcode": result.retcode, "price": price, "pnl": pnl}

    def get_open_positions(self) -> list[dict]:
        """Return open positions as plain dicts from the live terminal."""
        import metatrader5 as mt5
        raw = mt5.positions_get()
        if raw is None:
            logger.warning("positions_get returned None: %s", mt5.last_error())
            return []
        return [p._asdict() for p in raw]

    def get_account_info(self):
        import metatrader5 as mt5
        return mt5.account_info()
