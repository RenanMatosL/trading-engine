"""Golden tests do preset v5.10 (pydantic + validadores cruzados).

Cobre:
  - bounds básicos de cada seção (ge/gt);
  - regras de coerência do OnInit() do EA v4.60;
  - round-trip YAML -> preset -> dict.
"""
from __future__ import annotations

from datetime import time

import pytest
from pydantic import ValidationError

from engine.config.presets import (
    CandidateMode,
    DetectorParams,
    EntryLevelMode,
    EntryParams,
    PartialTier,
    RegionsParams,
    RiskParams,
    SLLevelMode,
    SessionParams,
    SizingMode,
    StdDevV510Preset,
    StopParams,
    TakeProfitParams,
    TimeWindowParams,
)


def _minimal() -> dict:
    """Preset mínimo válido — base para os testes que só testam UM campo."""
    return {"name": "test", "strategy": "stddev_v510"}


#+------------------------------------------------------------------+
#| DetectorParams                                                   |
#+------------------------------------------------------------------+
def test_detector_defaults():
    p = DetectorParams()
    assert p.length == 180
    assert p.std_ref == 4.0
    assert p.mute_open_min == 10
    assert p.use_big_candle_rule is True
    assert p.big_candle_min_range == 400.0
    assert p.big_candle_entry_offset == 200.0


def test_detector_length_menor_que_2_rejeitado():
    with pytest.raises(ValidationError):
        DetectorParams(length=1)


def test_detector_std_ref_nao_positivo_rejeitado():
    with pytest.raises(ValidationError):
        DetectorParams(std_ref=0.0)


def test_detector_timeframe_invalido_rejeitado():
    with pytest.raises(ValidationError):
        DetectorParams(timeframe="D1")


def test_detector_big_candle_offset_maior_que_range_rejeitado():
    with pytest.raises(ValidationError):
        DetectorParams(big_candle_min_range=300.0, big_candle_entry_offset=400.0)


def test_detector_big_candle_sl_adjust_muito_negativo_rejeitado():
    with pytest.raises(ValidationError):
        DetectorParams(big_candle_entry_offset=200.0, big_candle_sl_adjust=-200.0)


def test_detector_big_candle_regra_desligada_ignora_validacoes():
    # Se use_big_candle_rule=False, os bounds não se aplicam.
    p = DetectorParams(
        use_big_candle_rule=False,
        big_candle_min_range=100.0,
        big_candle_entry_offset=1000.0,
    )
    assert p.big_candle_entry_offset == 1000.0


#+------------------------------------------------------------------+
#| SessionParams                                                    |
#+------------------------------------------------------------------+
def test_session_defaults():
    s = SessionParams()
    assert s.window.start == time(9, 0)
    assert s.window.end == time(17, 30)
    assert s.carry_entry_delay_min == 15
    assert s.breakout_ttl_min == 60
    assert s.cooldown_after_sl_min == 10
    assert s.max_trades_day == 3
    assert s.use_entry_block is True
    assert s.entry_block.start == time(10, 0)
    assert s.entry_block.end == time(11, 0)


def test_session_entry_block_vazio_rejeitado_quando_ligado():
    with pytest.raises(ValidationError):
        SessionParams(
            use_entry_block=True,
            entry_block=TimeWindowParams(start=time(10, 0), end=time(10, 0)),
        )


def test_session_entry_block_vazio_aceito_quando_desligado():
    s = SessionParams(
        use_entry_block=False,
        entry_block=TimeWindowParams(start=time(10, 0), end=time(10, 0)),
    )
    assert s.use_entry_block is False


def test_session_max_trades_zero_aceito():
    # 0 = sem limite no EA
    s = SessionParams(max_trades_day=0)
    assert s.max_trades_day == 0


#+------------------------------------------------------------------+
#| RiskParams — parciais                                            |
#+------------------------------------------------------------------+
def test_risk_defaults():
    r = RiskParams()
    assert r.sizing_mode == SizingMode.FIXED_CONTRACTS
    assert r.total_contracts == 6
    assert r.use_partial_exit is False  # default do EA
    assert r.use_reentry is False


def test_risk_parciais_ligadas_sem_tiers_ativos_rejeitado():
    with pytest.raises(ValidationError):
        RiskParams(
            use_partial_exit=True,
            tiers=[
                PartialTier(contracts=0, points=200.0),
                PartialTier(contracts=0, points=400.0),
                PartialTier(contracts=0, points=600.0),
            ],
        )


def test_risk_parciais_soma_maior_igual_total_rejeitado():
    with pytest.raises(ValidationError):
        RiskParams(
            use_partial_exit=True,
            total_contracts=6,
            tiers=[
                PartialTier(contracts=3, points=200.0),
                PartialTier(contracts=3, points=400.0),
                PartialTier(contracts=0, points=600.0),
            ],
        )


def test_risk_parciais_pontos_nao_crescentes_rejeitado():
    with pytest.raises(ValidationError):
        RiskParams(
            use_partial_exit=True,
            total_contracts=10,
            tiers=[
                PartialTier(contracts=2, points=400.0),
                PartialTier(contracts=2, points=200.0),   # menor que o anterior
                PartialTier(contracts=0, points=600.0),
            ],
        )


def test_risk_parciais_validas():
    r = RiskParams(
        use_partial_exit=True,
        total_contracts=6,
        tiers=[
            PartialTier(contracts=2, points=200.0),
            PartialTier(contracts=2, points=400.0),
            PartialTier(contracts=1, points=600.0),
        ],
    )
    assert r.use_partial_exit is True


def test_risk_parciais_exit_points_exige_partial_points():
    with pytest.raises(ValidationError):
        RiskParams(
            use_partial_exit=True,
            total_contracts=6,
            partial_points=0.0,
            tiers=[PartialTier(contracts=2, points=200.0)],
        )


#+------------------------------------------------------------------+
#| StdDevV510Preset — validadores cruzados                          |
#+------------------------------------------------------------------+
def test_preset_minimo_valido():
    p = StdDevV510Preset.model_validate(_minimal())
    assert p.strategy == "stddev_v510"
    assert p.entry.level_mode == EntryLevelMode.DEFAULT
    assert p.stop.level_mode == SLLevelMode.DEFAULT


def test_preset_nome_vazio_rejeitado():
    with pytest.raises(ValidationError):
        StdDevV510Preset.model_validate({"name": "  ", "strategy": "stddev_v510"})


def test_preset_strategy_invalida_rejeitada():
    with pytest.raises(ValidationError):
        StdDevV510Preset.model_validate({"name": "x", "strategy": "outra"})


def test_preset_entry_opposite_mais_sl_mid_rejeitado():
    with pytest.raises(ValidationError, match="opposite_extreme"):
        StdDevV510Preset.model_validate({
            **_minimal(),
            "entry": {"level_mode": "opposite_extreme"},
            "stop": {"level_mode": "mid"},
        })


def test_preset_entry_mid_mais_sl_mid_com_offsets_zero_rejeitado():
    with pytest.raises(ValidationError, match="offsets que os separem|SL = entrada"):
        StdDevV510Preset.model_validate({
            **_minimal(),
            "entry": {"level_mode": "mid", "level_offset_points": 0.0},
            "stop": {"level_mode": "mid", "level_offset_points": 0.0},
        })


def test_preset_entry_mid_mais_sl_mid_com_offsets_positivos_aceito():
    p = StdDevV510Preset.model_validate({
        **_minimal(),
        "entry": {"level_mode": "mid", "level_offset_points": 50.0},
        "stop": {"level_mode": "mid", "level_offset_points": 50.0},
    })
    assert p.entry.level_mode == EntryLevelMode.MID
    assert p.stop.level_mode == SLLevelMode.MID


def test_preset_completo_valido():
    """Preset com todas as seções preenchidas — sanidade geral."""
    p = StdDevV510Preset.model_validate({
        "name": "v510_full",
        "strategy": "stddev_v510",
        "detector": {
            "length": 180, "std_ref": 4.0, "volume_source": "tick",
            "timeframe": "M1", "mute_open_min": 10,
        },
        "session": {
            "window": {"start": "09:00:00", "end": "17:30:00"},
            "carry_entry_delay_min": 15,
            "breakout_ttl_min": 60,
            "cooldown_after_sl_min": 10,
            "max_trades_day": 3,
            "use_entry_block": True,
            "entry_block": {"start": "10:00:00", "end": "11:00:00"},
        },
        "entry": {"level_mode": "default", "as_pending": True, "max_entry_gap_points": 100},
        "stop": {"level_mode": "default", "sl_points": 200.0},
        "take_profit": {"use_final_tp": True, "final_tp_points": 600.0},
        "risk": {"sizing_mode": "fixed_contracts", "total_contracts": 6,
                 "lot_per_contract": 1.0},
        "regions": {"max_loc": 12, "valid_days": 2,
                    "candidate_mode": "highest_volume"},
    })
    assert p.session.max_trades_day == 3
    assert p.regions.max_loc == 12
    assert p.regions.candidate_mode == CandidateMode.HIGHEST_VOLUME


def test_preset_round_trip_dict():
    """model_dump(mode='json') deve funcionar para serializar de volta."""
    p = StdDevV510Preset.model_validate(_minimal())
    d = p.model_dump(mode="json")
    assert d["name"] == "test"
    assert d["strategy"] == "stddev_v510"
    assert d["detector"]["length"] == 180