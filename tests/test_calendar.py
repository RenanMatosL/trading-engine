from datetime import datetime, time

from engine.domain.risk.calendar import TradingWindow


def test_janela_normal():
    w = TradingWindow(start=time(9, 0), end=time(17, 30))
    assert w.is_open(datetime(2026, 8, 13, 10, 0))
    assert not w.is_open(datetime(2026, 8, 13, 17, 30))
    assert not w.is_open(datetime(2026, 8, 13, 8, 59))


def test_janela_cruzando_meia_noite():
    w = TradingWindow(start=time(22, 0), end=time(2, 0))
    assert w.is_open(datetime(2026, 8, 13, 23, 0))
    assert w.is_open(datetime(2026, 8, 13, 1, 0))
    assert not w.is_open(datetime(2026, 8, 13, 12, 0))



#+------------------------------------------------------------------+
#| F5d — B3Calendar + session_shift                                 |
#+------------------------------------------------------------------+
def test_b3_calendar_sabado_domingo_nao_sao_pregoes():
    from datetime import date
    from engine.domain.risk.exchange_calendar import B3Calendar

    cal = B3Calendar()
    # 2026-10-31 = sábado, 2026-11-01 = domingo
    assert cal.is_trading_day(date(2026, 10, 31)) is False
    assert cal.is_trading_day(date(2026, 11, 1)) is False
    # 2026-10-30 = sexta
    assert cal.is_trading_day(date(2026, 10, 30)) is True


def test_b3_calendar_feriado_nao_e_pregao():
    from datetime import date
    from engine.domain.risk.exchange_calendar import B3Calendar

    cal = B3Calendar()
    # 2026-11-02 = Finados (segunda) → feriado
    assert cal.is_trading_day(date(2026, 11, 2)) is False
    # 2026-11-03 = terça → pregão
    assert cal.is_trading_day(date(2026, 11, 3)) is True


def test_session_shift_sexta_para_segunda():
    """Sexta → segunda = 1 pregão (não 3 dias corridos)."""
    from datetime import date, datetime
    from engine.domain.risk.calendar import TradingWindow
    from engine.domain.risk.exchange_calendar import B3Calendar
    from datetime import time as dt_time

    cal = B3Calendar()
    tw = TradingWindow(start=dt_time(9, 0), end=dt_time(17, 30))
    # 2026-10-30 = sexta, 2026-11-02 = segunda (feriado), 2026-11-03 = terça
    # sexta → terça = 1 pregão (segunda é feriado)
    shift = tw.session_shift(
        bar_time=datetime(2026, 10, 30, 10, 0),
        now=datetime(2026, 11, 3, 10, 0),
        calendar=cal,
    )
    assert shift == 1  # segunda (feriado) não conta; terça = 1


def test_session_shift_mesmo_dia_e_zero():
    from datetime import datetime, time as dt_time
    from engine.domain.risk.calendar import TradingWindow
    from engine.domain.risk.exchange_calendar import B3Calendar

    cal = B3Calendar()
    tw = TradingWindow(start=dt_time(9, 0), end=dt_time(17, 30))
    shift = tw.session_shift(
        bar_time=datetime(2026, 10, 30, 10, 0),
        now=datetime(2026, 10, 30, 15, 0),
        calendar=cal,
    )
    assert shift == 0
