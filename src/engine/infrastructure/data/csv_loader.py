"""Carregador de CSV de candles (F6 + F8 adaptativo).

Aceita três formatos:
  1. Padrão do projeto (ISO 8601, vírgula).
  2. MT5 com cabeçalho (separador ;, <DATE> e <TIME>).
  3. MT5 sem cabeçalho (2026.05.12 17:12,...).

Detecta automaticamente a codificação (UTF-8, UTF-16, Windows-1252).
Retorna `list[Bar]` com timezone UTC.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

from engine.domain.shared.types import Bar


#+------------------------------------------------------------------+
#| Detecção de codificação                                          |
#+------------------------------------------------------------------+
def _open_csv(path: Path):
    """Abre o arquivo tentando UTF-8, UTF-16 e Windows-1252."""
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return path.open("r", encoding="utf-16", newline="")
    if raw.startswith(b"\xef\xbb\xbf"):
        return path.open("r", encoding="utf-8-sig", newline="")
    try:
        raw.decode("utf-8")
        return path.open("r", encoding="utf-8", newline="")
    except UnicodeDecodeError:
        return path.open("r", encoding="cp1252", newline="")


#+------------------------------------------------------------------+
#| Detectores de formato                                             |
#+------------------------------------------------------------------+
def _is_iso_format(header: list[str]) -> bool:
    return (
        len(header) >= 5
        and header[0].strip().lower() == "time"
        and header[1].strip().lower() == "open"
    )


def _is_mt5_header_format(header: list[str]) -> bool:
    return (
        len(header) >= 6
        and header[0].strip().upper() in ("<DATE>", "DATE")
        and header[1].strip().upper() in ("<TIME>", "TIME")
    )


def _is_mt5_no_header_format(line: str) -> bool:
    parts = line.split(",")
    if len(parts) < 5:
        return False
    first = parts[0].strip()
    return "." in first and " " in first


#+------------------------------------------------------------------+
#| Parser genérico                                                  |
#+------------------------------------------------------------------+
def _parse_dt(raw: str) -> datetime:
    """Aceita `2026.05.12 17:12`, `2026.05.12 17:12:00` ou ISO."""
    raw = raw.strip()
    for fmt in ("%Y.%m.%d %H:%M", "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        raise ValueError(f"timestamp inválido: {raw!r}") from None


def _parse_mt5_no_header(path: Path) -> list[Bar]:
    bars: list[Bar] = []
    with _open_csv(path) as f:
        for row in csv.reader(f):
            if not row or len(row) < 5:
                continue
            try:
                dt = _parse_dt(row[0])
                bars.append(Bar(
                    time=dt,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    tick_volume=float(row[5]) if len(row) > 5 else 0.0,
                    real_volume=float(row[6]) if len(row) > 6 else 0.0,
                ))
            except (ValueError, IndexError):
                continue
    return bars


def _parse_mt5_header(path: Path) -> list[Bar]:
    bars: list[Bar] = []
    with _open_csv(path) as f:
        first_line = f.readline()
        delimiter = "\t" if "\t" in first_line else ";"
        f.seek(0)
        reader = csv.reader(f, delimiter=delimiter)
        next(reader, None)  # pula cabeçalho
        for row in reader:
            if not row or len(row) < 6:
                continue
            try:
                dt = _parse_dt(f"{row[0].strip().replace('.', '-')} {row[1].strip()}")
                bars.append(Bar(
                    time=dt,
                    open=float(row[2]),
                    high=float(row[3]),
                    low=float(row[4]),
                    close=float(row[5]),
                    tick_volume=float(row[6]) if len(row) > 6 else 0.0,
                    real_volume=float(row[7]) if len(row) > 7 else 0.0,
                ))
            except (ValueError, IndexError):
                continue
    return bars


def _parse_iso(path: Path) -> list[Bar]:
    bars: list[Bar] = []
    with _open_csv(path) as f:
        reader = csv.DictReader(f)
        # Checa as colunas obrigatórias
        required = {"time", "open", "high", "low", "close", "tick_volume"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV faltando colunas obrigatórias: {missing}")
        for row in reader:
            try:
                time_str = row["time"].strip()
                if time_str.isdigit():
                    dt = datetime.fromtimestamp(float(time_str), tz=timezone.utc)
                else:
                    dt = _parse_dt(time_str)
                bars.append(Bar(
                    time=dt,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    tick_volume=float(row.get("tick_volume", 0) or 0),
                    real_volume=float(row.get("real_volume", 0) or 0),
                ))
            except (ValueError, KeyError):
                continue
    return bars


#+------------------------------------------------------------------+
#| Entry point                                                      |
#+------------------------------------------------------------------+
def load_bars_csv(path: Path | str) -> list[Bar]:
    """Carrega CSV nos formatos ISO, MT5 com cabeçalho ou MT5 sem cabeçalho."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"CSV não encontrado: {path}")

    with _open_csv(path) as f:
        first_line = f.readline().strip()
        if not first_line:
            raise ValueError("CSV vazio")

    # Detecta o separador
    if "\t" in first_line:
        delimiter = "\t"
    elif ";" in first_line:
        delimiter = ";"
    else:
        delimiter = ","

    header = [h.strip().lower() for h in first_line.split(delimiter)]

    # 1. ISO com header explícito (o _parse_iso checa as colunas obrigatórias)
    if _is_iso_format(header):
        return _parse_iso(path)

    # 2. MT5 com header
    if _is_mt5_header_format(header):
        return _parse_mt5_header(path)

    # 3. MT5 sem header
    if _is_mt5_no_header_format(first_line):
        return _parse_mt5_no_header(path)

    # 4. Fallback: tenta o parser MT5 sem header
    try:
        result = _parse_mt5_no_header(path)
        if result:
            return result
    except Exception:
        pass

    raise ValueError(
        f"Formato de CSV não reconhecido. Cabeçalho: {header[:8]}. "
        f"Esperado ISO (time,open,...), MT5 com cabeçalho (<DATE>;<TIME>;...), "
        f"ou MT5 sem cabeçalho (2026.05.12 17:12,...). "
        f"Verifique se faltando colunas obrigatórias."
    )