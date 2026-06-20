#!/usr/bin/env python
"""出场规则对照实验：同一批每日 Top-N 选股，比较不同出场规则的单笔平均收益。

目的：验证"为什么月度持有能 100%+、而每日止盈止损不行"——是出场规则(砍利润)而非选股的问题。
评分(最贵)只跑一遍，多种出场规则在同一批选股上一起算。

规则：
- stop_target : 当前(ATR 止损 / 技术目标止盈 / 40日超时)
- hold20      : 不止损，持有 20 个交易日按收盘平仓
- hold60      : 不止损，持有 60 个交易日
- trailing    : 移动止损(从入场后最高价回撤 3×ATR 才出场，让利润奔跑，最长 60 日)
入场统一为次日开盘价，计真实成本。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from src.backtest import BacktestSimulator  # noqa: E402
from src.data_layer.storage import DataStorage  # noqa: E402

START, END, TOP_N = "2023-07-01", "2026-06-10", 20
BUY = settings.BACKTEST_COMMISSION_RATE + settings.BACKTEST_SLIPPAGE
SELL = settings.BACKTEST_COMMISSION_RATE + settings.BACKTEST_SLIPPAGE + settings.BACKTEST_STAMP_TAX
MAXH = 60


def load_membership() -> dict:
    p = PROJECT_ROOT / "data" / "index_membership.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p, dtype={"code": str})
    out: dict = {}
    for a, g in df.groupby("as_of"):
        try:
            out[datetime.strptime(str(a), "%Y-%m-%d").date()] = set(g["code"].str.zfill(6))
        except ValueError:
            pass
    return out


def members_asof(m: dict, day):
    if not m:
        return None
    ks = [k for k in m if k <= day]
    return m[max(ks)] if ks else None


def ret_after_cost(entry, exit_):
    return (exit_ * (1 - SELL)) / (entry * (1 + BUY)) - 1


def main() -> None:
    storage = DataStorage()
    sim = BacktestSimulator(storage)
    start, end = pd.to_datetime(START).date(), pd.to_datetime(END).date()
    prices = sim._load_price_panel(storage.get_all_active_codes(), start, end)
    quotes_by_code = sim._load_quotes_by_code(prices.columns, end)
    financials = {c: storage.get_financial_history(c) for c in prices.columns}
    sectors = sim._load_stock_sectors(prices.columns)
    industry_hist = storage.get_all_industry_history()
    membership = load_membership()

    ohlc: dict = {}
    for code, q in quotes_by_code.items():
        qq = q.copy()
        qq["d"] = pd.to_datetime(qq["trade_date"]).dt.date
        ohlc[code] = qq.set_index("d")[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")

    dates = list(prices.index)
    rules: dict[str, list[float]] = {"stop_target": [], "hold20": [], "hold60": [], "trailing": []}

    for i, day in enumerate(dates):
        if i < 60 or i >= len(dates) - 2:
            continue
        ranked = sim._composite_scores(prices.loc[:day], quotes_by_code, financials, sectors, industry_hist, day, "shock")
        valid = members_asof(membership, day)
        if valid is not None:
            ranked = ranked[ranked.index.isin(valid)]
        entry_day = dates[i + 1]
        for code in ranked.head(TOP_N).index:
            o = ohlc.get(code)
            if o is None or entry_day not in o.index:
                continue
            entry = o.loc[entry_day, "open"]
            if pd.isna(entry) or entry <= 0:
                continue
            win = o.loc[entry_day:].head(MAXH + 1)
            if len(win) < 2:
                continue
            atr = float((win["high"] - win["low"]).head(14).mean()) or entry * 0.03
            hi, lo, cl = win["high"].values, win["low"].values, win["close"].values
            n = len(cl)
            stop = entry - 1.5 * atr
            target = entry + 3.0 * atr
            # stop_target
            st = None
            for k in range(n):
                if lo[k] <= stop:
                    st = stop; break
                if hi[k] >= target:
                    st = target; break
                if k >= 40:
                    st = cl[k]; break
            rules["stop_target"].append(ret_after_cost(entry, st if st is not None else cl[-1]))
            # hold20 / hold60
            rules["hold20"].append(ret_after_cost(entry, cl[min(20, n - 1)]))
            rules["hold60"].append(ret_after_cost(entry, cl[min(60, n - 1)]))
            # trailing: 从最高价回撤 3ATR 出场
            peak = entry; tr = None
            for k in range(n):
                peak = max(peak, hi[k])
                if cl[k] <= peak - 3.0 * atr:
                    tr = cl[k]; break
            rules["trailing"].append(ret_after_cost(entry, tr if tr is not None else cl[-1]))
        if i % 100 == 0:
            print(f"...{i}/{len(dates)} 日，样本 {len(rules['hold20'])}", flush=True)

    print(f"\n=== 出场规则对照 (每日 Top{TOP_N} 次日开盘入场, {START}~{END}) ===")
    print(f"{'规则':<14}{'笔数':>8}{'胜率':>8}{'单笔均收益':>12}{'中位收益':>10}")
    for name, arr in rules.items():
        a = pd.Series(arr)
        if a.empty:
            continue
        print(f"{name:<14}{len(a):>8}{(a>0).mean():>8.1%}{a.mean():>12.2%}{a.median():>10.2%}")
    print("EXIT_STUDY_DONE")


if __name__ == "__main__":
    main()
