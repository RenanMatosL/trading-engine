"""Golden tests do load_bars_csv (F6)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.infrastructure.data.csv_loader import load_bars_csv


FIXTURE = Path(__file__).parent / "fixtures" / "sample_bars.csv"


#+------------------------------------------------------------------+
#| Loader                                                           |
#+------------------------------------------------------------------+
def test_load_bars_csv_fixture_real():
    """Carrega o fixture real (10 candles do WIN$N M1)."""
    bars = load_bars_csv(FIXTURE)
    assert len(bars) == 10
    assert bars[0].time == datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)
    assert bars[0].open == 170900.0
    assert bars[0].close == 170950.0
    assert bars[0].tick_volume == 2500.0
    assert bars[-1].time == datetime(2026, 10, 29, 9, 9, tzinfo=timezone.utc)


def test_load_bars_csv_ordenado_por_tempo():
    """O CSV deve estar em ordem cronológica (loader preserva)."""
    bars = load_bars_csv(FIXTURE)
    for i in range(1, len(bars)):
        assert bars[i].time > bars[i - 1].time


def test_load_bars_csv_aceita_epoch():
    """Aceita `time` como epoch (segundos)."""
    import tempfile
    csv_content = (
        "time,open,high,low,close,tick_volume,real_volume\n"
        "1761739200,100,110,90,105,1000,0\n"
        "1761739260,105,115,95,110,1200,0\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                     encoding="utf-8") as f:
        f.write(csv_content)
        tmp = f.name
    try:
        bars = load_bars_csv(tmp)
        assert len(bars) == 2
        assert bars[0].open == 100.0
        # datetime.fromtimestamp(1761739200, tz=utc)
        assert bars[0].time.tzinfo is not None
    finally:
        Path(tmp).unlink()


def test_load_bars_csv_arquivo_inexistente_falha():
    with pytest.raises(FileNotFoundError, match="não encontrado"):
        load_bars_csv("nao_existe.csv")


def test_load_bars_csv_coluna_faltando_falha():
    import tempfile
    csv_content = "time,open,high,low,close\n2026-10-29 09:00:00,100,110,90,105\n"
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False,
                                     encoding="utf-8") as f:
        f.write(csv_content)
        tmp = f.name
    try:
        with pytest.raises(ValueError, match="faltando colunas"):
            load_bars_csv(tmp)
    finally:
        Path(tmp).unlink()