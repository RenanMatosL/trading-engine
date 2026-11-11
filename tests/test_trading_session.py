"""Golden tests do TradingSession (escopo B + F3b)."""
from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest

from engine.application.trade_events import (
    DEAL_REASON_CLIENT,
    DEAL_REASON_SL,
    DEAL_REASON_TP,
    EntryFilled,
    PartialFilled,
    PositionClosed,
    StopLossHit,
    TakeProfitHit,
)
from engine.application.trading_session import TradingSession
from engine.config.presets import (
    DetectorParams,
    EntryParams,
    EntryLevelMode,
    SessionParams,
    StdDevV510Preset,
    TimeWindowParams,
)
from engine.domain.shared.types import Bar, MarketSnapshot
from engine.infrastructure.mt5.gateway import DealInfo

T0 = datetime(2026, 10, 29, 9, 0)
TICK = timedelta(minutes=1)


#+------------------------------------------------------------------+
#| Helpers gerais                                                    |
#+------------------------------------------------------------------+
def _bar(now: datetime, high: float, low: float, vol: float) -> Bar:
    return Bar(
        time=now, open=(high + low) / 2,
        high=high, low=low, close=(high + low) / 2,
        tick_volume=vol, real_volume=0.0,
    )


def _snap(ask: float, bid: float, now: datetime) -> MarketSnapshot:
    return MarketSnapshot(ask=ask, bid=bid, now=now)


def _preset(**overrides) -> StdDevV510Preset:
    base = {
        "name": "test",
        "strategy": "stddev_v510",
        "detector": DetectorParams(mute_open_min=0).model_dump(),
        "session": SessionParams(
            use_entry_block=False,
            window=TimeWindowParams(start=time(9, 0), end=time(17, 30)),
        ).model_dump(),
    }
    base.update(overrides)
    return StdDevV510Preset.model_validate(base)


#+------------------------------------------------------------------+
#| F2c — on_bar_closed (filtros)                                    |
#+------------------------------------------------------------------+
def test_bar_closed_cria_regiao_se_z_alto():
    sess = TradingSession(_preset())
    result = sess.on_bar_closed(
        bar=_bar(T0 + 10 * TICK, high=1000.0, low=900.0, vol=5000.0),
        zscore=5.0,
        now=T0 + 10 * TICK,
    )
    assert result.created is True
    assert len(sess.regions) == 1


def test_bar_closed_ignora_z_baixo():
    sess = TradingSession(_preset())
    result = sess.on_bar_closed(
        bar=_bar(T0 + 10 * TICK, high=1000.0, low=900.0, vol=5000.0),
        zscore=2.0,
        now=T0 + 10 * TICK,
    )
    assert result.created is False
    assert result.skipped_reason is not None
    assert "std_ref" in result.skipped_reason


def test_bar_closed_aplica_mute_open_min():
    preset = _preset()
    preset = StdDevV510Preset.model_validate({
        **preset.model_dump(mode="json"),
        "detector": {**preset.detector.model_dump(mode="json"), "mute_open_min": 10},
    })
    sess = TradingSession(preset)

    bar = _bar(T0 + 5 * TICK, high=1000.0, low=900.0, vol=5000.0)
    result = sess.on_bar_closed(bar=bar, zscore=5.0, now=T0 + 5 * TICK)
    assert result.created is False
    assert "mute_open" in (result.skipped_reason or "")

    bar2 = _bar(T0 + 15 * TICK, high=1000.0, low=900.0, vol=5000.0)
    result2 = sess.on_bar_closed(bar=bar2, zscore=5.0, now=T0 + 15 * TICK)
    assert result2.created is True


#+------------------------------------------------------------------+
#| F2c — on_tick (filtros de sessão)                                |
#+------------------------------------------------------------------+
def test_tick_bloqueia_fora_do_horario():
    sess = TradingSession(_preset())
    decision = sess.on_tick(_snap(ask=1000.0, bid=999.0,
                                  now=T0.replace(hour=8)))
    assert decision.intent is None
    assert decision.blocked_reason == "outside_hours"


def test_tick_bloqueia_entry_block():
    preset = _preset()
    preset = StdDevV510Preset.model_validate({
        **preset.model_dump(mode="json"),
        "session": {
            **preset.session.model_dump(mode="json"),
            "use_entry_block": True,
            "entry_block": {"start": "10:00:00", "end": "11:00:00"},
        },
    })
    sess = TradingSession(preset)
    decision = sess.on_tick(_snap(ask=1000.0, bid=999.0,
                                  now=T0.replace(hour=10, minute=30)))
    assert decision.blocked_reason == "entry_block"


def test_tick_bloqueia_cooldown_pos_sl():
    sess = TradingSession(_preset())
    now_sl = T0.replace(hour=10, minute=0)
    sess.notify_stop_loss(now_sl)
    decision = sess.on_tick(_snap(ask=1000.0, bid=999.0,
                                  now=now_sl + timedelta(minutes=5)))
    assert decision.blocked_reason == "cooldown"


def test_tick_libera_cooldown_apos_expirar():
    sess = TradingSession(_preset())
    now_sl = T0.replace(hour=10, minute=0)
    sess.notify_stop_loss(now_sl)
    decision = sess.on_tick(_snap(ask=1000.0, bid=999.0,
                                  now=now_sl + timedelta(minutes=11)))
    assert decision.blocked_reason != "cooldown"


def test_tick_bloqueia_daily_limit():
    preset = _preset()
    preset = StdDevV510Preset.model_validate({
        **preset.model_dump(mode="json"),
        "session": {
            **preset.session.model_dump(mode="json"),
            "max_trades_day": 1,
        },
    })
    sess = TradingSession(preset)
    sess.notify_trade_opened(T0 + 10 * TICK)
    decision = sess.on_tick(_snap(ask=1000.0, bid=999.0, now=T0 + 20 * TICK))
    assert decision.blocked_reason == "daily_limit"


#+------------------------------------------------------------------+
#| F2c — on_tick (emissão de TradeIntent)                           |
#+------------------------------------------------------------------+
def test_tick_emite_intent_apos_rompimento_e_pullback():
    preset = _preset()
    preset = StdDevV510Preset.model_validate({
        **preset.model_dump(mode="json"),
        "entry": EntryParams(level_mode=EntryLevelMode.MID).model_dump(),
    })
    sess = TradingSession(preset)

    sess.on_bar_closed(
        bar=_bar(T0 + 10 * TICK, high=1200.0, low=1000.0, vol=5000.0),
        zscore=5.0, now=T0 + 10 * TICK,
    )
    assert len(sess.regions) == 1

    sess.on_tick(_snap(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    reg = sess.regions.governing()
    assert reg is not None
    assert reg.phase.value == "BROKEN"

    decision = sess.on_tick(_snap(ask=1100.0, bid=1099.0, now=T0 + 12 * TICK))
    assert decision.intent is not None
    assert decision.intent.is_buy is True
    assert decision.intent.entry_price == 1100.0
    assert decision.intent.stop_loss == 800.0
    assert decision.intent.take_profit == 1700.0


def test_tick_nao_emite_intent_se_preco_nao_chegou_no_nivel():
    preset = _preset()
    preset = StdDevV510Preset.model_validate({
        **preset.model_dump(mode="json"),
        "entry": EntryParams(level_mode=EntryLevelMode.MID).model_dump(),
    })
    sess = TradingSession(preset)

    sess.on_bar_closed(
        bar=_bar(T0 + 10 * TICK, high=1200.0, low=1000.0, vol=5000.0),
        zscore=5.0, now=T0 + 10 * TICK,
    )
    sess.on_tick(_snap(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    decision = sess.on_tick(_snap(ask=1150.0, bid=1149.0, now=T0 + 12 * TICK))
    assert decision.intent is None


def test_tick_sem_regiao_nao_emite():
    sess = TradingSession(_preset())
    decision = sess.on_tick(_snap(ask=1000.0, bid=999.0, now=T0 + 10 * TICK))
    assert decision.intent is None
    assert decision.blocked_reason is None


#+------------------------------------------------------------------+
#| F3b — helpers de deal e sessão com região                        |
#+------------------------------------------------------------------+
def _mk_deal(
    *,
    ticket: int = 500,
    position_ticket: int = 5000,
    is_buy: bool = True,
    volume: float = 6.0,
    price: float = 1100.0,
    is_entry: bool = False,
    reason: int = DEAL_REASON_CLIENT,
    comment: str = "",
) -> DealInfo:
    return DealInfo(
        ticket=ticket, order_ticket=ticket,
        position_ticket=position_ticket,
        symbol="WIN$N", is_buy=is_buy, volume=volume, price=price,
        is_entry=is_entry, magic=0, comment=comment,
        time=T0, reason=reason,
    )


def _mk_sessao_com_regiao(
    *, use_reverse: bool = False, reuse_sl_signal: bool = False
):
    """Cria sessão + registra uma região + rompe + SIMULA a abertura do trade.

    A linha `sess.notify_trade_opened(...)` preenche `_current_entry_region`
    para que o `on_trade_event` saiba qual região consumir/rearmar.
    """
    preset_base = _preset()
    preset = StdDevV510Preset.model_validate({
        **preset_base.model_dump(mode="json"),
        "risk": {
            **preset_base.risk.model_dump(mode="json"),
            "use_reverse": use_reverse,
            "reuse_sl_signal": reuse_sl_signal,
        },
    })
    sess = TradingSession(preset)
    sess.on_bar_closed(
        bar=_bar(T0 + 10 * TICK, high=1200.0, low=1000.0, vol=5000.0),
        zscore=5.0, now=T0 + 10 * TICK,
    )
    sess.on_tick(_snap(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    reg = sess.regions.governing()
    assert reg is not None

    # Simula a abertura do trade (engine run faria isso após executor.execute OK)
    sess.notify_trade_opened(now=T0 + 12 * TICK, region_bar_time=reg.bar_time)

    return sess, reg.bar_time


#+------------------------------------------------------------------+
#| F3b — on_trade_event                                             |
#+------------------------------------------------------------------+
def test_on_trade_event_entry_filled_rastreia_position():
    sess = TradingSession(_preset())
    deal = _mk_deal(ticket=500, position_ticket=5000, is_entry=True)
    event = EntryFilled(deal=deal, position_ticket=5000)

    sess.on_trade_event(event, now=T0 + 20 * TICK)

    assert sess.current_entry_position == 5000


def test_on_trade_event_sl_sem_rearme_consome_regiao():
    sess, region_time = _mk_sessao_com_regiao()
    deal = _mk_deal(ticket=501, is_entry=False, reason=DEAL_REASON_SL)
    event = StopLossHit(deal=deal, position_ticket=5000)

    sess.on_trade_event(event, now=T0 + 20 * TICK)

    reg = sess.regions.get(region_time)
    assert reg is not None
    assert reg.phase.value == "CONSUMED"
    assert sess.last_sl_time is not None


def test_on_trade_event_sl_com_use_reverse_rearma_uma_vez():
    sess, region_time = _mk_sessao_com_regiao(use_reverse=True)
    deal = _mk_deal(ticket=502, is_entry=False, reason=DEAL_REASON_SL)
    event = StopLossHit(deal=deal, position_ticket=5000)

    sess.on_trade_event(event, now=T0 + 20 * TICK)

    reg = sess.regions.get(region_time)
    assert reg is not None
    assert reg.phase.value == "REARMED"
    assert reg.rearmed_once is True


def test_on_trade_event_sl_com_reuse_sl_signal_rearma_sem_limite():
    sess, region_time = _mk_sessao_com_regiao(reuse_sl_signal=True)
    deal = _mk_deal(ticket=503, is_entry=False, reason=DEAL_REASON_SL)

    sess.on_trade_event(StopLossHit(deal=deal, position_ticket=5000),
                        now=T0 + 20 * TICK)
    reg = sess.regions.get(region_time)
    assert reg is not None
    assert reg.phase.value == "REARMED"

    sess.on_trade_event(StopLossHit(deal=deal, position_ticket=5000),
                        now=T0 + 30 * TICK)
    reg = sess.regions.get(region_time)
    assert reg is not None
    assert reg.phase.value == "REARMED"


def test_on_trade_event_take_profit_consome_regiao():
    sess, region_time = _mk_sessao_com_regiao()
    deal = _mk_deal(ticket=504, is_entry=False, reason=DEAL_REASON_TP)
    event = TakeProfitHit(deal=deal, position_ticket=5000)

    sess.on_trade_event(event, now=T0 + 20 * TICK)

    reg = sess.regions.get(region_time)
    assert reg is not None
    assert reg.phase.value == "CONSUMED"


def test_on_trade_event_position_closed_consome_regiao():
    sess, region_time = _mk_sessao_com_regiao()
    deal = _mk_deal(ticket=505, is_entry=False, reason=DEAL_REASON_CLIENT,
                    comment="close")
    event = PositionClosed(deal=deal, position_ticket=5000)

    sess.on_trade_event(event, now=T0 + 20 * TICK)

    reg = sess.regions.get(region_time)
    assert reg is not None
    assert reg.phase.value == "CONSUMED"


def test_on_trade_event_partial_nao_consome_regiao():
    sess, region_time = _mk_sessao_com_regiao()
    deal = _mk_deal(ticket=506, is_entry=False, reason=DEAL_REASON_CLIENT,
                    volume=3.0, comment="partial")
    event = PartialFilled(deal=deal, position_ticket=5000, remaining_volume=3.0)

    sess.on_trade_event(event, now=T0 + 20 * TICK)

    reg = sess.regions.get(region_time)
    assert reg is not None
    assert reg.phase.value == "BROKEN"

def test_trading_session_nao_duplica_ordem_enquanto_aberta():
    """Garante que a trava anti-spam impede múltiplos TradeIntents."""
    from datetime import timezone
    
    # 1. Cria a sessão com o preset padrão dos testes
    sess = TradingSession(_preset())

    # 2. Cria uma região válida (exatamente como o teste de pullback faz)
    sess.on_bar_closed(
        bar=_bar(T0 + 10 * TICK, high=1200.0, low=1000.0, vol=5000.0),
        zscore=5.0, now=T0 + 10 * TICK,
    )
    
    # 3. Força o rompimento (para a região ficar no estado BROKEN)
    sess.on_tick(_snap(ask=1210.0, bid=1205.0, now=T0 + 11 * TICK))
    
    reg = sess.regions.governing()
    assert reg is not None

    # 4. Simula que a primeira ordem foi enviada e executada
    # (Isso preenche a _current_entry_region, ativando a trava)
    sess.notify_trade_opened(
        now=T0 + 12 * TICK,
        region_bar_time=reg.bar_time,
        entry_price=1100.0, # Preço de pullback
        is_buy=True,
    )

    # 5. O preço volta para o nível de entrada novamente (pullback)
    # Se a trava não existisse, ele emitiria um novo TradeIntent aqui.
    decision = sess.on_tick(_snap(ask=1100.0, bid=1099.0, now=T0 + 13 * TICK))

    # 6. A PROVA DOS 9: O intent DEVE ser None (bloqueado)
    assert decision.intent is None
    assert sess.current_entry_region is not None