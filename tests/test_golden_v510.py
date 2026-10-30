"""Teste golden v5.10 — paridade do VolumeStdDetector com o EA v4.60.

Fonte de verdade: CSV exportado do MT5 pelo script `z_dump.mq5`,
com a MESMA semantica do EA v4.60:
  - janela INCLUI o candle avaliado (shifts 1..InpLen)
  - desvio AMOSTRAL (n-1)
  - media aritmetica simples
  - fonte de volume = TICK

Cada linha do CSV tem o z-score calculado pelo proprio MT5 (coluna `z`),
mean (coluna `mean`) e std (coluna `std`). O teste re-alimenta o detector
Python candle a candle (ordem cronologica) e exige paridade BIT-A-BIT
(na pratica, tolerancia 1e-9) em z, mean e std.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pytest

from engine.domain.shared.types import Bar, VolumeSource
from engine.domain.strategy.detector import VolumeStdDetector

FIXTURE = Path(__file__).parent / "fixtures" / "v510_expected.csv"

# Parametros identicos ao preset v510_default e ao EA v4.60
LEN = 180
STD_REF = 4.0
SOURCE = VolumeSource.TICK

# Tolerancia: o MT5 exporta 10 casas decimais; a formula de uma passada
# do Python e algebricamente identica. 1e-9 cobre o ruido de float do
# parser (nao cobre divergencia real, que e >> 1e-6).
TOL = 1e-9


def _parse_dt(s: str) -> datetime:
    """MT5 exporta 'YYYY.MM.DD HH:MM' (com ponto, nao hifen)."""
    return datetime.strptime(s.strip(), "%Y.%m.%d %H:%M")


def _load_rows() -> list[dict]:
    if not FIXTURE.exists():
        pytest.skip(
            f"Fixture nao encontrado em {FIXTURE}. "
            "Gere com z_dump.mq5 no MT5 e copie para tests/fixtures/."
        )
    with FIXTURE.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _row_to_bar(r: dict) -> Bar:
    return Bar(
        time=_parse_dt(r["time"]),
        open=float(r["open"]),
        high=float(r["high"]),
        low=float(r["low"]),
        close=float(r["close"]),
        tick_volume=float(r["tick_volume"]),
        real_volume=float(r["real_volume"]),
    )


#+------------------------------------------------------------------+
#| Teste 1: paridade candle a candle (z, mean, std)                 |
#+------------------------------------------------------------------+
def test_paridade_candle_a_candle() -> None:
    rows = _load_rows()
    assert len(rows) >= LEN + 1, (
        f"Fixture tem {len(rows)} candles; minimo {LEN + 1} para 1 leitura."
    )

    # Ordem cronologica: o CSV vem do mais antigo (idx maior) para o
    # mais novo (idx=1).
    rows_sorted = sorted(rows, key=lambda r: int(r["idx"]), reverse=True)

    det = VolumeStdDetector(length=LEN, std_ref=STD_REF, source=SOURCE)

    divergencias: list[str] = []
    leituras = 0

    for row in rows_sorted:
        reading = det.on_bar_closed(_row_to_bar(row))
        if reading is None:
            # Janela enchendo: o VolumeStdDetector so emite a partir do
            # LEN-esimo candle. O CSV ja vem pre-aquecido, entao essas
            # LEN-1 primeiras linhas nao tem contraparte em Python.
            continue

        leituras += 1

        z_mt5    = float(row["z"])
        mean_mt5 = float(row["mean"])
        std_mt5  = float(row["std"])

        dz    = reading.zscore - z_mt5
        dmean = reading.mean   - mean_mt5
        dstd  = reading.std    - std_mt5

        if abs(dz) > TOL or abs(dmean) > TOL or abs(dstd) > TOL:
            divergencias.append(
                f"idx={row['idx']} time={row['time']} "
                f"z(py)={reading.zscore:.10f} z(mt5)={z_mt5:.10f} dz={dz:.2e} | "
                f"mean(py)={reading.mean:.10f} mean(mt5)={mean_mt5:.10f} dmean={dmean:.2e} | "
                f"std(py)={reading.std:.10f} std(mt5)={std_mt5:.10f} dstd={dstd:.2e}"
            )

    assert not divergencias, (
        f"{len(divergencias)} candle(s) divergente(s) de {leituras} "
        f"leituras (tol={TOL:.1e}):\n" + "\n".join(divergencias[:10])
    )

    # O CSV ja vem pre-aquecido: cada linha tem z-score calculado sobre
    # janela completa. O Python so emite a partir do LEN-esimo candle
    # recebido, entao o numero esperado e (total - (LEN-1)).
    esperadas = max(0, len(rows_sorted) - (LEN - 1))
    assert leituras == esperadas, (
        f"Esperava {esperadas} leituras (linhas do CSV a partir do "
        f"{LEN}o candle), mas {leituras} foram produzidas."
    )


#+------------------------------------------------------------------+
#| Teste 2: is_signal (z >= std_ref) bate candle a candle           |
#+------------------------------------------------------------------+
def test_is_signal_alinhado() -> None:
    rows = _load_rows()
    rows_sorted = sorted(rows, key=lambda r: int(r["idx"]), reverse=True)

    det = VolumeStdDetector(length=LEN, std_ref=STD_REF, source=SOURCE)
    mismatches: list[str] = []

    for row in rows_sorted:
        reading = det.on_bar_closed(_row_to_bar(row))
        if reading is None:
            continue
        z_mt5 = float(row["z"])
        sinal_mt5 = z_mt5 >= STD_REF
        if reading.is_signal != sinal_mt5:
            mismatches.append(
                f"idx={row['idx']} time={row['time']} "
                f"z={z_mt5:.6f} py_is_signal={reading.is_signal} mt5_z>=ref={sinal_mt5}"
            )

    assert not mismatches, (
        f"{len(mismatches)} candle(s) com is_signal divergente:\n"
        + "\n".join(mismatches[:10])
    )


#+------------------------------------------------------------------+
#| Teste 3: sanity do fixture (ordem e contagem)                    |
#+------------------------------------------------------------------+
def test_fixture_sanity() -> None:
    rows = _load_rows()
    idxs = [int(r["idx"]) for r in rows]
    assert idxs == list(range(idxs[0], 0, -1)), (
        "CSV deve vir do maior idx (mais antigo) para idx=1 (mais novo), "
        "sem buracos."
    )
    times = [_parse_dt(r["time"]) for r in rows]
    for i in range(1, len(times)):
        assert times[i] > times[i - 1], (
            f"time nao monotonico entre idx={idxs[i-1]} e idx={idxs[i]}"
        )
    assert len(rows) >= LEN, f"Fixture com {len(rows)} < LEN={LEN} candles"