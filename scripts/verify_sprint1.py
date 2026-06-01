#!/usr/bin/env python
"""Sprint 1 验证脚本：拉取、清洗、入库、读取。"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.logging_config import setup_logging  # noqa: E402
from src.data_layer import DataStorage, StockDataFetcher  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="验证 Sprint 1 数据链路")
    parser.add_argument("--code", default="000001", help="股票代码，默认 000001")
    parser.add_argument("--days", type=int, default=90, help="拉取最近多少天日线，默认 90")
    return parser.parse_args()


def main() -> None:
    setup_logging()
    args = parse_args()
    end = date.today()
    start = end - timedelta(days=args.days)
    start_date = start.strftime("%Y%m%d")
    end_date = end.strftime("%Y%m%d")

    storage = DataStorage()
    storage.init_db()
    fetcher = StockDataFetcher()

    print(f"开始验证: 股票 {args.code}, 区间 {start_date} - {end_date}")
    quotes = fetcher.get_daily_quotes(args.code, start_date, end_date)
    print(f"拉取并清洗日线数据: {len(quotes)} 行")
    if quotes.empty:
        existing = storage.get_quotes(args.code)
        if existing.empty:
            print("未获取到行情数据，且数据库没有可用历史数据。请检查网络或 AKShare 接口状态。")
            raise SystemExit(1)
        print("实时接口暂不可用，使用数据库已有数据继续验证读取链路。")
        print(f"从数据库读取: {len(existing)} 行")
        print("最近 5 条数据:")
        print(existing.tail(5).to_string(index=False))
        print("Sprint 1 数据链路验证完成（使用本地已有数据）")
        return

    written = storage.upsert_daily_quotes(quotes)
    loaded = storage.get_quotes(args.code, start.isoformat(), end.isoformat())
    print(f"写入数据库: {written} 行")
    print(f"从数据库读取: {len(loaded)} 行")
    print("最近 5 条数据:")
    print(loaded.tail(5).to_string(index=False))
    print("Sprint 1 数据链路验证完成")


if __name__ == "__main__":
    main()
