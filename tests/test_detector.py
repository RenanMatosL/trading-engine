"""Golden tests do detector - semantica identica ao EA v5.10 (janela inclui o candle)."""
import math
import statistics
from datetime import datetime, timezone

import pytest

from engine.domain.shared.types import Bar, VolumeSource
from engine.domain.strategy.detector import VolumeStdDetector


def _bar(vol: float) -> Bar:
    return Bar(time=datetime.now(tz=timezone.utc), open=1, high=2, low=0, close=1,
               tick_volume=vol, real_volume=0.0)


def test_janela_incompleta_nao_emite_leitura():
    det = VolumeStdDetector(length=5, std_ref=4.0, source=VolumeSource.TICK)
    for v in [2000, 2000, 2000, 2000]:
        assert det.on_bar_closed(_bar(v)) is None
    assert not det.ready


def test_golden_lanchonete_15000_salgados():
    """Exemplo canonico dos manuais (media ~2000, dia de 15000) COM a semantica
    do EA: a janela INCLUI o candle avaliado. Propriedade matematica importante
    que este teste documenta: com autoinclusao, o z maximo de uma janela de n
    candles e (n-1)/sqrt(n) (~1.789 para n=5) - o outlier infla o proprio desvio
    que o mede. No Len=180 de producao o efeito e despresivel; em janelas
    minusculas ele limita o z, e o teste garante paridade exata com o MQL5."""
    vols = [2000.0, 2100.0, 1900.0, 2000.0, 15000.0]
    det = VolumeStdDetector(length=5, std_ref=1.5, source=VolumeSource.TICK)
    reading = None
    for v in vols:
        reading = det.on_bar_closed(_bar(v))
    assert reading is not None
    esperado_media = statistics.mean(vols)
    esperado_std = statistics.stdev(vols)          # amostral (n-1), como o EA
    assert math.isclose(reading.mean, esperado_media)
    assert math.isclose(reading.std, esperado_std, rel_tol=1e-9)
    esperado_z = (15000.0 - esperado_media) / esperado_std
    assert math.isclose(reading.zscore, esperado_z, rel_tol=1e-9)
    assert math.isclose(reading.zscore, 1.7887, rel_tol=1e-3)
    assert reading.is_signal                        # 1.789 >= 1.5
    # e o teto teorico: com std_ref acima de (n-1)/sqrt(n), NUNCA ha sinal em n=5
    det2 = VolumeStdDetector(length=5, std_ref=2.0, source=VolumeSource.TICK)
    r2 = None
    for v in vols:
        r2 = det2.on_bar_closed(_bar(v))
    assert not r2.is_signal


def test_janela_desliza_e_some_o_antigo():
    det = VolumeStdDetector(length=3, std_ref=99.0, source=VolumeSource.TICK)
    for v in [10.0, 20.0, 30.0]:
        det.on_bar_closed(_bar(v))
    r = det.on_bar_closed(_bar(40.0))              # janela agora: 20,30,40
    assert math.isclose(r.mean, 30.0)
    assert math.isclose(r.std, statistics.stdev([20.0, 30.0, 40.0]))


def test_volume_real_com_fallback_para_tick():
    b = Bar(time=datetime.now(tz=timezone.utc), open=1, high=2, low=0, close=1,
            tick_volume=500.0, real_volume=0.0)
    assert b.volume(VolumeSource.REAL) == 500.0    # real zerado -> tick
    b2 = Bar(time=b.time, open=1, high=2, low=0, close=1,
             tick_volume=500.0, real_volume=9000.0)
    assert b2.volume(VolumeSource.REAL) == 9000.0


def test_parametros_invalidos():
    with pytest.raises(ValueError):
        VolumeStdDetector(length=1, std_ref=4.0, source=VolumeSource.TICK)
    with pytest.raises(ValueError):
        VolumeStdDetector(length=10, std_ref=0.0, source=VolumeSource.TICK)
