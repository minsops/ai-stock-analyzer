from __future__ import annotations

from datetime import date

import pandas as pd

from src.data_layer import DataStorage, DataUpdater


class FakeFetcher:
    def get_stock_list(self, with_industry: bool = True) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "code": ["000001"],
                "name": ["平安银行"],
                "market": ["SZ"],
                "industry_l1": ["银行"],
                "industry_l2": [None],
                "list_date": [date(1991, 4, 3)],
                "is_st": [False],
                "is_active": [True],
            }
        )

    def get_daily_quotes(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "code": [code],
                "trade_date": [date(2026, 1, 1)],
                "open": [10.0],
                "high": [10.2],
                "low": [9.9],
                "close": [10.1],
                "volume": [1000],
                "amount": [10_000_000],
                "turnover": [1.0],
                "pct_change": [1.0],
            }
        )

    def get_financial_data(self, code: str) -> pd.DataFrame:
        return pd.DataFrame({"code": [code], "report_date": [date(2025, 12, 31)], "pe_ttm": [8.0]})

    def get_capital_flow(self, code: str) -> pd.DataFrame:
        return pd.DataFrame({"code": [code], "trade_date": [date(2026, 1, 1)], "main_net_inflow": [1000.0]})

    def get_industry_index(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "industry_code": ["BK001"],
                "industry_name": ["银行"],
                "trade_date": [date(2026, 1, 1)],
                "close": [1000.0],
                "pct_change": [1.0],
                "volume": [1000],
            }
        )

    def _normalize_code(self, code: str) -> str:
        digits = "".join(ch for ch in str(code) if ch.isdigit())
        return digits[-6:] if len(digits) >= 6 else digits


class MultiStockFetcher(FakeFetcher):
    def get_stock_list(self, with_industry: bool = True) -> pd.DataFrame:
        codes = [f"00000{i}" for i in range(1, 6)]
        return pd.DataFrame(
            {
                "code": codes,
                "name": codes,
                "market": ["SZ"] * len(codes),
                "industry_l1": [None] * len(codes),
                "industry_l2": [None] * len(codes),
                "list_date": [date(1991, 4, 3)] * len(codes),
                "is_st": [False] * len(codes),
                "is_active": [True] * len(codes),
            }
        )


def test_data_updater_full_update_writes_all_tables() -> None:
    storage = DataStorage("sqlite:///:memory:")

    summary = DataUpdater(FakeFetcher(), storage).update(full=True)

    assert summary.stocks == 1
    assert summary.quotes == 1
    assert summary.financial == 1
    assert summary.capital == 1
    assert summary.industry_index == 1
    assert storage.get_stock_info("000001")["name"] == "平安银行"


def test_data_updater_sample_limits_universe() -> None:
    storage = DataStorage("sqlite:///:memory:")

    summary = DataUpdater(MultiStockFetcher(), storage).update(sample=2)

    assert summary.stocks == 5  # 股票列表整体写入
    assert summary.quotes == 2  # 仅更新前 2 只的行情


def test_data_updater_codes_targets_specific_stocks() -> None:
    storage = DataStorage("sqlite:///:memory:")

    summary = DataUpdater(MultiStockFetcher(), storage).update(codes=["000003"])

    assert summary.quotes == 1
