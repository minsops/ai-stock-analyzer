"""综合评分与排序调度器。"""

from __future__ import annotations

from datetime import date
import json
from typing import Any

import pandas as pd
from loguru import logger

from src.data_layer.fetcher import StockDataFetcher
from src.data_layer.storage import DataStorage
from src.engines import BaseEngine, ScoreResult
from src.fusion.conflict_resolver import ConflictResolver
from src.fusion.filter import StockFilter
from src.fusion.regime_detector import RegimeDetector
from src.fusion.weight_manager import WeightManager
from src.risk.trade_plan import TradePlan
from src.valuation.historical import HistoricalValuation


class StockRanker:
    """整合所有模块，输出最终评分报告和排行榜。"""

    def __init__(
        self,
        fetcher: StockDataFetcher,
        storage: DataStorage,
        engines: list[BaseEngine],
        regime_detector: RegimeDetector,
        weight_manager: WeightManager,
        conflict_resolver: ConflictResolver,
        stock_filter: StockFilter,
    ) -> None:
        self.fetcher = fetcher
        self.storage = storage
        self.engines = engines
        self.regime_detector = regime_detector
        self.weight_manager = weight_manager
        self.conflict_resolver = conflict_resolver
        self.stock_filter = stock_filter
        self.historical_valuation = HistoricalValuation(storage)

    def score_single(
        self,
        code: str,
        market_data: dict[str, Any] | None = None,
        detected_regime: tuple[str, float, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        stock_info = self.storage.get_stock_info(code) or {"code": code, "name": code, "industry_l1": None, "is_st": False}
        quotes = self.storage.get_quotes(code)
        financial = self.storage.get_latest_financial(code)
        financial_history = self.storage.get_financial_history(code)
        capital = self.storage.get_capital_flow(code)
        if detected_regime is None:
            market_data = market_data or self.fetcher.get_market_overview()
            regime, regime_confidence, regime_details = self.regime_detector.detect(market_data)
        else:
            regime, regime_confidence, regime_details = detected_regime

        filter_passed, filter_reason = self.stock_filter.apply(code, stock_info, quotes, financial)
        context = {
            "stock_info": stock_info,
            "quotes": quotes,
            "financial": financial,
            "financial_history": financial_history,
            "capital": capital,
            "industry": self._build_industry_context(stock_info, quotes),
            "news": self.storage.get_recent_news(code),
        }
        engine_scores = {engine.name: engine.score(code, context) for engine in self.engines}
        conflict_result = self.conflict_resolver.resolve(engine_scores, regime)
        adjusted_scores: dict[str, ScoreResult] = conflict_result["adjusted_scores"]
        quarantined = conflict_result["action"] == "quarantine"
        composite = 0.0 if quarantined or not filter_passed else self.weight_manager.compute_composite(adjusted_scores, regime)

        pe_valuation = self.historical_valuation.compute_percentile(code, "pe_ttm")
        valuation = {
            "pe_percentile": pe_valuation.get("percentile"),
            "pb_percentile": self.historical_valuation.compute_percentile(code, "pb").get("percentile"),
        }
        trade_plan = TradePlan().build(composite, quotes, pe_valuation)
        # 实际参与综合评分的引擎数：信号越薄(参与越少)，综合分越不可靠。
        available_engines = sum(1 for result in adjusted_scores.values() if result.available)
        recent_news = [
            {"pub_date": str(item.get("pub_date", "")), "title": item.get("title", "")}
            for item in (context.get("news") or [])[:8]
        ]
        return {
            "code": code,
            "name": stock_info.get("name", code),
            "industry": stock_info.get("industry_l1"),
            "composite_score": composite,
            "recent_news": recent_news,
            "available_engines": available_engines,
            "total_engines": len(self.engines),
            "regime": regime,
            "regime_confidence": regime_confidence,
            "regime_details": regime_details,
            "weights": self.weight_manager.get_weights(regime),
            "trade_plan": trade_plan,
            "engine_scores": {name: result.to_dict() for name, result in adjusted_scores.items()},
            "conflicts": conflict_result["conflicts"],
            "conflict_action": conflict_result["action"],
            "filter_passed": filter_passed,
            "filter_reason": filter_reason,
            "quarantined": quarantined,
            "valuation": valuation,
            "scored_at": pd.Timestamp.now().isoformat(),
        }

    def scan_all(self, top_n: int = 50) -> pd.DataFrame:
        codes = self.storage.get_all_active_codes()
        rows: list[dict[str, Any]] = []
        logger.info(f"开始全市场评分，股票数: {len(codes)}")
        market_data = self.fetcher.get_market_overview()
        detected_regime = self.regime_detector.detect(market_data)
        self.storage.save_market_regime(date.today(), detected_regime[0], detected_regime[1], detected_regime[2])
        for code in codes:
            try:
                report = self.score_single(code, market_data=market_data, detected_regime=detected_regime)
                if report["filter_passed"] and not report["quarantined"]:
                    rows.append(
                        {
                            "code": report["code"],
                            "score_date": date.today(),
                            "name": report["name"],
                            "industry": report["industry"],
                            "composite_score": report["composite_score"],
                            "value_score": report["engine_scores"].get("value", {}).get("score"),
                            "trend_score": report["engine_scores"].get("trend", {}).get("score"),
                            "capital_score": report["engine_scores"].get("capital", {}).get("score"),
                            "industry_score": report["engine_scores"].get("industry", {}).get("score"),
                            "event_score": report["engine_scores"].get("event", {}).get("score"),
                            "regime": report["regime"],
                            "weights_json": json.dumps(report["weights"], ensure_ascii=False),
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - 扫描单股失败不影响整体
                logger.warning(f"{code} 评分失败，已跳过: {exc}")
        result = pd.DataFrame(rows).sort_values("composite_score", ascending=False).head(top_n) if rows else pd.DataFrame()
        if not result.empty:
            self.storage.save_scores(result)
        return result

    def _build_industry_context(self, stock_info: dict[str, Any], quotes: pd.DataFrame) -> dict[str, Any]:
        from src.industry.sector_map import csi_sector

        # 个股证监会行业 → 中证一级行业(industry_index 表里存的是中证一级)。
        industry_name = csi_sector(stock_info.get("industry_l1")) or stock_info.get("industry_l1")
        if not industry_name:
            return {}
        all_history = self.storage.get_all_industry_history()
        if all_history.empty:
            return {}
        industry_returns: dict[str, float] = {}
        volume_changes: dict[str, float] = {}
        for name, group in all_history.groupby("industry_name"):
            group = group.sort_values("trade_date")
            close = pd.to_numeric(group["close"], errors="coerce").dropna()
            if len(close) >= 21 and close.iloc[-21] != 0:
                industry_returns[str(name)] = float(close.iloc[-1] / close.iloc[-21] - 1)
            volume = pd.to_numeric(group.get("volume"), errors="coerce").dropna()
            if len(volume) >= 10 and volume.iloc[-10] != 0:
                volume_changes[str(name)] = float(volume.tail(5).mean() / volume.iloc[-10:-5].mean() - 1)
        if industry_name not in industry_returns:
            return {}
        sorted_returns = sorted(industry_returns.items(), key=lambda item: item[1], reverse=True)
        return_rank = next(index for index, item in enumerate(sorted_returns, start=1) if item[0] == industry_name)
        context: dict[str, Any] = {
            "return_20d": industry_returns[industry_name],
            "rank_percentile": return_rank / len(sorted_returns),
        }
        if industry_name in volume_changes:
            sorted_volume = sorted(volume_changes.items(), key=lambda item: item[1], reverse=True)
            volume_rank = next(index for index, item in enumerate(sorted_volume, start=1) if item[0] == industry_name)
            context["fund_flow_percentile"] = volume_rank / len(sorted_volume)
        return context
