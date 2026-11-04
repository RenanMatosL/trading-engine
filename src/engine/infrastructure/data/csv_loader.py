"""Carregador de CSV de candles (F6).

Formato esperado:
  time,open,high,low,close,tick_volume,real_volume

- `time`: formato ISO 8601 (`YYYY-MM-DD HH:MM:SS`) ou epoch (segundos).
- `open`, `high`, `low`, `close`: float.
- `tick_volume`, `real_volume`: int.

Retorna `list[Bar]` com timezone UTC (aware).

Zero dependências externas (só stdlib `csv`). Testável com pytest puro.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from engine.domain.shared.types import Bar


def _parse_time(raw: str) -> datetime:
    """Aceita ISO 8601 (`YYYY-MM-DD HH:MM:SS`) ou epoch (segundos)."""
    raw = raw.strip()
    # Tenta epoch primeiro
    try:
        ts = int(raw)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except ValueError:
        pass
    # Tenta ISO 8601
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_bars_csv(path: str | Path) -> list[Bar]:
    """Carrega um CSV de candles. Header obrigatório.

    Levanta `FileNotFoundError` se o arquivo não existir.
    Levanta `ValueError` se o CSV estiver malformado (coluna faltando, tipo inválido).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"CSV não encontrado: {p}")

    bars: list[Bar] = []
    with p.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {"time", "open", "high", "low", "close",
                    "tick_volume", "real_volume"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                f"CSV faltando colunas obrigatórias: {sorted(missing)}"
            )

        for i, row in enumerate(reader, start=2):  # start=2: header é linha 1
            try:
                bars.append(Bar(
                    time=_parse_time(row["time"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    tick_volume=float(row["tick_volume"]),
                    real_volume=float(row["real_volume"]),
                ))
            except (ValueError, KeyError) as exc:
                raise ValueError(
                    f"CSV malformado na linha {i}: {exc}"
                ) from exc

    return bars