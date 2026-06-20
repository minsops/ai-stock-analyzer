"""API 服务依赖工厂。"""

from __future__ import annotations

import json

from src.data_layer import DataStorage, StockDataFetcher
from src.engines import CapitalEngine, EventEngine, IndustryEngine, NewsEngine, TrendEngine, ValueEngine
from src.fusion import ConflictResolver, RegimeDetector, StockFilter, StockRanker, WeightManager
from src.llm import LLMAnalyst


def get_storage() -> DataStorage:
    return DataStorage()


def get_fetcher() -> StockDataFetcher:
    return StockDataFetcher()


def get_analyst() -> LLMAnalyst:
    return LLMAnalyst()


def get_current_regime() -> tuple[str, float, dict]:
    """返回当前市场状态 (regime, confidence, details)。

    优先读每日扫描已落库的最近一次状态（无网络、低延迟、抗限流），仅当库内
    为空时才回退到实时探测。这样仪表盘/排行接口不必在每次请求都做阻塞式行情拉取。
    """
    persisted = get_storage().get_latest_market_regime()
    if persisted and persisted.get("regime"):
        details = persisted.get("details_json")
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except (ValueError, TypeError):
                details = {}
        return persisted["regime"], persisted.get("confidence") or 0.0, details or {}
    return RegimeDetector().detect(get_fetcher().get_market_overview())


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

