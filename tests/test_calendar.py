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
