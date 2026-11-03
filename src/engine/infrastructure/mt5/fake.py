"""Gateway FAKE determinístico — desenvolvimento/testes sem terminal.

Simula fills imediatos (market) ou preenchimento por preço (limit).
O book interno é simples: aceita qualquer ordem, marca como executada.
Suficiente para testar o RealExecutor (F3a) + run/shadow (F3d/F4) sem MT5.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from engine.domain.shared.types import Bar
from engine.infrastructure.mt5.gateway import (
    AccountInfo,
    DealInfo,
    OrderInfo,
    OrderRequest,
    OrderResult,
    PositionInfo,
    SymbolInfo,
    TickInfo,
)


RETCODE_DONE = 10009


@dataclass
class _OpenPosition:
    ticket: int
    symbol: str
    is_buy: bool
    volume: float
    price_open: float
    stop_loss: float
    take_profit: float
    magic: int
    comment: str
    time: datetime


@dataclass
class _PendingOrder:
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


class FakeGateway:
    def __init__(self, seed: int = 42, balance: float = 100_000.0) -> None:
        self._rng = random.Random(seed)
        self._balance = balance
        self._next_ticket = 1000
        self._positions: dict[int, _OpenPosition] = {}
        self._orders: dict[int, _PendingOrder] = {}
        self._deals: list[DealInfo] = []
        self._symbol = "WIN$N"
        self._symbol_info = SymbolInfo(
            name=self._symbol,
            point=1.0,
            digits=0,
            lots_min=1.0,
            lots_max=100.0,
            lots_step=1.0,
            tick_size=1.0,
            tick_value=1.0,
        )
        self._last_ask = 171_000.0
        self._last_bid = 171_000.0

    # --- Ciclo de vida ---
    def connect(self) -> None: ...
    def shutdown(self) -> None: ...

    # --- Leitura ---
    def account(self) -> AccountInfo:
        return AccountInfo(
            login=0, server="FAKE", balance=self._balance, currency="BRL",
        )

    def symbol_info(self, symbol: str) -> SymbolInfo:
        return self._symbol_info

    def symbol_info_tick(self, symbol: str) -> TickInfo:
        # Preço sintético: 171000 ± jitter determinístico (por seed)
        jitter = self._rng.uniform(-50.0, 50.0)
        mid = 171_000.0 + jitter
        self._last_ask = mid + 5.0
        self._last_bid = mid - 5.0
        return TickInfo(
            ask=self._last_ask,
            bid=self._last_bid,
            time=datetime.now(tz=timezone.utc),
        )

    def closed_bars(self, symbol: str, timeframe: str, count: int) -> list[Bar]:
        bars: list[Bar] = []
        t = datetime.now(tz=timezone.utc).replace(second=0, microsecond=0)
        price = 171_000.0
        for i in range(count):
            o = price
            h = o + self._rng.uniform(20, 120)
            l = o - self._rng.uniform(20, 120)
            c = self._rng.uniform(l, h)
            vol = self._rng.gauss(2000, 600)
            if i == count - 1:
                vol = 15_000
            bars.append(Bar(
                time=t - timedelta(minutes=count - i), open=o, high=h, low=l,
                close=c, tick_volume=max(vol, 1.0), real_volume=0.0,
            ))
            price = c
        return bars

    # --- Execução ---
    def place_order(self, req: OrderRequest) -> OrderResult:
        ticket = self._next_ticket
        self._next_ticket += 1

        # Stop (BuyStop/SellStop): registra como ordem pendente, NÃO abre posição.
        # Detecta pelo comment conter "sl" ou "stop" (o RealExecutor usa
        # "engine_reentry_sl" para o SL do reforço).
        c = (req.comment or "").lower()
        is_stop = (
            not req.is_limit
            and ("stop" in c or "sl" in c)
        )

        if req.is_limit or is_stop:
            order = _PendingOrder(
                ticket=ticket, symbol=req.symbol, is_buy=req.is_buy,
                is_limit=req.is_limit,
                volume=req.volume, price=req.price,
                stop_loss=req.stop_loss, take_profit=req.take_profit,
                magic=req.magic, comment=req.comment,
                time=datetime.now(tz=timezone.utc),
            )
            self._orders[ticket] = order
            kind = "limit" if req.is_limit else "stop"
            return OrderResult(RETCODE_DONE, ticket, 0, f"{kind} accepted")

        # Market: abre posição
        pos = _OpenPosition(
            ticket=ticket, symbol=req.symbol, is_buy=req.is_buy,
            volume=req.volume, price_open=req.price,
            stop_loss=req.stop_loss, take_profit=req.take_profit,
            magic=req.magic, comment=req.comment,
            time=datetime.now(tz=timezone.utc),
        )
        self._positions[ticket] = pos
        self._deals.append(DealInfo(
            ticket=ticket, order_ticket=ticket, position_ticket=ticket,
            symbol=req.symbol, is_buy=req.is_buy, volume=req.volume,
            price=req.price, is_entry=True, magic=req.magic,
            comment=req.comment, time=pos.time, reason=0,
        ))
        return OrderResult(RETCODE_DONE, ticket, ticket, "market filled")

    def cancel_order(self, ticket: int) -> OrderResult:
        if ticket not in self._orders:
            return OrderResult(-1, 0, 0, f"order {ticket} não encontrada")
        del self._orders[ticket]
        return OrderResult(RETCODE_DONE, ticket, 0, "order cancelled")

    def modify_position(
        self, ticket: int, *, stop_loss: float, take_profit: float
    ) -> OrderResult:
        pos = self._positions.get(ticket)
        if pos is None:
            return OrderResult(-1, 0, 0, f"posição {ticket} não encontrada")
        pos.stop_loss = stop_loss
        pos.take_profit = take_profit
        return OrderResult(RETCODE_DONE, 0, 0, "position modified")

    def close_position(self, ticket: int) -> OrderResult:
        pos = self._positions.pop(ticket, None)
        if pos is None:
            return OrderResult(-1, 0, 0, f"posição {ticket} não encontrada")
        self._deals.append(DealInfo(
            ticket=self._next_ticket, order_ticket=self._next_ticket,
            position_ticket=ticket, symbol=pos.symbol, is_buy=pos.is_buy,
            volume=pos.volume, price=pos.price_open, is_entry=False,
            magic=pos.magic, comment="close",
            time=datetime.now(tz=timezone.utc), reason=0,
        ))
        self._next_ticket += 1
        return OrderResult(RETCODE_DONE, 0, 0, "position closed")

    # --- Inspeção ---
    def positions(self, symbol: str | None = None) -> list[PositionInfo]:
        return [
            PositionInfo(
                ticket=p.ticket, symbol=p.symbol, is_buy=p.is_buy,
                volume=p.volume, price_open=p.price_open,
                price_current=p.price_open,
                stop_loss=p.stop_loss, take_profit=p.take_profit,
                magic=p.magic, comment=p.comment, time=p.time,
            )
            for p in self._positions.values()
            if symbol is None or p.symbol == symbol
        ]

    def orders(self, symbol: str | None = None) -> list[OrderInfo]:
        return [
            OrderInfo(
                ticket=o.ticket, symbol=o.symbol, is_buy=o.is_buy,
                is_limit=o.is_limit, volume=o.volume, price=o.price,
                stop_loss=o.stop_loss, take_profit=o.take_profit,
                magic=o.magic, comment=o.comment, time=o.time,
            )
            for o in self._orders.values()
            if symbol is None or o.symbol == symbol
        ]

    def history_deals(
        self, since: datetime, *, symbol: str | None = None, magic: int | None = None
    ) -> list[DealInfo]:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        out = []
        for d in self._deals:
            if d.time < since:
                continue
            if symbol and d.symbol != symbol:
                continue
            if magic is not None and d.magic != magic:
                continue
            out.append(d)
        return out

    # --- Hooks de teste (não fazem parte do Protocol) ---
    def _force_fill_pending(self, ticket: int) -> None:
        """Preenche manualmente uma ordem pendente (para testes)."""
        order = self._orders.pop(ticket, None)
        if order is None:
            return
        pos = _OpenPosition(
            ticket=ticket, symbol=order.symbol, is_buy=order.is_buy,
            volume=order.volume, price_open=order.price,
            stop_loss=order.stop_loss, take_profit=order.take_profit,
            magic=order.magic, comment=order.comment,
            time=datetime.now(tz=timezone.utc),
        )
        self._positions[ticket] = pos