#!/usr/bin/env python
"""逐引擎 IC 体检：每个引擎单独对未来 20 日收益的预测力(IC + 多空价差)。

回答"哪个因子有真信号、哪个是噪声"，为按 IC 重建综合分提供依据。
每周(每5交易日)采样，point-in-time 构造各引擎输入。
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
from src.engines import CapitalEngine, EventEngine, IndustryEngine, NewsEngine, TrendEngine, ValueEngine  # noqa: E402

START, END, FWD, STEP = "2023-07-01", "2026-06-10", 20, 5


def main() -> None:
    storage = DataStorage()
    sim = BacktestSimulator(storage)
    start, end = pd.to_datetime(START).date(), pd.to_datetime(END).date()
    prices = sim._load_price_panel(storage.get_all_active_codes(), start, end)
    quotes_by_code = sim._load_quotes_by_code(prices.columns, end)
    financials = {c: storage.get_financial_history(c) for c in prices.columns}
    sectors = sim._load_stock_sectors(prices.columns)
    industry_hist = storage.get_all_industry_history()
    engines = [ValueEngine(), TrendEngine(), CapitalEngine(), IndustryEngine(), EventEngine(), NewsEngine()]
    dates = list(prices.index)

    ic: dict[str, list[float]] = {e.name: [] for e in engines}
    spread: dict[str, list[float]] = {e.name: [] for e in engines}
    cover: dict[str, list[int]] = {e.name: [] for e in engines}

    for i in range(60, len(dates) - FWD - 1, STEP):
        day = dates[i]
        ind_ret, ind_rank = sim._industry_strength_asof(industry_hist, day)
        fwd: dict[str, float] = {}
        eng_scores: dict[str, dict[str, float]] = {e.name: {} for e in engines}
        for code in prices.columns:
            q = quotes_by_code.get(code)
            if q is None:
                continue
            pit = q[pd.to_datetime(q["trade_date"]).dt.date <= day]
            if len(pit) < 60:
                continue
            p0, p1 = prices[code].iloc[i], prices[code].iloc[i + FWD]
            if pd.isna(p0) or pd.isna(p1) or p0 <= 0:
                continue
            fwd[code] = p1 / p0 - 1
            fh = sim._slice_financials(financials.get(code), day)
            fin = fh.iloc[-1].to_dict() if not fh.empty else {}
            sector = sectors.get(code)
            ictx = {"return_20d": ind_ret[sector], "rank_percentile": ind_rank[sector]} if sector in ind_ret else {}
            ctx = {"stock_info": {"code": code, "industry_l1": sector}, "quotes": pit, "financial": fin,
                   "financial_history": fh, "capital": pd.DataFrame(), "industry": ictx, "news": []}
            for e in engines:
                r = e.score(code, ctx)
                if r.available:
                    eng_scores[e.name][code] = r.score
        for e in engines:
            scores = eng_scores[e.name]
            common = [c for c in scores if c in fwd]
            cover[e.name].append(len(common))
            if len(common) < 40:
                continue
            s = pd.Series({c: scores[c] for c in common})
            f = pd.Series({c: fwd[c] for c in common})
            if s.nunique() < 5:
                continue
            val = s.rank().corr(f.rank())  # spearman(无scipy)
            if pd.notna(val):
                ic[e.name].append(float(val))
            srt = s.sort_values(ascending=False)
            k = max(1, len(srt) // 5)
            spread[e.name].append(float(f[srt.head(k).index].mean() - f[srt.tail(k).index].mean()))

    print(f"\n=== 逐引擎 IC 体检 (未来{FWD}日, 每{STEP}日采样, {START}~{END}) ===")
    print(f"{'引擎':<10}{'平均覆盖股':>10}{'IC均值':>10}{'IC正占比':>10}{'多空价差':>10}")
    for e in engines:
        cov = int(np.mean(cover[e.name])) if cover[e.name] else 0
        if not ic[e.name]:
            print(f"{e.name:<10}{cov:>10}{'无数据':>10}{'-':>10}{'-':>10}")
            continue
        arr = pd.Series(ic[e.name])
        sp = np.mean(spread[e.name]) if spread[e.name] else 0
        print(f"{e.name:<10}{cov:>10}{arr.mean():>+10.3f}{(arr>0).mean():>10.1%}{sp:>+10.2%}")
    print("\n说明: IC|>0.03 才算有用; 多空价差=该因子前20%减后20%的未来20日收益; 资金为量价代理, 消息面回测期无历史。")
    print("ENGINE_IC_DONE")


if __name__ == "__main__":
    main()
