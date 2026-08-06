"""API 服务依赖工厂。"""

from __future__ import annotations

from src.data_layer import DataStorage, StockDataFetcher
from src.engines import CapitalEngine, EventEngine, IndustryEngine, NewsEngine, TrendEngine, ValueEngine
from src.fusion import ConflictResolver, RegimeDetector, StockFilter, StockRanker, WeightManager
from src.fusion.ranker import resolve_local_regime
from src.llm import LLMAnalyst


def get_storage() -> DataStorage:
    return DataStorage()


def get_fetcher() -> StockDataFetcher:
    return StockDataFetcher()


def get_analyst() -> LLMAnalyst:
    return LLMAnalyst()


def get_current_regime() -> tuple[str, float, dict]:
    """返回当前市场状态 (regime, confidence, details)。

    优先读数据更新阶段落库的最近一次状态；库内为空时直接按震荡处理。
    """
    return resolve_local_regime(get_storage(), RegimeDetector())


def get_ranker() -> StockRanker:
    return StockRanker(
        fetcher=get_fetcher(),
        storage=get_storage(),
        engines=[ValueEngine(), TrendEngine(), CapitalEngine(), IndustryEngine(), EventEngine(), NewsEngine()],
        regime_detector=RegimeDetector(),
        weight_manager=WeightManager(),
        conflict_resolver=ConflictResolver(),
        stock_filter=StockFilter(),
    )
