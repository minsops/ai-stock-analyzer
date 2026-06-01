from __future__ import annotations

from datetime import date

import pandas as pd

from src.data_layer.storage import DataStorage


def test_storage_upserts_and_reads_quotes() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    quotes = pd.DataFrame(
        {
            "code": ["000001", "000001"],
            "trade_date": [date(2026, 1, 1), date(2026, 1, 2)],
            "open": [10.0, 10.1],
            "high": [10.2, 10.3],
            "low": [9.9, 10.0],
            "close": [10.1, 10.2],
            "volume": [1000.0, 1200.0],
            "amount": [1000000.0, 1200000.0],
            "turnover": [1.1, 1.2],
            "pct_change": [1.0, 0.99],
        }
    )

    count = storage.upsert_daily_quotes(quotes)
    loaded = storage.get_quotes("000001")

    assert count == 2
    assert len(loaded) == 2
    assert loaded.iloc[-1]["close"] == 10.2


def test_storage_skips_empty_dataframe() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()

    assert storage.upsert_daily_quotes(pd.DataFrame()) == 0

