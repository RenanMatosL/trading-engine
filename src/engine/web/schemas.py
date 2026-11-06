"""Schemas Pydantic do frontend (F7a+).

Response e request models para os endpoints JSON.
Reusa os tipos do backend (`AccountInfo`, `DetectorReading`, etc) onde possível.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


#+------------------------------------------------------------------+
#| Response models                                                  |
#+------------------------------------------------------------------+
class AccountSchema(BaseModel):
    """Conta MT5 (subset do `AccountInfo`)."""
    login: int
    server: str
    balance: float
    currency: str


class DetectorSchema(BaseModel):
    """Leitura do detector z-score."""
    zscore: float
    mean: float
    std: float
    volume: float
    is_signal: bool


class RegionSchema(BaseModel):
    """Região ativa (subset do `RegionState`)."""
    bar_time: datetime
    phase: str
    is_buy: bool
    stop_loss: float
    take_profit: float
    volume: float


class StatusResponse(BaseModel):
    """Resposta do `/api/status`."""
    account: AccountSchema
    symbol: str
    bars_loaded: int
    last_bar_time: str
    last_close: float
    detector: DetectorSchema | None = None
    regions_count: int = 0
    regions: list[RegionSchema] = Field(default_factory=list)
    engine_status: str = "unknown"  # "ready" / "no_mt5" / "error"
    error: str | None = None


#+------------------------------------------------------------------+
#| Request models (F7c+)                                            |
#+------------------------------------------------------------------+
class PresetUpdateRequest(BaseModel):
    """Atualização do preset via JSON (F7c)."""
    detector: dict | None = None
    session: dict | None = None
    entry: dict | None = None
    stop: dict | None = None
    take_profit: dict | None = None
    risk: dict | None = None
    regions: dict | None = None



#+------------------------------------------------------------------+
#| F7b-2: Trades + Equity                                           |
#+------------------------------------------------------------------+
class TradeSchema(BaseModel):
    """Trade fechado (subset do `TradeRecord`)."""
    id: int | None = None
    region_bar_time: str
    is_buy: bool
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    stop_loss: float
    take_profit: float
    initial_volume: float
    pnl_points: float
    pnl_money: float
    exit_reason: str


class EquityPointSchema(BaseModel):
    """Ponto da equity curve."""
    time: str
    balance: float