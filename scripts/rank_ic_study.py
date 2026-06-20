#!/usr/bin/env python
"""排名预测力检验：综合评分的高排名股票，是否真的对应高远期收益(挣钱的票是否在前列)。

每周(每5个交易日)对全样本评分排名，分桶看各桶未来 20 个交易日收益；
并统计 Spearman 排名 IC，以及"真实大赢家(未来20日涨幅前5%)"有多少落在评分 Top10/Top50。
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

START, END, FWD, STEP = "2023-07-01", "2026-06-10", 20, 5
BUCKETS = [("Top10", 0, 10), ("11-30", 10, 30), ("31-60", 30, 60), ("61-100", 60, 100), ("101-200", 100, 200), ("200+", 200, 10**9)]


def main() -> None:
    storage = DataStorage()
    sim = BacktestSimulator(storage)
    start, end = pd.to_datetime(START).date(), pd.to_datetime(END).date()
    prices = sim._load_price_panel(storage.get_all_active_codes(), start, end)
    quotes_by_code = sim._load_quotes_by_code(prices.columns, end)
    financials = {c: storage.get_financial_history(c) for c in prices.columns}
    sectors = sim._load_stock_sectors(prices.columns)
    industry_hist = storage.get_all_industry_history()
    dates = list(prices.index)

    bucket_ret: dict[str, list[float]] = {b[0]: [] for b in BUCKETS}
    ics: list[float] = []
    cap10: list[float] = []
    cap50: list[float] = []

    for i in range(60, len(dates) - FWD - 1, STEP):
        day = dates[i]
        ranked = sim._composite_scores(prices.loc[:day], quotes_by_code, financials, sectors, industry_hist, day, "shock")
        if ranked.empty:
            continue
        codes = list(ranked.index)
        fwd = {}
        for c in codes:
            p0, p1 = prices[c].iloc[i], prices[c].iloc[i + FWD]
            if pd.notna(p0) and pd.notna(p1) and p0 > 0:
                fwd[c] = p1 / p0 - 1
        codes = [c for c in codes if c in fwd]
        if len(codes) < 50:
            continue
        for name, lo, hi in BUCKETS:
            grp = [fwd[c] for c in codes[lo:hi]]
            if grp:
                bucket_ret[name].append(float(np.mean(grp)))
        fwd_s = pd.Series([fwd[c] for c in codes], index=codes)
        # 无 scipy，用"排名的 Pearson 相关 = Spearman"：评分名次(0=最高分) vs 收益名次(1=最高收益)
        score_rank = pd.Series(np.arange(len(codes), dtype=float), index=codes)
        fwd_rank = fwd_s.rank(ascending=False)
        ic = score_rank.corr(fwd_rank)  # >0 表示高分对应高收益
        if pd.notna(ic):
            ics.append(float(ic))
        n_win = max(1, int(len(codes) * 0.05))
        winners = set(fwd_s.sort_values(ascending=False).head(n_win).index)
        top10, top50 = set(codes[:10]), set(codes[:50])
        cap10.append(len(winners & top10) / min(10, n_win))
        cap50.append(len(winners & top50) / min(50, n_win))

    print(f"\n=== 评分排名 vs 未来{FWD}日收益 (每{STEP}日采样, {START}~{END}, {len(ics)} 个截面) ===")
    print(f"{'分桶(按评分排名)':<16}{'平均未来收益':>14}")
    for name, _, _ in BUCKETS:
        a = bucket_ret[name]
        if a:
            print(f"{name:<16}{np.mean(a):>14.2%}")
    print(f"\nSpearman 排名 IC 均值 : {np.mean(ics):+.3f}   (>0 表示高分→高收益; |IC|>0.03 即有用)")
    print(f"IC 为正的截面占比     : {np.mean([1 if x>0 else 0 for x in ics]):.1%}")
    print(f"大赢家(未来涨幅前5%)落在评分 Top10 的比例 : {np.mean(cap10):.1%}")
    print(f"大赢家(未来涨幅前5%)落在评分 Top50 的比例 : {np.mean(cap50):.1%}")
    print("RANK_IC_DONE")


if __name__ == "__main__":
    main()
