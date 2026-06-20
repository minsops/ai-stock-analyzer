#!/usr/bin/env python
"""路线 B · 因子 IC 研究框架。

从本地库构建一个较完整的因子库，做【行业 + 市值中性化】，计算 rank-IC 的时间序列
(均值/IC_IR/t 值/正比例/多空价差)，并按时间切【滚动样本外】检验稳健性；最后用
样本内 IC 加权把稳健因子组成一个组合分，在样本外评估，和等权组合、最优单因子对比。

目标：找出 |IC|>0.03 且方向稳健(各子窗口同号)的因子，作为重建综合分的依据。
A 股这段样本传统因子普遍偏弱(见 HANDOFF §4)，本框架就是用来把"哪个因子还有微弱真信号、
哪个纯噪声"量化讲清楚，而不是靠调参自欺。

市值代理：本库不存总股本，用 ln(成交额/换手率) ≈ ln(流通市值)(差一个常数，中性化用足够)。

用法:
    python scripts/factor_research.py                 # 默认窗口
    python scripts/factor_research.py 2023-07-01 2026-06-10
    python scripts/factor_research.py --with-composite  # 额外对比现综合分 IC(较慢)
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

FWD, STEP, WARMUP = 20, 5, 125  # 未来20日收益；每5个交易日采样；动量预热125日
# 稳健判据(decay-aware)：全期 |IC| 达标 + 显著 + **两个半段各自都有同号信号**。
# 比单看全期 |IC| 更严：能排除"上半段很强、下半段衰减到 0 或翻转"的市况型因子
# (如 lowvol 后半翻负、lottery 后半≈0)，留下方向真正稳定的弱信号。
ROBUST_IC = 0.025               # 全期 |IC均值| 下限
ROBUST_HALF = 0.012             # 每个半段 |IC| 下限(低于=该段没信号)
ROBUST_T = 2.0                  # |t 值| 下限(显著性)


def neutralize(factor: pd.Series, size: pd.Series, sector: pd.Series) -> pd.Series:
    """行业 + 市值中性化:先按行业去均值，再对市值代理做 OLS 取残差。"""
    df = pd.DataFrame({"f": factor, "size": size, "sector": sector}).dropna(subset=["f"])
    if df.empty:
        return df["f"]
    # 行业内去均值(行业中性)
    df["f"] = df.groupby(df["sector"].fillna("NA"))["f"].transform(lambda x: x - x.mean())
    # 对市值代理回归取残差(市值中性)
    sub = df.dropna(subset=["size"])
    if len(sub) > 10 and sub["size"].std() > 1e-9:
        slope, intercept = np.polyfit(sub["size"].to_numpy(), sub["f"].to_numpy(), 1)
        df.loc[sub.index, "f"] = sub["f"] - (slope * sub["size"] + intercept)
    return df["f"]


def zscore(series: pd.Series) -> pd.Series:
    """截面 z-score + 去极值(±3)。"""
    s = series.dropna()
    if s.std(ddof=0) < 1e-12:
        return pd.Series(0.0, index=s.index)
    z = (s - s.mean()) / s.std(ddof=0)
    return z.clip(-3, 3)


def rank_ic(x: pd.Series, y: pd.Series) -> float | None:
    df = pd.concat([x, y], axis=1, keys=["x", "y"]).dropna()
    if len(df) < 50 or df["x"].nunique() < 5:
        return None
    return float(df["x"].rank().corr(df["y"].rank()))


def ls_spread(x: pd.Series, y: pd.Series) -> float | None:
    df = pd.concat([x, y], axis=1, keys=["x", "y"]).dropna()
    if len(df) < 50:
        return None
    srt = df.sort_values("x", ascending=False)
    k = max(1, len(srt) // 5)
    return float(srt["y"].head(k).mean() - srt["y"].tail(k).mean())


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    start_s = args[0] if len(args) > 0 else "2023-07-01"
    end_s = args[1] if len(args) > 1 else "2026-06-10"
    with_composite = "--with-composite" in flags

    storage = DataStorage()
    sim = BacktestSimulator(storage)
    start, end = pd.to_datetime(start_s).date(), pd.to_datetime(end_s).date()

    codes = storage.get_all_active_codes()
    close = sim._load_price_panel(codes, start, end)
    if close.empty:
        print("无行情数据，请先 update-data / fetch_backtest_history。")
        return
    quotes_by_code = sim._load_quotes_by_code(close.columns, end)
    sectors = sim._load_stock_sectors(close.columns)
    dates = list(close.index)

    def panel(field: str) -> pd.DataFrame:
        cols = {}
        for code, q in quotes_by_code.items():
            qq = q.copy()
            qq["d"] = pd.to_datetime(qq["trade_date"]).dt.date
            cols[code] = pd.to_numeric(qq.set_index("d")[field], errors="coerce")
        return pd.DataFrame(cols).reindex(dates)

    ret = close.pct_change()
    turn = panel("turnover")
    amt = panel("amount")
    # 市值代理 = ln(20日均成交额 / 20日均换手率) ≈ ln(流通市值)(差常数)
    size_panel = np.log((amt.rolling(20).mean()) / (turn.rolling(20).mean().replace(0, np.nan)))
    # Amihud 非流动性 = 平均(|日收益| / 成交额)，越大=越不流动(小盘代理)
    amihud_panel = (ret.abs() / amt.replace(0, np.nan)).rolling(20).mean()

    # 财务历史(point-in-time 用 searchsorted)
    fin_arrays: dict[str, tuple] = {}
    for code in close.columns:
        df = storage.get_financial_history(code)
        if df.empty:
            continue
        df = df.sort_values("report_date")
        rd = pd.to_datetime(df["report_date"]).to_numpy()
        fin_arrays[code] = (rd, df.reset_index(drop=True))

    def fundamental(field: str, day) -> pd.Series:
        """每只取 report_date≤day 的【最近一个非空】值(point-in-time，前向填充)。

        财务表里估值行(月度)与季度基本面行交错，基本面列在估值行上是 NaN，故不能只看
        最近一行，必须取最近的非空值。"""
        day64 = np.datetime64(pd.Timestamp(day))
        out: dict[str, float] = {}
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

    # 因子定义:返回"原始截面值"，全部已调向(大=预期收益高)。lambda(i, day)->Series
    def f_price(expr):
        return lambda i, day: expr(i)

    factor_defs: dict[str, callable] = {
        # 量价/技术
        "rev5": f_price(lambda i: -(close.iloc[i] / close.iloc[i - 5] - 1)),
        "rev20": f_price(lambda i: -(close.iloc[i] / close.iloc[i - 20] - 1)),
        "mom60": f_price(lambda i: close.iloc[i] / close.iloc[i - 60] - 1),
        "mom120": f_price(lambda i: close.iloc[i] / close.iloc[i - 120] - 1),
        "lowvol": f_price(lambda i: -ret.iloc[i - 20:i].std()),
        "lottery": f_price(lambda i: -ret.iloc[i - 20:i].max()),
        "lowturn": f_price(lambda i: -turn.iloc[i - 20:i].mean()),
        "illiq_amt": f_price(lambda i: -amt.iloc[i - 20:i].mean()),
        "amihud": f_price(lambda i: amihud_panel.iloc[i]),
        # 基本面质量/成长/估值(point-in-time)
        "roe": lambda i, day: fundamental("roe", day),
        "profit_yoy": lambda i, day: fundamental("profit_yoy", day),
        "revenue_yoy": lambda i, day: fundamental("revenue_yoy", day),
        "gross_margin": lambda i, day: fundamental("gross_margin", day),
        "low_debt": lambda i, day: -fundamental("debt_ratio", day),
        "earnings_yield": lambda i, day: (1.0 / fundamental("pe_ttm", day).replace(0, np.nan)),
        "book_to_price": lambda i, day: (1.0 / fundamental("pb", day).replace(0, np.nan)),
    }

    names = list(factor_defs)
    records: dict[str, list[dict]] = {n: [] for n in names}
    # 组合用:逐期保存"中性化后的 z 因子"和 fwd，便于事后按权重合成
    neutral_z: dict[str, dict] = {}   # date_i -> {factor: zSeries}
    fwd_by_i: dict[int, pd.Series] = {}
    composite_ic: list[tuple] = []

    sample_idx = range(WARMUP, len(dates) - FWD - 1, STEP)
    for i in sample_idx:
        day = dates[i]
        fwd = close.iloc[i + FWD] / close.iloc[i] - 1
        fwd_by_i[i] = fwd
        size_i = size_panel.iloc[i]
        sector_i = pd.Series(sectors)
        neutral_z[i] = {}
        for name, fn in factor_defs.items():
            try:
                raw = fn(i, day)
            except Exception:  # noqa: BLE001 - 单因子单期失败不影响整体
                continue
            if raw is None or (hasattr(raw, "empty") and raw.empty):
                continue
            neu = neutralize(raw.astype(float), size_i, sector_i)
            ic = rank_ic(neu, fwd)
            if ic is None:
                continue
            sp = ls_spread(neu, fwd)
            records[name].append({"date": day, "ic": ic, "spread": sp if sp is not None else np.nan})
            neutral_z[i][name] = zscore(neu)

        if with_composite:
            financials = {c: storage.get_financial_history(c) for c in close.columns}
            ranked = sim._composite_scores(
                close.loc[:day], quotes_by_code, financials, sectors,
                storage.get_all_industry_history(), day, "shock",
            )
            if not ranked.empty:
                score = ranked["composite_score"] if "composite_score" in ranked else ranked.iloc[:, 0]
                ic = rank_ic(score, fwd)
                if ic is not None:
                    composite_ic.append((day, ic))

    # ---- 汇总每个因子的 IC 统计 + 滚动样本外(按时间切两半) ----
    all_dates = sorted({r["date"] for n in names for r in records[n]})
    if not all_dates:
        print("样本不足，无法计算 IC。")
        return
    mid = all_dates[len(all_dates) // 2]

    def stats(rows: list[dict]) -> dict:
        ic = pd.Series([r["ic"] for r in rows], dtype=float)
        sp = pd.Series([r["spread"] for r in rows], dtype=float).dropna()
        n = len(ic)
        ir = ic.mean() / ic.std(ddof=0) if n > 1 and ic.std(ddof=0) > 1e-12 else 0.0
        t = ir * np.sqrt(n) if n > 1 else 0.0
        h1 = pd.Series([r["ic"] for r in rows if r["date"] <= mid], dtype=float)
        h2 = pd.Series([r["ic"] for r in rows if r["date"] > mid], dtype=float)
        return {
            "n": n, "ic": ic.mean(), "ir": ir, "t": t, "pos": (ic > 0).mean(),
            "spread": sp.mean() if len(sp) else np.nan,
            "ic_h1": h1.mean() if len(h1) else np.nan,
            "ic_h2": h2.mean() if len(h2) else np.nan,
        }

    table = {n: stats(records[n]) for n in names if records[n]}
    ordered = sorted(table.items(), key=lambda kv: abs(kv[1]["ic"]), reverse=True)

    print(f"\n=== 因子 IC 研究 (未来{FWD}日, 每{STEP}日采样, {start_s}~{end_s}, 行业+市值中性化) ===")
    print(f"样本期数 ≈ {len(all_dates)}  | 中点 {mid}  | 稳健判据: |IC|>{ROBUST_IC} 且 |t|>{ROBUST_T} 且两半各自|IC|>{ROBUST_HALF}同号")
    print(f"{'因子':<14}{'IC均值':>9}{'IC_IR':>8}{'t值':>7}{'正比例':>8}{'多空价差':>10}{'前半IC':>9}{'后半IC':>9}{'稳健':>6}")
    robust: list[str] = []
    for name, s in ordered:
        h1, h2 = s["ic_h1"], s["ic_h2"]
        both_signal = (
            not np.isnan(h1) and not np.isnan(h2)
            and np.sign(h1) == np.sign(h2)
            and abs(h1) > ROBUST_HALF and abs(h2) > ROBUST_HALF
        )
        is_robust = abs(s["ic"]) > ROBUST_IC and abs(s["t"]) > ROBUST_T and both_signal
        if is_robust:
            robust.append(name)
        sp = f"{s['spread']:+.2%}" if not np.isnan(s["spread"]) else "   -"
        print(f"{name:<14}{s['ic']:>+9.3f}{s['ir']:>+8.2f}{s['t']:>+7.1f}{s['pos']:>8.0%}{sp:>10}"
              f"{s['ic_h1']:>+9.3f}{s['ic_h2']:>+9.3f}{'  ✓' if is_robust else '   ':>6}")

    # ---- 组合因子:用前半样本 IC 当权重，在后半样本(真·样本外)评估 ----
    print(f"\n稳健因子(|IC|>{ROBUST_IC} & 稳定): {robust if robust else '无 —— 该样本下传统因子均不稳健(与 HANDOFF §4 一致)'}")

    weight_src = robust if robust else [n for n, _ in ordered[:5]]  # 没有稳健因子时退而用|IC|最大的前5个看上限
    weights = {n: table[n]["ic_h1"] for n in weight_src if not np.isnan(table[n]["ic_h1"])}

    def combo_ic(weight_map: dict, only_second_half: bool) -> dict:
        ics = []
        for i in sample_idx:
            day = dates[i]
            if only_second_half and day <= mid:
                continue
            zs = neutral_z.get(i, {})
            parts = [w * zs[n] for n, w in weight_map.items() if n in zs]
            if not parts:
                continue
            combined = pd.concat(parts, axis=1).sum(axis=1, min_count=1)
            ic = rank_ic(combined, fwd_by_i[i])
            if ic is not None:
                ics.append(ic)
        s = pd.Series(ics, dtype=float)
        ir = s.mean() / s.std(ddof=0) if len(s) > 1 and s.std(ddof=0) > 1e-12 else 0.0
        return {"n": len(s), "ic": s.mean() if len(s) else np.nan, "ir": ir}

    eq_weights = {n: np.sign(table[n]["ic_h1"]) or 1.0 for n in weight_src}
    icw = combo_ic(weights, only_second_half=True)
    eqw = combo_ic(eq_weights, only_second_half=True)
    best_name = ordered[0][0]
    best_h2 = table[best_name]["ic_h2"]

    print("\n=== 组合因子 · 样本外(后半段)对比 ===")
    print(f"  IC加权组合(权重来自前半IC)  : IC均值 {icw['ic']:+.3f}  IR {icw['ir']:+.2f}  (n={icw['n']})  权重因子={list(weights)}")
    print(f"  等权组合(同一批因子,仅对齐方向): IC均值 {eqw['ic']:+.3f}  IR {eqw['ir']:+.2f}  (n={eqw['n']})")
    print(f"  最优单因子 {best_name} 后半IC      : {best_h2:+.3f}")
    if with_composite and composite_ic:
        cs = pd.Series([x[1] for x in composite_ic], dtype=float)
        print(f"  现综合分(6引擎)全期 rank-IC   : {cs.mean():+.3f}  (n={len(cs)})")

    # ---- 落盘 CSV ----
    out_rows = []
    for name, s in ordered:
        out_rows.append({
            "factor": name, "ic_mean": round(s["ic"], 4), "ic_ir": round(s["ir"], 3),
            "t_stat": round(s["t"], 2), "ic_pos_ratio": round(s["pos"], 3),
            "ls_spread": round(s["spread"], 4) if not np.isnan(s["spread"]) else None,
            "ic_first_half": round(s["ic_h1"], 4) if not np.isnan(s["ic_h1"]) else None,
            "ic_second_half": round(s["ic_h2"], 4) if not np.isnan(s["ic_h2"]) else None,
            "robust": name in robust, "n_periods": s["n"],
        })
    out_path = PROJECT_ROOT / "data" / "factor_ic_report.csv"
    pd.DataFrame(out_rows).to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nIC 明细已写出: {out_path}")
    print(f"解读: 稳健=|IC|>{ROBUST_IC} 且 |t|>{ROBUST_T} 且两半各自|IC|>{ROBUST_HALF}同号(decay-aware);否则视为市况型/噪声。")
    print("FACTOR_RESEARCH_DONE")


if __name__ == "__main__":
    main()
