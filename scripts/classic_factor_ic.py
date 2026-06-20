#!/usr/bin/env python
"""经典因子 IC 快测：直接从行情计算常见因子，看哪个对未来20日收益有真信号。

因子(均已调向，使"值大=预期收益高"):
- rev20   : 近20日反转(买跌)     = -(20日涨幅)
- rev5    : 近5日反转            = -(5日涨幅)
- mom120  : 6个月动量            = 120日涨幅
- lowvol  : 低波动              = -(20日日收益波动)
- lottery : 反彩票(避免暴涨股)   = -(20日最大单日涨幅)
- lowturn : 低换手              = -(20日平均换手率)
- illiq   : 小流动性/小盘代理     = -(20日平均成交额)
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


def main() -> None:
    storage = DataStorage()
    sim = BacktestSimulator(storage)
    start, end = pd.to_datetime(START).date(), pd.to_datetime(END).date()
    close = sim._load_price_panel(storage.get_all_active_codes(), start, end)
    quotes_by_code = sim._load_quotes_by_code(close.columns, end)
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

    factors = ["rev20", "rev5", "mom120", "lowvol", "lottery", "lowturn", "illiq"]
    ic: dict[str, list[float]] = {f: [] for f in factors}
    spread: dict[str, list[float]] = {f: [] for f in factors}

    for i in range(125, len(dates) - FWD - 1, STEP):
        fwd = close.iloc[i + FWD] / close.iloc[i] - 1
        vals = {
            "rev20": -(close.iloc[i] / close.iloc[i - 20] - 1),
            "rev5": -(close.iloc[i] / close.iloc[i - 5] - 1),
            "mom120": close.iloc[i] / close.iloc[i - 120] - 1,
            "lowvol": -ret.iloc[i - 20:i].std(),
            "lottery": -ret.iloc[i - 20:i].max(),
            "lowturn": -turn.iloc[i - 20:i].mean(),
            "illiq": -amt.iloc[i - 20:i].mean(),
        }
        for f in factors:
            df = pd.concat([vals[f], fwd], axis=1, keys=["x", "y"]).dropna()
            if len(df) < 50 or df["x"].nunique() < 5:
                continue
            ic[f].append(float(df["x"].rank().corr(df["y"].rank())))
            srt = df.sort_values("x", ascending=False)
            k = max(1, len(srt) // 5)
            spread[f].append(float(srt["y"].head(k).mean() - srt["y"].tail(k).mean()))

    print(f"\n=== 经典因子 IC 快测 (未来{FWD}日, 每{STEP}日采样, {START}~{END}) ===")
    print(f"{'因子':<10}{'IC均值':>10}{'IC正占比':>10}{'多空价差':>12}{'年化多空~':>12}")
    for f in factors:
        if not ic[f]:
            print(f"{f:<10}{'无数据':>10}")
            continue
        a = pd.Series(ic[f])
        sp = np.mean(spread[f]) if spread[f] else 0
        ann = sp * (244 / FWD)  # 粗略年化(不复利)
        print(f"{f:<10}{a.mean():>+10.3f}{(a>0).mean():>10.1%}{sp:>+12.2%}{ann:>+12.1%}")
    print("\n说明: |IC|>0.03 有用、>0.05 较强; 多空价差=前20%−后20%未来20日收益; 年化为粗略折算。")
    print("CLASSIC_IC_DONE")


if __name__ == "__main__":
    main()
