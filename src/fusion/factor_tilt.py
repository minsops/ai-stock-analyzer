"""因子倾斜(路线B落地)。

把综合分向一组经 IC 研究验证的弱而稳因子倾斜:
  价值(1/PE) + 质量(ROE) + 成长(净利同比) + 反转(60日)。
都做【行业 + 市值中性化】后取截面 z-score、方向对齐后等权相加，得到每只股票的"因子组合 z"。
ranker 在排序前把 `FACTOR_TILT_STRENGTH × clip(z, -3, 3)` 加到综合分上。

依据:`scripts/factor_research.py`(组合样本外 IC≈+0.035) + `scripts/factor_tilt_backtest.py`
(月度回测净成本后 年化/夏普/回撤均改善)。因子在同段样本选出，存在过拟合风险，故默认温和。
市值代理 = ln(成交额/换手率) ≈ ln(流通市值)(无总股本时的近似，中性化用足够)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _neutralize(factor: pd.Series, size: pd.Series, sector: pd.Series) -> pd.Series:
    df = pd.DataFrame({"f": factor, "size": size, "sector": sector}).dropna(subset=["f"])
    if df.empty:
        return df["f"]
    df["f"] = df.groupby(df["sector"].fillna("NA"))["f"].transform(lambda x: x - x.mean())
    sub = df.dropna(subset=["size"])
    if len(sub) > 10 and sub["size"].std() > 1e-9:
        slope, intercept = np.polyfit(sub["size"].to_numpy(), sub["f"].to_numpy(), 1)
        df.loc[sub.index, "f"] = sub["f"] - (slope * sub["size"] + intercept)
    return df["f"]


def _zscore(series: pd.Series) -> pd.Series:
    s = series.dropna()
    if s.std(ddof=0) < 1e-12:
        return pd.Series(0.0, index=s.index)
    return ((s - s.mean()) / s.std(ddof=0)).clip(-3, 3)


def compute_factor_tilt(panel: pd.DataFrame) -> pd.Series:
    """输入按 code 索引的截面 DataFrame，列(缺则跳过该因子):
        pe_ttm, roe, profit_yoy, mom60(60日涨幅), size(市值代理), sector。
    返回每 code 的因子组合 z(已对齐方向，大=更看好)。样本太小时返回全 0。
    """
    if panel is None or panel.empty or len(panel) < 15:
        return pd.Series(0.0, index=panel.index if panel is not None else None, dtype=float)
    size = panel["size"] if "size" in panel else pd.Series(np.nan, index=panel.index)
    sector = panel["sector"] if "sector" in panel else pd.Series("NA", index=panel.index)
    raw_factors = {
        "earnings_yield": (1.0 / panel["pe_ttm"].replace(0, np.nan)) if "pe_ttm" in panel else None,
        "roe": panel["roe"] if "roe" in panel else None,
        "profit_yoy": panel["profit_yoy"] if "profit_yoy" in panel else None,
        "reversal60": -panel["mom60"] if "mom60" in panel else None,  # 60日反转:涨多→负向
    }
    parts: list[pd.Series] = []
    for raw in raw_factors.values():
        if raw is None or pd.to_numeric(raw, errors="coerce").dropna().empty:
            continue
        parts.append(_zscore(_neutralize(pd.to_numeric(raw, errors="coerce"), size, sector)))
    if not parts:
        return pd.Series(0.0, index=panel.index, dtype=float)
    combo = pd.concat(parts, axis=1).sum(axis=1, min_count=1)
    return combo.reindex(panel.index).fillna(0.0)
