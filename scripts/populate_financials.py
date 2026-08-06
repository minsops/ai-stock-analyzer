#!/usr/bin/env python
"""并行补全财务/估值数据(baostock)。

baostock 单连接非线程安全，但多进程各自登录可安全并行。本脚本对"已有行情的股票"
并行拉取 PE/PB/PS 估值历史 + 最新一期基本面(ROE/同比/毛利率/负债率)，写入 financial_data。

用法: python scripts/populate_financials.py [workers]
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_layer.baostock_source import BaostockFetcher  # noqa: E402
from src.data_layer.storage import DataStorage  # noqa: E402


def _fetch_chunk(codes: list[str]) -> pd.DataFrame:
    fetcher = BaostockFetcher()
    frames: list[pd.DataFrame] = []
    for code in codes:
        try:
            df = fetcher.get_financial_data(code)
            if not df.empty:
                frames.append(df)
        except Exception:  # noqa: BLE001 - 单股失败跳过
            continue
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def main() -> None:
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    storage = DataStorage()
    codes = storage.get_codes_with_quotes()
    if not codes:
        print("daily_quotes 为空，请先拉取行情")
        return
    chunks = [codes[i::workers] for i in range(workers)]
    print(f"待补财务股票数: {len(codes)}，并发进程: {workers}")

    total = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for df in executor.map(_fetch_chunk, chunks):
            if not df.empty:
                total += storage.upsert_financial_data(df)
    print(f"financial_data 写入/更新 {total} 行，覆盖股票 {len(codes)} 只")


if __name__ == "__main__":
    main()
