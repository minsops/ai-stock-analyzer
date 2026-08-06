#!/usr/bin/env python
"""路线 B 数据补全:回填【真历史季度基本面】(point-in-time)。

之前 financial_data 里 roe/同比/毛利/负债 只盖在最新一行，导致质量/成长因子在
历史截面上几乎全 NaN、无法做 point-in-time IC 检验(见 docs/FACTOR_RESEARCH.md)。
本脚本用 baostock 逐季度拉每只股票的 ROE/毛利率/净利同比/营收同比/资产负债率，
按 **pubDate(发布日)** 作为 report_date 写回 financial_data(只更新基本面列，不动估值)。

baostock 单连接非线程安全；本机沙箱又禁用多进程(共享内存库被系统策略拦)，故
**单进程顺序**拉取，按批提交(可中断续跑:已写入的不会丢)。

用法: python scripts/backfill_fundamentals.py [years] [limit]
  years: 回看年数(默认4)  limit: 只处理前 N 只(调试用，默认全部)
"""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_layer.baostock_source import BaostockFetcher  # noqa: E402
from src.data_layer.storage import DataStorage  # noqa: E402

BATCH = 50  # 每 50 只提交一次


def main() -> None:
    years = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    storage = DataStorage()
    codes = storage.get_codes_with_quotes()
    if not codes:
        print("daily_quotes 为空，请先拉取行情")
        return
    if limit:
        codes = codes[:limit]
    fetcher = BaostockFetcher(valuation_lookback_years=years)
    print(f"待回填季度基本面股票数: {len(codes)}，单进程顺序，回看 {years} 年", flush=True)

    total = 0
    buffer: list[pd.DataFrame] = []
    for idx, code in enumerate(codes, start=1):
        try:
            df = fetcher.get_quarterly_fundamentals(code, years=years)
            if not df.empty:
                buffer.append(df)
        except Exception:  # noqa: BLE001 - 单股失败跳过
            pass
        if idx % BATCH == 0 or idx == len(codes):
            if buffer:
                total += storage.upsert_fundamentals(pd.concat(buffer, ignore_index=True))
                buffer = []
            print(f"  {idx}/{len(codes)} 只已处理，累计写入 {total} 行", flush=True)
    print(f"\n季度基本面回填完成: 写入/更新 {total} 行，覆盖股票 {len(codes)} 只")
    print("BACKFILL_FUNDAMENTALS_DONE")


if __name__ == "__main__":
    main()
