from __future__ import annotations

from src.risk import PositionSizer


def test_position_sizer_caps_single_position() -> None:
    result = PositionSizer().suggest("000001", 90, "shock", 100_000)

    assert result["suggested_pct"] <= result["max_allowed_pct"]
    assert result["suggested_amount"] <= 20_000


def test_position_sizer_uses_confirmed_regime_caps() -> None:
    sizer = PositionSizer()

    assert sizer.suggest("000001", 100, "bull", 100_000)["regime_total_cap"] == 0.8
    assert sizer.suggest("000001", 100, "shock", 100_000)["regime_total_cap"] == 0.6
    assert sizer.suggest("000001", 100, "bear", 100_000)["regime_total_cap"] == 0.4
    assert sizer.suggest("000001", 100, "extreme_fear", 100_000)["regime_total_cap"] == 0.2
    assert sizer.suggest("000001", 100, "extreme_greed", 100_000)["regime_total_cap"] == 0.5


def test_position_sizer_caps_same_industry() -> None:
    result = PositionSizer().suggest(
        "000001",
        composite_score=100,
        regime="bull",
        total_capital=100_000,
        current_positions={"600000": {"pct": 0.35, "industry": "银行"}},
        industry="银行",
    )

    assert result["suggested_pct"] == 0.05
    assert result["suggested_amount"] == 5_000
    assert "同行业仓位接近上限" in result["warnings"]


def test_position_sizer_caps_total_exposure_before_industry() -> None:
    result = PositionSizer().suggest(
        "000001",
        composite_score=100,
        regime="shock",
        total_capital=100_000,
        current_positions={
            "600000": {"pct": 0.3, "industry": "银行"},
            "600519": {"pct": 0.25, "industry": "白酒"},
        },
        industry="银行",
    )

    assert result["suggested_pct"] == 0.05
    assert "当前总仓位接近市场状态上限" in result["warnings"]
