"""Porta do broker + ACL sobre a API oficial MetaTrader5 (somente Windows)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from engine.config.settings import MT5Settings
from engine.domain.shared.types import Bar


#+------------------------------------------------------------------+
#| Tipos de domínio (ACL)                                           |
#+------------------------------------------------------------------+
@dataclass(frozen=True, slots=True)
class AccountInfo:
    login: int
    server: str
    balance: float
    currency: str


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    name: str
    point: float
    digits: int
    lots_min: float
    lots_max: float
    lots_step: float
    tick_size: float
    tick_value: float


@dataclass(frozen=True, slots=True)
class TickInfo:
    ask: float
    bid: float
    time: datetime


@dataclass(frozen=True, slots=True)
class PositionInfo:
    ticket: int
    symbol: str
    is_buy: bool
    volume: float
    price_open: float
    price_current: float
    stop_loss: float
    take_profit: float
    magic: int
    comment: str
    time: datetime


@dataclass(frozen=True, slots=True)
class OrderInfo:
    ticket: int
    symbol: str
    is_buy: bool
    is_limit: bool
    volume: float
    price: float
    stop_loss: float
    take_profit: float
    magic: int
    comment: str
    time: datetime


@dataclass(frozen=True, slots=True)
class DealInfo:
    ticket: int
    order_ticket: int
    position_ticket: int
    symbol: str
    is_buy: bool
    volume: float
    price: float
    is_entry: bool
    magic: int
    comment: str
    time: datetime
    reason: int


@dataclass(frozen=True, slots=True)
class OrderRequest:
    symbol: str
    is_buy: bool
    volume: float
    price: float
    stop_loss: float = 0.0
    take_profit: float = 0.0
    is_limit: bool = True
    is_stop: bool = False
    comment: str = ""
    magic: int = 0


@dataclass(frozen=True, slots=True)
class OrderResult:
    retcode: int
    order_ticket: int
    deal_ticket: int
    message: str

    @property
    def is_ok(self) -> bool:
        return self.retcode == 10009


#+------------------------------------------------------------------+
#| Protocol                                                         |
#+------------------------------------------------------------------+
class BrokerGateway(Protocol):
    def connect(self) -> None: ...
    def shutdown(self) -> None: ...
    def account(self) -> AccountInfo: ...
    def symbol_info(self, symbol: str) -> SymbolInfo: ...
    def symbol_info_tick(self, symbol: str) -> TickInfo: ...
    def closed_bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]: ...
    def place_order(self, req: OrderRequest) -> OrderResult: ...
    def cancel_order(self, ticket: int) -> OrderResult: ...
    def modify_position(
        self, ticket: int, *, stop_loss: float, take_profit: float
    ) -> OrderResult: ...
    def close_position(self, ticket: int) -> OrderResult: ...
    def positions(self, symbol: str | None = None) -> list[PositionInfo]: ...
    def orders(self, symbol: str | None = None) -> list[OrderInfo]: ...
    def history_deals(
        self, since: datetime, *, symbol: str | None = None, magic: int | None = None
    ) -> list[DealInfo]: ...


class MT5NotAvailableError(RuntimeError):
    pass


#+------------------------------------------------------------------+
#| Adapter real                                                     |
#+------------------------------------------------------------------+
_TF_NAMES = {
    "M1": "TIMEFRAME_M1", "M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30", "H1": "TIMEFRAME_H1",
}

RETCODE_DONE = 10009


class RealMT5Gateway:
    def __init__(self, cfg: MT5Settings) -> None:
        self._cfg = cfg
        self._mt5 = None

    def connect(self) -> None:
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as exc:
            raise MT5NotAvailableError(
                "Pacote MetaTrader5 indisponivel nesta maquina."
            ) from exc

        kwargs = {}
        if self._cfg.terminal_path:
            kwargs["path"] = self._cfg.terminal_path
        if not mt5.initialize(**kwargs):
            raise MT5NotAvailableError(f"mt5.initialize falhou: {mt5.last_error()}")

        if self._cfg.login:
            if not mt5.login(self._cfg.login, self._cfg.password, self._cfg.server):
                raise MT5NotAvailableError(f"mt5.login falhou: {mt5.last_error()}")

        if not mt5.symbol_select(self._cfg.symbol, True):
            raise MT5NotAvailableError(f"symbol_select({self._cfg.symbol}) falhou")

        self._mt5 = mt5

    def shutdown(self) -> None:
        if self._mt5 is not None:
            self._mt5.shutdown()
            self._mt5 = None

    def account(self) -> AccountInfo:
        ai = self._mt5.account_info()
        if ai is None:
            raise MT5NotAvailableError(f"account_info retornou None: {self._mt5.last_error()}")
        return AccountInfo(
            login=ai.login, server=ai.server,
            balance=ai.balance, currency=ai.currency,
        )

    def symbol_info(self, symbol: str) -> SymbolInfo:
        si = self._mt5.symbol_info(symbol)
        if si is None:
            raise MT5NotAvailableError(f"symbol_info({symbol}) retornou None")
        return SymbolInfo(
            name=si.name, point=si.point, digits=si.digits,
            lots_min=si.volume_min, lots_max=si.volume_max, lots_step=si.volume_step,
            tick_size=si.trade_tick_size, tick_value=si.trade_tick_value,
        )

    def symbol_info_tick(self, symbol: str) -> TickInfo:
        tick = self._mt5.symbol_info_tick(symbol)
        if tick is None:
            raise MT5NotAvailableError(f"symbol_info_tick({symbol}) retornou None")
        return TickInfo(
            ask=float(tick.ask), bid=float(tick.bid),
            time=datetime.fromtimestamp(int(tick.time), tz=timezone.utc),
        )

    def closed_bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        tf = getattr(self._mt5, _TF_NAMES[timeframe])
        rates = self._mt5.copy_rates_from_pos(symbol, tf, 1, count)
        if rates is None:
            return []
        return [
            Bar(
                time=datetime.fromtimestamp(int(r["time"]), tz=timezone.utc),
                open=float(r["open"]), high=float(r["high"]),
                low=float(r["low"]), close=float(r["close"]),
                tick_volume=float(r["tick_volume"]), real_volume=float(r["real_volume"]),
            )
            for r in rates
        ]

    def place_order(self, req: OrderRequest) -> OrderResult:
        mt5 = self._mt5
        if req.is_stop:
            order_type = mt5.ORDER_TYPE_BUY_STOP if req.is_buy else mt5.ORDER_TYPE_SELL_STOP
            action = mt5.TRADE_ACTION_PENDING
        elif req.is_limit:
            order_type = mt5.ORDER_TYPE_BUY_LIMIT if req.is_buy else mt5.ORDER_TYPE_SELL_LIMIT
            action = mt5.TRADE_ACTION_PENDING
        else:
            order_type = mt5.ORDER_TYPE_BUY if req.is_buy else mt5.ORDER_TYPE_SELL
            action = mt5.TRADE_ACTION_DEAL

        request = {
            "action": action, "symbol": req.symbol, "volume": float(req.volume),
            "type": order_type, "price": float(req.price), "sl": float(req.stop_loss),
            "tp": float(req.take_profit), "deviation": 10, "magic": int(req.magic),
            "comment": req.comment, "type_time": mt5.ORDER_TIME_DAY,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            return OrderResult(-1, 0, 0, f"order_send retornou None: {mt5.last_error()}")
        return OrderResult(
            retcode=int(result.retcode), order_ticket=int(result.order),
            deal_ticket=int(result.deal), message=result.comment or "",
        )

    def cancel_order(self, ticket: int) -> OrderResult:
        mt5 = self._mt5
        request = {"action": mt5.TRADE_ACTION_REMOVE, "order": ticket}
        result = mt5.order_send(request)
        if result is None:
            return OrderResult(-1, 0, 0, f"cancel_order None: {mt5.last_error()}")
        return OrderResult(
            int(result.retcode), int(result.order), int(result.deal), result.comment or "",
        )

    def modify_position(
        self, ticket: int, *, stop_loss: float, take_profit: float
    ) -> OrderResult:
        mt5 = self._mt5
        position = self._find_position(ticket)
        if position is None:
            return OrderResult(-1, 0, 0, f"posição {ticket} não encontrada")
        request = {
            "action": mt5.TRADE_ACTION_SLTP, "position": ticket, "symbol": position.symbol,
            "sl": float(stop_loss), "tp": float(take_profit),
        }
        result = mt5.order_send(request)
        if result is None:
            return OrderResult(-1, 0, 0, f"modify_position None: {mt5.last_error()}")
        return OrderResult(
            int(result.retcode), int(result.order), int(result.deal), result.comment or "",
        )

    def close_position(self, ticket: int) -> OrderResult:
        mt5 = self._mt5
        position = self._find_position(ticket)
        if position is None:
            return OrderResult(-1, 0, 0, f"posição {ticket} não encontrada")
        is_buy_close = not position.is_buy
        tick = mt5.symbol_info_tick(position.symbol)
        price = tick.bid if is_buy_close else tick.ask
        request = {
            "action": mt5.TRADE_ACTION_DEAL, "position": ticket, "symbol": position.symbol,
            "volume": position.volume, "type": mt5.ORDER_TYPE_SELL if is_buy_close else mt5.ORDER_TYPE_BUY,
            "price": float(price), "deviation": 10, "magic": position.magic,
            "comment": "close", "type_time": mt5.ORDER_TIME_DAY, "type_filling": mt5.ORDER_FILLING_IOC,
        }
        result = mt5.order_send(request)
        if result is None:
            return OrderResult(-1, 0, 0, f"close_position None: {mt5.last_error()}")
        return OrderResult(
            int(result.retcode), int(result.order), int(result.deal), result.comment or "",
        )

    def _find_position(self, ticket: int) -> PositionInfo | None:
        for p in self.positions():
            if p.ticket == ticket:
                return p
        return None

    def positions(self, symbol: str | None = None) -> list[PositionInfo]:
        mt5 = self._mt5
        raw = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if raw is None:
            return []
        return [
            PositionInfo(
                ticket=int(p.ticket), symbol=p.symbol, is_buy=(p.type == mt5.POSITION_TYPE_BUY),
                volume=float(p.volume), price_open=float(p.price_open), price_current=float(p.price_current),
                stop_loss=float(p.sl), take_profit=float(p.tp), magic=int(p.magic), comment=p.comment,
                time=datetime.fromtimestamp(int(p.time), tz=timezone.utc),
            )
            for p in raw
        ]

    def orders(self, symbol: str | None = None) -> list[OrderInfo]:
        mt5 = self._mt5
        raw = mt5.orders_get(symbol=symbol) if symbol else mt5.orders_get()
        if raw is None:
            return []
        limit_types = {mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_SELL_LIMIT}
        buy_types = {mt5.ORDER_TYPE_BUY, mt5.ORDER_TYPE_BUY_LIMIT, mt5.ORDER_TYPE_BUY_STOP}
        return [
            OrderInfo(
                ticket=int(o.ticket), symbol=o.symbol, is_buy=(o.type in buy_types),
                is_limit=(o.type in limit_types), volume=float(o.volume_current), price=float(o.price_open),
                stop_loss=float(o.sl), take_profit=float(o.tp), magic=int(o.magic), comment=o.comment,
                time=datetime.fromtimestamp(int(o.time_setup), tz=timezone.utc),
            )
            for o in raw
        ]

    def history_deals(
        self, since: datetime, *, symbol: str | None = None, magic: int | None = None
    ) -> list[DealInfo]:
        mt5 = self._mt5
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        raw = mt5.history_deals_get(since, now, group=None)
        if raw is None:
            return []
        out: list[DealInfo] = []
        for d in raw:
            if symbol and d.symbol != symbol:
                continue
            if magic is not None and int(d.magic) != magic:
                continue
            out.append(
                DealInfo(
                    ticket=int(d.ticket), order_ticket=int(d.order), position_ticket=int(d.position_id),
                    symbol=d.symbol, is_buy=(d.type == mt5.DEAL_TYPE_BUY), volume=float(d.volume),
                    price=float(d.price), is_entry=(d.entry == mt5.DEAL_ENTRY_IN), magic=int(d.magic),
                    comment=d.comment, time=datetime.fromtimestamp(int(d.time), tz=timezone.utc),
                    reason=int(d.reason),
                )
            )
        return out