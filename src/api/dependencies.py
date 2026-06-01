"""API 服务依赖工厂。"""

from __future__ import annotations

from src.data_layer import DataStorage, StockDataFetcher
from src.engines import CapitalEngine, EventEngine, IndustryEngine, TrendEngine, ValueEngine
from src.fusion import ConflictResolver, RegimeDetector, StockFilter, StockRanker, WeightManager


def get_storage() -> DataStorage:
    return DataStorage()


def get_fetcher() -> StockDataFetcher:
    return StockDataFetcher()


def get_ranker() -> StockRanker:
    return StockRanker(
        fetcher=get_fetcher(),
        storage=get_storage(),
        engines=[ValueEngine(), TrendEngine(), CapitalEngine(), IndustryEngine(), EventEngine()],
        regime_detector=RegimeDetector(),
        weight_manager=WeightManager(),
        conflict_resolver=ConflictResolver(),
        stock_filter=StockFilter(),
    )

