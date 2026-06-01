from __future__ import annotations

from src.risk import PositionSizer


def test_position_sizer_caps_single_position() -> None:
    result = PositionSizer().suggest("000001", 90, "shock", 100_000)

    assert result["suggested_pct"] <= result["max_allowed_pct"]
    assert result["suggested_amount"] <= 20_000
