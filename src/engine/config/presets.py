"""Presets de estratégia em YAML -> parâmetros tipados/validados.

Espelha EXATAMENTE os inputs do EA `StdDevVolumeBreakout.mq5` v4.60
(ver comentários no YAML default). Validadores cruzados replicam o
`OnInit()` do EA — combinações incoerentes são rejeitadas no load,
não em runtime.

Fonte única de verdade para F2+: o `TradingSession` lê daqui.
"""
from __future__ import annotations

from datetime import time
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from engine.domain.shared.types import VolumeSource


#+------------------------------------------------------------------+
#| Enums (espelham os ENUM_* do EA)                                 |
#+------------------------------------------------------------------+
class EntryLevelMode(str, Enum):
    """ENUM_ENTRY_LEVEL do EA."""
    DEFAULT = "default"
    BROKEN_EXTREME = "broken_extreme"
    MID = "mid"
    OPPOSITE_EXTREME = "opposite_extreme"
    IMMEDIATE = "immediate"


class SLLevelMode(str, Enum):
    """ENUM_SL_LEVEL do EA."""
    DEFAULT = "default"
    OPPOSITE_EXTREME = "opposite_extreme"
    MID = "mid"


class SizingMode(str, Enum):
    """ENUM_SIZING_MODE do EA."""
    FIXED_CONTRACTS = "fixed_contracts"
    BY_RISK = "by_risk"


class RiskMode(str, Enum):
    """ENUM_RISK_MODE do EA."""
    FIXED_MONEY = "fixed_money"
    PERCENT_BALANCE = "percent_balance"


class CandidateMode(str, Enum):
    """ENUM_CANDIDATE_MODE do EA."""
    HIGHEST_VOLUME = "highest_volume"
    FIRST_READY = "first_ready"


class PartialExitType(str, Enum):
    """ENUM_PARTIAL_EXIT_TYPE do EA."""
    POINTS = "points"
    PERCENT = "percent"

class TriggerMode(str, Enum):
    """Modo do gatilho: normal (rompeu = segue) ou trap (rompeu = inverte)."""
    NORMAL = "normal"
    TRAP = "trap"

class TriggerStyle(str, Enum):
    """Estilo do modo trap: imediata (ao atingir X) ou pullback (no retorno)."""
    IMMEDIATE = "immediate"
    PULLBACK = "pullback"


#+------------------------------------------------------------------+
#| TimeWindowParams — janela reutilizável (sessão, bloqueio)        |
#+------------------------------------------------------------------+
class TimeWindowParams(BaseModel):
    """Janela de tempo [start, end). Suporta cruzamento de meia-noite."""
    start: time = time(9, 0)
    end: time = time(17, 30)

    @model_validator(mode="after")
    def _coherent(self) -> "TimeWindowParams":
        # start == end é aceito em alguns contextos (janela vazia = desligado).
        # Quem quiser proibir valida no campo pai.
        return self


#+------------------------------------------------------------------+
#| DetectorParams                                                   |
#+------------------------------------------------------------------+
class DetectorParams(BaseModel):
    """InpLen, InpStdRef, InpVolType, InpTimeframe, InpSignalMuteOpenMin
    + regra de candle grande (InpUseBigCandleRule e afins)."""
    length: int = Field(180, ge=2, description="Janela da média/desvio do volume (candles)")
    std_ref: float = Field(4.0, gt=0, description="z-score mínimo do candle-sinal")
    volume_source: VolumeSource = VolumeSource.TICK
    timeframe: str = Field("M1", pattern=r"^(M1|M5|M15|M30|H1)$")

    # --- Filtro de ruído da abertura (InpSignalMuteOpenMin) ---
    mute_open_min: int = Field(
        10, ge=0,
        description="Candles nos primeiros X min após a abertura NÃO geram região.",
    )

    # --- Regra de candle grande (InpUseBigCandleRule) ---
    use_big_candle_rule: bool = True
    big_candle_min_range: float = Field(
        400.0, gt=0,
        description="Range mínimo (pontos) que ativa a regra de candle grande.",
    )
    big_candle_entry_offset: float = Field(
        200.0, gt=0,
        description="Distância (pontos) do extremo para a entrada (candle grande).",
    )
    big_candle_sl_adjust: float = Field(
        0.0,
        description="Ajuste do SL em pontos (+, folga; -, justo).",
    )

    @model_validator(mode="after")
    def _big_candle_coherent(self) -> "DetectorParams":
        if self.use_big_candle_rule:
            if self.big_candle_entry_offset >= self.big_candle_min_range:
                raise ValueError(
                    "big_candle_entry_offset deve ser MENOR que big_candle_min_range"
                )
            if self.big_candle_sl_adjust <= -self.big_candle_entry_offset:
                raise ValueError(
                    "big_candle_sl_adjust não pode ser <= -big_candle_entry_offset"
                )
        return self


#+------------------------------------------------------------------+
#| SessionParams                                                    |
#+------------------------------------------------------------------+
class SessionParams(BaseModel):
    """Janela operacional + filtros de sessão (bloqueio, cooldown, TTL)."""
    # Janela operacional (InpStartHour/InpEndHour, InpCloseOutside)
    window: TimeWindowParams = Field(default_factory=TimeWindowParams)
    close_outside: bool = True

    # InpCarryEntryDelayMin: carência p/ regiões de pregões anteriores.
    carry_entry_delay_min: int = Field(
        15, ge=0,
        description="Minutos de carência pós-abertura para regiões de dias anteriores.",
    )

    # InpBreakoutTTLMin: validade pós-rompimento sem pullback.
    breakout_ttl_min: int = Field(
        60, ge=0,
        description="Minutos após rompimento sem pullback — 0 = nunca expira.",
    )

    # InpCooldownAfterSLMin: pausa após Stop Loss.
    cooldown_after_sl_min: int = Field(
        10, ge=0,
        description="Pausa (min) após SL — 0 = sem pausa.",
    )

    # InpMaxTradesDay: limite diário.
    max_trades_day: int = Field(
        3, ge=0,
        description="Máx. operações abertas/dia — 0 = sem limite.",
    )

    # InpUseEntryBlock + InpBlockStart/End: janela de exclusão de entradas.
    use_entry_block: bool = True
    entry_block: TimeWindowParams = Field(
        default_factory=lambda: TimeWindowParams(
            start=time(10, 0), end=time(11, 0)
        )
    )

    @model_validator(mode="after")
    def _block_window_non_empty(self) -> "SessionParams":
        if self.use_entry_block and self.entry_block.start == self.entry_block.end:
            raise ValueError(
                "entry_block.start e entry_block.end iguais com use_entry_block=True "
                "(janela vazia não é permitida)"
            )
        return self


#+------------------------------------------------------------------+
#| EntryParams                                                      |
#+------------------------------------------------------------------+
class EntryParams(BaseModel):
    """InpEntryLevelMode, InpEntryLevelOffset, InpEntryAsPending, InpMaxEntryGapPoints."""
    level_mode: EntryLevelMode = EntryLevelMode.DEFAULT
    level_offset_points: float = Field(
        0.0,
        description="Ajuste (pontos) sobre o nível escolhido — não se aplica a DEFAULT/IMMEDIATE.",
    )
    as_pending: bool = Field(
        True,
        description="True: ordem limite no nível exato. False: entrada a mercado.",
    )
    max_entry_gap_points: int = Field(
        100, ge=0,
        description="Gap máximo aceito na entrada — 0 = sem checagem.",
    )


#+------------------------------------------------------------------+
#| StopParams                                                       |
#+------------------------------------------------------------------+
class StopParams(BaseModel):
    """InpSLLevelMode, InpSLPoints, InpSLLevelOffset."""
    level_mode: SLLevelMode = SLLevelMode.DEFAULT
    sl_points: float = Field(
        200.0, gt=0,
        description="Pontos além da mín/máx (modo DEFAULT, fora do candle grande).",
    )
    level_offset_points: float = Field(
        0.0, ge=0,
        description="Pontos além do nível escolhido (modos OPPOSITE/MID).",
    )


#+------------------------------------------------------------------+
#| TakeProfitParams                                                 |
#+------------------------------------------------------------------+
class TakeProfitParams(BaseModel):
    """InpUseFinalTP, InpFinalTPPoints."""
    use_final_tp: bool = True
    final_tp_points: float = Field(
        600.0, ge=0,
        description="Pontos do TP final (a partir do meio do candle).",
    )


#+------------------------------------------------------------------+
#| RiskParams + PartialTier                                         |
#+------------------------------------------------------------------+
class PartialTier(BaseModel):
    """Um alvo parcial (1, 2 ou 3)."""
    contracts: int = Field(0, ge=0)
    points: float = Field(0.0, ge=0)

    @property
    def enabled(self) -> bool:
        return self.contracts > 0


class RiskParams(BaseModel):
    """Dimensionamento + parciais + reforço (tudo do grupo 'Risk' do EA)."""
    # --- Sizing (InpSizingMode, InpTotalContracts, InpLotPerContract) ---
    sizing_mode: SizingMode = SizingMode.FIXED_CONTRACTS
    total_contracts: int = Field(6, gt=0)
    lot_per_contract: float = Field(1.0, gt=0)

    # --- Modo 'Pelo risco' (InpRiskMode, InpRiskValue) ---
    risk_mode: RiskMode = RiskMode.PERCENT_BALANCE
    risk_value: float = Field(1.0, gt=0)

    # --- Parciais (InpUsePartialExit, InpExitType, InpPartial*) ---
    use_partial_exit: bool = False
    exit_type: PartialExitType = PartialExitType.POINTS
    partial_points: float = Field(200.0, ge=0)
    partial_percent: float = Field(0.2, ge=0)
    partial_as_pending: bool = True
    breakeven_after_partial: bool = False
    tiers: list[PartialTier] = Field(
        default_factory=lambda: [
            PartialTier(contracts=3, points=200.0),
            PartialTier(contracts=0, points=400.0),
            PartialTier(contracts=0, points=600.0),
        ]
    )

    # --- Reforço no retorno à entrada (InpUseReentry e afins) ---
    use_reentry: bool = False
    reentry_contracts: int = Field(3, gt=0)
    reentry_arm_points: float = Field(200.0, gt=0)
    reentry_tp_points: float = Field(200.0, gt=0)
    reentry_sl_points: float = Field(200.0, gt=0)

    # --- Reação ao Stop Loss (F3b) ---
    use_reverse: bool = Field(
        False,
        description="Inverter a mão 1 vez por região após SL (InpAllowReverse).",
    )
    reuse_sl_signal: bool = Field(
        False,
        description="Rearmar após SL sem limite (InpReuseSLSignal).",
    )

    # --- Validador cruzado das parciais (espelha o OnInit do EA) ---
    @model_validator(mode="after")
    def _partials_coherent(self) -> "RiskParams":
        if not self.use_partial_exit:
            return self

        # Só conta tiers habilitados (contracts > 0).
        enabled = [t for t in self.tiers if t.enabled]
        if not enabled:
            raise ValueError(
                "use_partial_exit=True exige ao menos 1 tier com contracts > 0"
            )

        # Soma dos contratos das parciais deve ser MENOR que o total.
        soma = sum(t.contracts for t in enabled)
        if soma >= self.total_contracts:
            raise ValueError(
                f"Soma dos contratos das parciais ({soma}) deve ser MENOR que "
                f"total_contracts ({self.total_contracts})"
            )

        # Pontos estritamente crescentes entre tiers habilitados.
        points = [t.points for t in enabled]
        for i in range(1, len(points)):
            if points[i] <= points[i - 1]:
                raise ValueError(
                    f"Pontos das parciais devem ser crescentes: "
                    f"tier {i+1} ({points[i]}) <= tier {i} ({points[i-1]})"
                )

        # Modo POINTS exige partial_points > 0; PERCENT exige partial_percent > 0.
        if self.exit_type == PartialExitType.POINTS and self.partial_points <= 0:
            raise ValueError("exit_type=points exige partial_points > 0")
        if self.exit_type == PartialExitType.PERCENT and self.partial_percent <= 0:
            raise ValueError("exit_type=percent exige partial_percent > 0")

        return self


#+------------------------------------------------------------------+
#| RegionsParams                                                    |
#+------------------------------------------------------------------+
class RegionsParams(BaseModel):
    """MAX_LOC, InpLocationValidDays, InpCandidateMode."""
    max_loc: int = Field(
        12, ge=1, le=100,
        description="Capacidade máxima de regiões simultâneas (MAX_LOC do EA).",
    )
    valid_days: int = Field(
        2, ge=0,
        description="Pregões anteriores em que a região continua válida.",
    )
    candidate_mode: CandidateMode = CandidateMode.HIGHEST_VOLUME


#+------------------------------------------------------------------+
#| StdDevV510Preset — preset raiz com validadores cruzados          |
#+------------------------------------------------------------------+
class StdDevV510Preset(BaseModel):
    """Preset completo do EA StdDevVolumeBreakout v4.60.

    O `model_validator` final replica as checagens cruzadas do `OnInit()`
    do EA (combinações inválidas de entry/sl, etc.) — falha no load do
    YAML, não em runtime.
    """
    name: str
    strategy: str = Field(pattern=r"^stddev_v510$")

    detector: DetectorParams = Field(default_factory=DetectorParams)
    session: SessionParams = Field(default_factory=SessionParams)
    entry: EntryParams = Field(default_factory=EntryParams)
    stop: StopParams = Field(default_factory=StopParams)
    take_profit: TakeProfitParams = Field(default_factory=TakeProfitParams)
    risk: RiskParams = Field(default_factory=RiskParams)
    regions: RegionsParams = Field(default_factory=RegionsParams)
    # --- Modo do Gatilho (F9) ---
    trigger_mode: TriggerMode = TriggerMode.NORMAL
    trap_arm_points: float = Field(200.0, ge=0)
    trap_style: TriggerStyle = TriggerStyle.IMMEDIATE
    trap_sl_points: float = Field(200.0, ge=0)

    @field_validator("name")
    @classmethod
    def _named(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("preset precisa de um nome")
        return v

    @model_validator(mode="after")
    def _cross_section_coherent(self) -> "StdDevV510Preset":
        """Regras cruzadas do OnInit() do EA v4.60."""

        # (1) Entrada no EXTREMO OPOSTO + SL no MEIO é inválido:
        #     o stop ficaria além do nível de entrada (risco negativo).
        if (self.entry.level_mode == EntryLevelMode.OPPOSITE_EXTREME
                and self.stop.level_mode == SLLevelMode.MID):
            raise ValueError(
                "entry.level_mode=opposite_extreme + stop.level_mode=mid: "
                "o stop ficaria além do nível de entrada"
            )

        # (2) Entrada no MEIO + SL no MEIO exige offsets que os separem.
        if (self.entry.level_mode == EntryLevelMode.MID
                and self.stop.level_mode == SLLevelMode.MID
                and (self.entry.level_offset_points
                     + self.stop.level_offset_points) <= 0):
            raise ValueError(
                "entry=mid + stop=mid exige entry.level_offset_points + "
                "stop.level_offset_points > 0 (senão SL = entrada)"
            )

        return self


#+------------------------------------------------------------------+
#| Loader                                                           |
#+------------------------------------------------------------------+
def load_preset(path: str | Path) -> StdDevV510Preset:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return StdDevV510Preset.model_validate(raw)