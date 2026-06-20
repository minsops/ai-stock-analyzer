#!/usr/bin/env python
"""路线 B 落地验证:把综合分向稳健因子集倾斜，回测【净收益】是否真改善。

研究(factor_research.py)发现一组弱而稳的因子:earnings_yield(低PE)+roe+profit_yoy+
mom60反转，组合样本外 IC≈+0.035。但 IC>0 不代表扣成本后能赚——本脚本做月度调仓
top-N 回测，对比:
  - baseline : 现 6 引擎综合分
  - tilt_a   : 综合分(z) + a×稳健因子组合(z)，a∈{0.5,1.0}
  - combo    : 只用稳健因子组合
  - universe : 等权全样本(beta 基准)
都按真实成本(佣金0.03%+滑点0.1%+卖出印花0.1%)，比 净收益/年化/夏普/最大回撤/胜率。
只有净收益+风险确实改善，才值得改线上评分。

用法: python scripts/factor_tilt_backtest.py [start] [end] [top_n]
"""

from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest import BacktestSimulator  # noqa: E402
from src.data_layer.storage import DataStorage  # noqa: E402

WARMUP, HOLD = 125, 20            # 预热125日；约月度调仓(20交易日)
ROUND_TRIP = 0.0003 + 0.001 + 0.0003 + 0.001 + 0.001  # 买(佣金+滑点)+卖(佣金+滑点+印花)≈0.36%
PERIODS_PER_YEAR = 244 / HOLD


def neutralize(factor: pd.Series, size: pd.Series, sector: pd.Series) -> pd.Series:
    df = pd.DataFrame({"f": factor, "size": size, "sector": sector}).dropna(subset=["f"])
    if df.empty:
        return df["f"]
    df["f"] = df.groupby(df["sector"].fillna("NA"))["f"].transform(lambda x: x - x.mean())
    sub = df.dropna(subset=["size"])
    if len(sub) > 10 and sub["size"].std() > 1e-9:
        slope, intercept = np.polyfit(sub["size"].to_numpy(), sub["f"].to_numpy(), 1)
        df.loc[sub.index, "f"] = sub["f"] - (slope * sub["size"] + intercept)
    return df["f"]


def zscore(series: pd.Series) -> pd.Series:
    s = series.dropna()
    if s.std(ddof=0) < 1e-12:
        return pd.Series(0.0, index=s.index)
    return ((s - s.mean()) / s.std(ddof=0)).clip(-3, 3)


def metrics(rets: list[float]) -> dict:
    r = pd.Series(rets, dtype=float)
    if r.empty:
        return {"total": 0.0, "ann": 0.0, "sharpe": 0.0, "mdd": 0.0, "win": 0.0}
    equity = (1 + r).cumprod()
    total = equity.iloc[-1] - 1
    ann = (1 + total) ** (PERIODS_PER_YEAR / len(r)) - 1
    sharpe = (r.mean() / r.std(ddof=0) * np.sqrt(PERIODS_PER_YEAR)) if r.std(ddof=0) > 1e-12 else 0.0
    mdd = (equity / equity.cummax() - 1).min()
    return {"total": total, "ann": ann, "sharpe": sharpe, "mdd": mdd, "win": (r > 0).mean()}


def main() -> None:
    start_s = sys.argv[1] if len(sys.argv) > 1 else "2023-07-01"
    end_s = sys.argv[2] if len(sys.argv) > 2 else "2026-06-10"
    top_n = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    storage = DataStorage()
    sim = BacktestSimulator(storage)
    start, end = pd.to_datetime(start_s).date(), pd.to_datetime(end_s).date()
    codes = storage.get_all_active_codes()
    close = sim._load_price_panel(codes, start, end)
    quotes_by_code = sim._load_quotes_by_code(close.columns, end)
    sectors = sim._load_stock_sectors(close.columns)
    financials = {c: storage.get_financial_history(c) for c in close.columns}
    industry_hist = storage.get_all_industry_history()
    dates = list(close.index)

    def panel(field: str) -> pd.DataFrame:
        cols = {}
        for code, q in quotes_by_code.items():
            qq = q.copy()
            qq["d"] = pd.to_datetime(qq["trade_date"]).dt.date
            cols[code] = pd.to_numeric(qq.set_index("d")[field], errors="coerce")
        return pd.DataFrame(cols).reindex(dates)

    turn, amt = panel("turnover"), panel("amount")
    size_panel = np.log((amt.rolling(20).mean()) / (turn.rolling(20).mean().replace(0, np.nan)))

    fin_arrays = {}
    for code in close.columns:
        df = financials.get(code)
        if df is None or df.empty:
            continue
        df = df.sort_values("report_date")
        fin_arrays[code] = (pd.to_datetime(df["report_date"]).to_numpy(), df.reset_index(drop=True))

    def fundamental(field: str, day) -> pd.Series:
        day64 = np.datetime64(pd.Timestamp(day))
        out = {}
        for code, (rd, df) in fin_arrays.items():
            if field not in df.columns:
                continue
            pos = int(np.searchsorted(rd, day64, side="right"))
            if pos <= 0:
                continue
            col = pd.to_numeric(df[field].iloc[:pos], errors="coerce").dropna()
            if not col.empty:
                out[code] = float(col.iloc[-1])
        return pd.Series(out, dtype=float)

    def combo_z(i: int, day) -> pd.Series:
        """稳健因子组合 z:价值(低PE)+质量(ROE)+成长(净利同比)+反转(60日)，方向对齐后等权。"""
        size_i, sector_i = size_panel.iloc[i], pd.Series(sectors)
        ey = 1.0 / fundamental("pe_ttm", day).replace(0, np.nan)
        roe = fundamental("roe", day)
        pyoy = fundamental("profit_yoy", day)
        rev60 = -(close.iloc[i] / close.iloc[i - 60] - 1)  # 反转:60日涨多→负
        parts = []
        for raw in (ey, roe, pyoy, rev60):
            if raw is None or raw.dropna().empty:
                continue
            parts.append(zscore(neutralize(raw.astype(float), size_i, sector_i)))
        if not parts:
            return pd.Series(dtype=float)
        return pd.concat(parts, axis=1).sum(axis=1, min_count=1)

    variants = {"baseline": 0.0, "tilt_0.5": 0.5, "tilt_1.0": 1.0, "combo_only": None}
    rets: dict[str, list[float]] = {v: [] for v in variants}
    rets["universe"] = []
    holds: dict[str, set] = {v: set() for v in variants}

    rebal = list(range(WARMUP, len(dates) - HOLD - 1, HOLD))
    for n, i in enumerate(rebal, start=1):
        day = dates[i]
        fwd = close.iloc[i + HOLD] / close.iloc[i] - 1
        rets["universe"].append(float(fwd.mean()))
        comp = sim._composite_scores(close.loc[:day], quotes_by_code, financials, sectors, industry_hist, day, "shock")
        cz = combo_z(i, day)
        comp_z = zscore(comp)
        for v, alpha in variants.items():
            if v == "combo_only":
                score = cz
            else:
                score = comp_z.add(alpha * cz, fill_value=0.0) if not cz.empty else comp_z
            sel = list(score.dropna().sort_values(ascending=False).head(top_n).index)
            if not sel:
                continue
            gross = float(fwd.reindex(sel).dropna().mean())
            turnover = len(set(sel) - holds[v]) / max(1, len(sel))
            rets[v].append(gross - turnover * ROUND_TRIP)
            holds[v] = set(sel)
        print(f"  调仓 {n}/{len(rebal)} @ {day}", flush=True)

    print(f"\n=== 因子倾斜回测 ({start_s}~{end_s}, 月度 top{top_n}, 净成本{ROUND_TRIP:.2%}/换手) ===")
    print(f"{'变体':<12}{'总收益':>10}{'年化':>9}{'夏普':>8}{'最大回撤':>10}{'胜率':>8}{'期数':>6}")
    order = ["baseline", "tilt_0.5", "tilt_1.0", "combo_only", "universe"]
    for v in order:
        m = metrics(rets[v])
        print(f"{v:<12}{m['total']:>+10.1%}{m['ann']:>+9.1%}{m['sharpe']:>+8.2f}{m['mdd']:>+10.1%}{m['win']:>8.0%}{len(rets[v]):>6}")
    base, t10 = metrics(rets["baseline"]), metrics(rets["tilt_1.0"])
    print(f"\n判定: 倾斜(tilt_1.0) vs baseline → 年化 {t10['ann']-base['ann']:+.1%}、夏普 {t10['sharpe']-base['sharpe']:+.2f}、回撤 {t10['mdd']-base['mdd']:+.1%}")
    better = t10["sharpe"] > base["sharpe"] and t10["ann"] >= base["ann"] - 0.01
    print("结论: " + ("倾斜净改善 → 值得把综合分轻度向稳健因子集倾斜。" if better else "倾斜未带来稳健净改善(弱IC被成本/噪声吞没) → 维持现状，别为这点边际加复杂度。"))
    print("FACTOR_TILT_BACKTEST_DONE")


if __name__ == "__main__":
    main()
