from __future__ import annotations

import pandas as pd

from src.data_layer.baostock_source import BaostockFetcher


def test_to_bs_code_maps_markets() -> None:
    f = BaostockFetcher()
    assert f._to_bs_code("600519") == "sh.600519"
    assert f._to_bs_code("sz000001") == "sz.000001"
    assert f._to_bs_code("300750") == "sz.300750"
    assert f._to_bs_code("830799") == "bj.830799"


def test_normalize_code_extracts_six_digits() -> None:
    f = BaostockFetcher()
    assert f._normalize_code("sh.600000") == "600000"
    assert f._normalize_code("000001.SZ") == "000001"


class _FakeRS:
    """模拟 baostock 结果集。"""

    def __init__(self, fields: list[str], rows: list[list[str]]) -> None:
        self.error_code = "0"
        self.fields = fields
        self._rows = rows
        self._i = -1

    def next(self) -> bool:
        self._i += 1
        return self._i < len(self._rows)

    def get_row_data(self) -> list[str]:
        return self._rows[self._i]


def test_rs_to_df_builds_dataframe() -> None:
    f = BaostockFetcher()
    rs = _FakeRS(["date", "close"], [["2025-01-02", "10.1"], ["2025-01-03", "10.3"]])

    df = f._rs_to_df(rs)

    assert list(df.columns) == ["date", "close"]
    assert len(df) == 2
    assert df.iloc[-1]["close"] == "10.3"


def test_rs_to_df_empty_returns_columns() -> None:
    f = BaostockFetcher()
    rs = _FakeRS(["date", "close"], [])

    df = f._rs_to_df(rs)

    assert df.empty
    assert list(df.columns) == ["date", "close"]
