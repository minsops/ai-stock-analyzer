#!/usr/bin/env python
"""交易级回测：每个交易日买入综合评分 Top-N(各 ¥10000)，按交易计划止盈/止损平仓。

- 入场：当日收盘价买入当日 Top-N(去幸存者偏差，仅当时成分股)。
- 出场：之后任一日 最低价≤止损 → 止损平仓；最高价≥技术目标 → 止盈平仓；
        超过 max_hold 个交易日仍未触发 → 按收盘价平仓。
- 成本：买卖各算佣金+滑点，卖出加印花税。
- 汇总：笔数/胜率/止盈止损占比/总投入/总净盈亏/总收益率(净盈亏÷总投入)。

用法: python scripts/trade_backtest.py [start] [end] [topn] [per_amount] [max_hold]
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from src.backtest import BacktestSimulator  # noqa: E402
from src.data_layer.storage import DataStorage  # noqa: E402
from src.risk.trade_plan import TradePlan  # noqa: E402

START = sys.argv[1] if len(sys.argv) > 1 else "2023-07-01"
END = sys.argv[2] if len(sys.argv) > 2 else "2026-06-10"
TOP_N = int(sys.argv[3]) if len(sys.argv) > 3 else 20
PER = float(sys.argv[4]) if len(sys.argv) > 4 else 10000.0
MAX_HOLD = int(sys.argv[5]) if len(sys.argv) > 5 else 40
REGIME = "shock"

BUY_COST = settings.BACKTEST_COMMISSION_RATE + settings.BACKTEST_SLIPPAGE
SELL_COST = settings.BACKTEST_COMMISSION_RATE + settings.BACKTEST_SLIPPAGE + settings.BACKTEST_STAMP_TAX


def load_membership() -> dict:
    path = PROJECT_ROOT / "data" / "index_membership.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path, dtype={"code": str})
    out: dict = {}
    for as_of, grp in df.groupby("as_of"):
        try:
            out[datetime.strptime(str(as_of), "%Y-%m-%d").date()] = set(grp["code"].str.zfill(6))
        except ValueError:
            continue
    return out


def members_asof(membership: dict, day) -> set | None:
    if not membership:
        return None
    keys = [k for k in membership if k <= day]
    return membership[max(keys)] if keys else None


def main() -> None:
    storage = DataStorage()
    sim = BacktestSimulator(storage)
    start = pd.to_datetime(START).date()
    end = pd.to_datetime(END).date()
    codes = storage.get_all_active_codes()
    prices = sim._load_price_panel(codes, start, end)
    if prices.empty:
        print("无价格数据")
        return
    quotes_by_code = sim._load_quotes_by_code(prices.columns, end)
    financials_by_code = {c: storage.get_financial_history(c) for c in prices.columns}
    stock_sector = sim._load_stock_sectors(prices.columns)
    industry_hist = storage.get_all_industry_history()
    membership = load_membership()

    # 预存每只股票的 OHLC(按日期索引)，供入场(次日开盘)与出场判断。
    ohlc: dict = {}
    for code, q in quotes_by_code.items():
        qq = q.copy()
        qq["d"] = pd.to_datetime(qq["trade_date"]).dt.date
        ohlc[code] = qq.set_index("d")[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")

    dates = list(prices.index)
    date_pos = {d: i for i, d in enumerate(dates)}
    trades: list[dict] = []
    plan = TradePlan()

    for i, day in enumerate(dates):
        if i < 60 or i >= len(dates) - 2:
            continue
        ranked = sim._composite_scores(prices.loc[:day], quotes_by_code, financials_by_code, stock_sector, industry_hist, day, REGIME)
        valid = members_asof(membership, day)
        if valid is not None:
            ranked = ranked[ranked.index.isin(valid)]
        entry_day = dates[i + 1]  # 次日开盘成交
        for code in ranked.head(TOP_N).index:
            o = ohlc.get(code)
            if o is None or entry_day not in o.index:
                continue
            entry = float(o.loc[entry_day, "open"])
            if not entry or pd.isna(entry):
                continue
            q_pit = quotes_by_code[code]
            q_pit = q_pit[pd.to_datetime(q_pit["trade_date"]).dt.date <= day]  # 仅用决策日及以前
            tp = plan.build(50.0, q_pit)
            if not tp.get("available"):
                continue
            stop, target = tp["stop_loss"], tp["target_technical"]
            # 从入场日(次日)起向前找出场
            exit_price, reason, hold = None, "timeout", 0
            for j in range(i + 1, min(i + 1 + MAX_HOLD, len(dates))):
                d2 = dates[j]
                if d2 not in o.index:
                    continue
                hold = j - (i + 1)
                lo, hi, cl = o.loc[d2, "low"], o.loc[d2, "high"], o.loc[d2, "close"]
                if pd.notna(lo) and lo <= stop:
                    exit_price, reason = stop, "止损"
                    break
                if pd.notna(hi) and hi >= target:
                    exit_price, reason = target, "止盈"
                    break
                exit_price = cl
            if exit_price is None or pd.isna(exit_price):
                continue
            shares = int(PER // entry // 100 * 100)
            if shares <= 0:
                continue
            cost_in = shares * entry * (1 + BUY_COST)
            cash_out = shares * exit_price * (1 - SELL_COST)
            trades.append({"pnl": cash_out - cost_in, "invested": shares * entry, "reason": reason, "hold": hold, "ret": cash_out / cost_in - 1})
        if i % 60 == 0:
            print(f"...进度 {i}/{len(dates)} 日，已开仓 {len(trades)} 笔", flush=True)

    if not trades:
        print("无成交")
        return
    t = pd.DataFrame(trades)
    total_invested = t["invested"].sum()
    total_pnl = t["pnl"].sum()
    win = (t["pnl"] > 0).mean()
    by_reason = t["reason"].value_counts(normalize=True).round(3).to_dict()
    years = (end - start).days / 365.25
    print("\n=== 交易级回测 每日选 Top%d 次日开盘各买 ¥%.0f，止盈止损 ===" % (TOP_N, PER))
    print(f"区间 {START}~{END}  入场=次日开盘价  最长持有 {MAX_HOLD} 交易日")
    print(f"总交易笔数 : {len(t):,}")
    print(f"胜率       : {win:.1%}")
    print(f"出场构成   : {by_reason}")
    print(f"平均持仓   : {t['hold'].mean():.1f} 交易日")
    print(f"单笔平均收益: {t['ret'].mean():.2%}")
    print(f"总投入本金 : ¥{total_invested:,.0f}  (每笔约 ¥{PER:.0f})")
    print(f"总净盈亏   : ¥{total_pnl:,.0f}")
    print(f"总收益率   : {total_pnl/total_invested:.2%}   (净盈亏 ÷ 总投入)")
    print("TRADE_BT_DONE")


if __name__ == "__main__":
    main()
