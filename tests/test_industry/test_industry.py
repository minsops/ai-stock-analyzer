from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from src.data_layer.storage import DataStorage
from src.industry import IndustryRanker


def _seed(storage: DataStorage, code: str, industry: str, slope: float, days: int = 260) -> None:
    start = date(2025, 1, 1)
    close = np.linspace(10, 10 * (1 + slope), days)
    storage.upsert_stocks(
        pd.DataFrame({"code": [code], "name": [f"股票{code}"], "market": ["SZ"], "industry_l1": [industry], "is_active": [True]})
    )
    storage.upsert_daily_quotes(
        pd.DataFrame(
            {
                "code": [code] * days,
                "trade_date": [start + timedelta(days=i) for i in range(days)],
                "open": close, "high": close, "low": close, "close": close,
                "volume": [1000] * days, "amount": [1_000_000] * days,
                "turnover": [1.0] * days, "pct_change": pd.Series(close).pct_change().fillna(0) * 100,
            }
        )
    )


def _build_storage() -> DataStorage:
    storage = DataStorage("sqlite:///:memory:")
    storage.init_db()
    # 热门行业：半导体（涨幅大）；冷门行业：银行（涨幅小）
    _seed(storage, "300001", "半导体", 0.60)
    _seed(storage, "300002", "半导体", 0.50)
    _seed(storage, "300003", "半导体", 0.40)
    _seed(storage, "600001", "银行", 0.05)
    _seed(storage, "600002", "银行", 0.03)
    _seed(storage, "600003", "银行", 0.01)
    return storage


def test_industry_strength_ranks_hot_industry_first() -> None:
    ranker = IndustryRanker(_build_storage())

    strength = ranker.industry_strength(lookback_days=250, min_stocks=3)

    assert list(strength["industry"])[0] == "半导体"
    assert strength.iloc[0]["mean_return"] > strength.iloc[1]["mean_return"]
    assert int(strength.iloc[0]["rank"]) == 1


def test_select_picks_top_industries_and_members() -> None:
    ranker = IndustryRanker(_build_storage())

    selections = ranker.select(top_industries=1, min_stocks=3, min_pick=2, max_pick=50)

    assert len(selections) == 1
    sel = selections[0]
    assert sel.industry == "半导体"
    assert len(sel.top_stocks) == 3
    # 无 scorer 时按近一年涨幅排序，涨幅最大的在前
    assert sel.top_stocks[0]["code"] == "300001"


def test_select_uses_scorer_when_provided() -> None:
    ranker = IndustryRanker(_build_storage())
    scores = {"300001": 50.0, "300002": 90.0, "300003": 70.0}

    def scorer(code: str) -> dict:
        return {"name": f"股票{code}", "composite_score": scores.get(code, 0.0), "filter_passed": True, "quarantined": False}

    selections = ranker.select(top_industries=1, min_stocks=3, scorer=scorer, min_pick=2, max_pick=50)

    picked = selections[0].top_stocks
    # 按综合评分排序：300002(90) > 300003(70) > 300001(50)
    assert [s["code"] for s in picked] == ["300002", "300003", "300001"]
