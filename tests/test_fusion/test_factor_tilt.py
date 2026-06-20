"""因子倾斜 compute_factor_tilt 单测。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.fusion.factor_tilt import compute_factor_tilt


def _panel(n: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    codes = [f"{i:06d}" for i in range(n)]
    return pd.DataFrame(
        {
            "pe_ttm": rng.uniform(5, 60, n),
            "roe": rng.uniform(-5, 30, n),
            "profit_yoy": rng.uniform(-40, 60, n),
            "mom60": rng.uniform(-0.3, 0.5, n),
            "size": rng.uniform(20, 26, n),
            "sector": rng.choice(["金融", "医药", "消费"], n),
        },
        index=codes,
    )


def test_tilt_returns_zero_for_tiny_sample() -> None:
    small = _panel(5)
    out = compute_factor_tilt(small)
    assert (out == 0).all()


def test_tilt_favors_cheap_highroe_growth_reversal() -> None:
    panel = _panel(30)
    # 造一只"理想票":低PE、高ROE、高成长、近期下跌(反转买点)
    panel.loc["999999"] = {"pe_ttm": 6.0, "roe": 35.0, "profit_yoy": 80.0, "mom60": -0.25, "size": 23.0, "sector": "消费"}
    # 造一只"最差票":高PE、负ROE、负增长、近期暴涨
    panel.loc["888888"] = {"pe_ttm": 90.0, "roe": -10.0, "profit_yoy": -50.0, "mom60": 0.6, "size": 23.0, "sector": "消费"}
    tilt = compute_factor_tilt(panel)
    assert tilt["999999"] > tilt.median()
    assert tilt["888888"] < tilt.median()
    assert tilt["999999"] > tilt["888888"]


def test_tilt_handles_missing_factor_columns() -> None:
    # 只有价值因子可用(其它列缺) → 不报错，仍按 1/PE 给出方向
    panel = _panel(20)[["pe_ttm", "size", "sector"]]
    tilt = compute_factor_tilt(panel)
    assert len(tilt) == 20
    cheap = panel["pe_ttm"].idxmin()
    assert tilt[cheap] > tilt.median()
