from __future__ import annotations

from datetime import date

import pandas as pd

from src.data_layer.storage import DataStorage
from src.valuation import PeerComparison


def test_peer_comparison_compares_industry_peers() -> None:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    storage.upsert_stocks(
        pd.DataFrame(
            {
                "code": ["000001", "000002"],
                "name": ["银行A", "银行B"],
                "market": ["SZ", "SZ"],
                "industry_l1": ["银行", "银行"],
                "is_active": [True, True],
            }
        )
    )
    storage.upsert_financial_data(
        pd.DataFrame(
            {
                "code": ["000001", "000002"],
                "report_date": [date(2025, 12, 31), date(2025, 12, 31)],
                "pe_ttm": [5.0, 8.0],
                "pb": [0.8, 1.0],
                "roe": [12.0, 10.0],
                "revenue_yoy": [8.0, 6.0],
                "profit_yoy": [9.0, 7.0],
            }
        )
    )

    result = PeerComparison(storage).compare("000001")

    assert result["industry"] == "银行"
    assert result["peer_count"] == 2
    assert result["rankings"]["pe_ttm"]["rank"] == 1
