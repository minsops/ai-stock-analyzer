#!/usr/bin/env python
"""为多周期 + 去幸存者偏差回测准备数据(baostock)。

- 幸存者偏差缓解：universe = 当前 + 多个历史时点的 沪深300/中证500 成分股并集
  (把后来被调出/退市的票也纳入)。同时把各时点成分股名单存入 index_membership 表，
  供回测做时点成分股(point-in-time)选股。
- 多周期：为该 universe 拉取 N 年日线。

用法: python scripts/fetch_backtest_history.py [years] [workers]
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_layer.baostock_source import BaostockFetcher  # noqa: E402
from src.data_layer.storage import DataStorage  # noqa: E402

# 取这些历史时点的成分股(半年一次)，覆盖回测窗口
AS_OF_DATES = ["2023-06-30", "2023-12-29", "2024-06-28", "2024-12-31", "2025-06-30", "2025-12-31"]


def _membership(fetcher: BaostockFetcher) -> pd.DataFrame:
    """各时点 沪深300/中证500 成分股名单(含当前)。"""
    rows: list[dict] = []
    queries = {"hs300": "query_hs300_stocks", "zz500": "query_zz500_stocks"}
    for as_of in [*AS_OF_DATES, ""]:
        for index_name, query in queries.items():
            try:
                rs = getattr(fetcher.bs, query)(date=as_of) if as_of else getattr(fetcher.bs, query)()
                df = fetcher._rs_to_df(rs)
            except Exception:  # noqa: BLE001
                continue
            if df.empty or "code" not in df:
                continue
            codes = df["code"].str.extract(r"\.(\d{6})", expand=False).dropna()
            label = as_of or date.today().isoformat()
            for code in codes:
                rows.append({"as_of": label, "index_name": index_name, "code": code})
    return pd.DataFrame(rows)


def _fetch_quotes(args: tuple[list[str], str, str]) -> int:
    codes, start, end = args
    fetcher = BaostockFetcher()
    storage = DataStorage()
    total = 0
    for code in codes:
        try:
            quotes = fetcher.get_daily_quotes(code, start, end)
            if not quotes.empty:
                total += storage.upsert_daily_quotes(quotes)
        except Exception:  # noqa: BLE001
            continue
    return total


def main() -> None:
    years = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    storage = DataStorage()
    storage.init_db()

    membership = _membership(BaostockFetcher())
    universe = sorted(membership["code"].unique()) if not membership.empty else []
    print(f"幸存者偏差缓解: universe(当前+历史并集) = {len(universe)} 只", flush=True)
    membership.to_csv(PROJECT_ROOT / "data" / "index_membership.csv", index=False)
    print(f"成分股名单已存 data/index_membership.csv ({len(membership)} 行)", flush=True)

    end = date.today()
    start = (end - timedelta(days=365 * years)).strftime("%Y%m%d")
    end_s = end.strftime("%Y%m%d")
    chunks = [(universe[i::workers], start, end_s) for i in range(workers)]
    total = 0
    with ProcessPoolExecutor(max_workers=workers) as executor:
        for written in executor.map(_fetch_quotes, chunks):
            total += written
    print(f"FETCH_HISTORY_DONE quotes 写入/更新 {total} 行，universe {len(universe)} 只，{years} 年", flush=True)


if __name__ == "__main__":
    main()
