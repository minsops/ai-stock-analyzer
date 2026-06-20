"""因子研究框架纯函数单测(中性化/zscore/rank-IC)。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("factor_research", PROJECT_ROOT / "scripts" / "factor_research.py")
fr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fr)


def test_neutralize_removes_industry_mean() -> None:
    # 两个行业各自有不同基线，中性化后行业内均值应≈0
    factor = pd.Series({"a": 10.0, "b": 12.0, "c": 1.0, "d": 3.0})
    sector = pd.Series({"a": "X", "b": "X", "c": "Y", "d": "Y"})
    size = pd.Series({"a": np.nan, "b": np.nan, "c": np.nan, "d": np.nan})  # 无市值→只做行业中性
    out = fr.neutralize(factor, size, sector)
    assert abs(out[["a", "b"]].mean()) < 1e-9
    assert abs(out[["c", "d"]].mean()) < 1e-9
    # 行业内相对排序保留(b>a, d>c)
    assert out["b"] > out["a"] and out["d"] > out["c"]


def test_neutralize_orthogonal_to_size() -> None:
    # factor 与 size 完全线性相关 → 中性化后残差应≈0(需 >10 个点触发市值回归)
    codes = [f"c{i}" for i in range(15)]
    size = pd.Series({c: float(i) for i, c in enumerate(codes)})
    factor = 2.0 * size + 5.0
    sector = pd.Series({c: "X" for c in codes})
    out = fr.neutralize(factor, size, sector)
    assert out.abs().max() < 1e-6


def test_zscore_clips_and_standardizes() -> None:
    z = fr.zscore(pd.Series([1.0, 2.0, 3.0, 4.0, 100.0]))
    assert z.max() <= 3.0 + 1e-9
    assert abs(z.mean()) < 5.0  # 不报错、有限值


def test_rank_ic_perfect_and_insufficient() -> None:
    n = 60
    x = pd.Series(range(n), index=[f"c{i}" for i in range(n)], dtype=float)
    y = x * 3 + 1  # 单调 → 秩相关=1
    assert abs(fr.rank_ic(x, y) - 1.0) < 1e-9
    # 样本不足 → None
    assert fr.rank_ic(x.head(10), y.head(10)) is None
