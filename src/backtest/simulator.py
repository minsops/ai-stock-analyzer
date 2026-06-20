"""历史回测模拟器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from config import settings
from src.backtest.metrics import PerformanceMetrics
from src.data_layer.storage import DataStorage
from src.engines import BaseEngine, CapitalEngine, EventEngine, IndustryEngine, NewsEngine, TrendEngine, ValueEngine
from src.fusion.weight_manager import WeightManager


@dataclass
class BacktestResult:
    """回测结果。"""

    equity_curve: pd.DataFrame
    positions: list[dict[str, Any]]
    metrics: dict[str, Any]


class BacktestSimulator:
    """基础回测模拟器，支持按动量或按系统综合评分调仓。"""

    def __init__(
        self,
        storage: DataStorage,
        engines: list[BaseEngine] | None = None,
        weight_manager: WeightManager | None = None,
    ) -> None:
        self.storage = storage
        self.metrics = PerformanceMetrics()
        self.engines = engines or [ValueEngine(), TrendEngine(), CapitalEngine(), IndustryEngine(), EventEngine(), NewsEngine()]
        self.weight_manager = weight_manager or WeightManager()

    def run(self, config: dict) -> BacktestResult:
        start_date = pd.to_datetime(config["start_date"]).date()
        end_date = pd.to_datetime(config["end_date"]).date()
        initial_capital = float(config.get("initial_capital", 100_000))
        top_n = int(config.get("top_n", 10))
        rebalance_freq = config.get("rebalance_freq", "monthly")
        # selection: "score"（系统综合评分，与推荐逻辑一致）或 "momentum"（动量基准）
        selection = config.get("selection", "score")
        regime = config.get("regime", "shock")
        # 去幸存者偏差：membership = {as_of_date: set(codes)} 时，每个调仓日只在"当时"成分股里选。
        membership = config.get("membership")

        codes = self.storage.get_all_active_codes()
        prices = self._load_price_panel(codes, start_date, end_date)
        if prices.empty:
            equity = pd.DataFrame({"trade_date": [], "equity": [], "daily_return": []})
            return BacktestResult(equity, [], self.metrics.compute(pd.Series(dtype=float)))

        if selection == "score":
            quotes_by_code = self._load_quotes_by_code(prices.columns, end_date)
            financials_by_code = {code: self.storage.get_financial_history(code) for code in prices.columns}
            stock_sector = self._load_stock_sectors(prices.columns)
            industry_hist = self.storage.get_all_industry_history()
        else:
            quotes_by_code, financials_by_code, stock_sector, industry_hist = {}, {}, {}, pd.DataFrame()

        rebalance_dates = self._rebalance_dates(prices.index, rebalance_freq)
        holdings: list[str] = []
        positions: list[dict[str, Any]] = []
        daily_returns: list[float] = []
        dates: list[date] = []

        # 单边成本：佣金+滑点；卖出额外印花税。换手部分按买卖各一次计。
        buy_cost = settings.BACKTEST_COMMISSION_RATE + settings.BACKTEST_SLIPPAGE
        sell_cost = settings.BACKTEST_COMMISSION_RATE + settings.BACKTEST_SLIPPAGE + settings.BACKTEST_STAMP_TAX

        # 熊市择时/降仓：按市场状态把总仓位在 0-1 之间缩放(其余空仓)，缓解系统性下跌。
        regime_timing = config.get("regime_timing", False)
        exposure_tiers = config.get("exposure_tiers")  # 可选: {regime: 仓位上限}
        exposure_by_date = self._exposure_series(prices, exposure_tiers) if regime_timing else {}

        returns = prices.pct_change().fillna(0)
        for current_date in prices.index:
            rebalance_cost = 0.0
            if current_date in rebalance_dates:
                if selection == "momentum":
                    ranked = self._momentum_scores(prices.loc[:current_date], lookback=60)
                else:
                    ranked = self._composite_scores(
                        prices.loc[:current_date], quotes_by_code, financials_by_code,
                        stock_sector, industry_hist, current_date, regime,
                    )
                if membership is not None:
                    members = self._members_asof(membership, current_date)
                    if members:
                        ranked = ranked[ranked.index.isin(members)]
                new_holdings = ranked.head(top_n).index.tolist()
                # 成本只作用于换手部分：新买入按买入成本、卖出按卖出成本(含印花税)。
                size = max(len(new_holdings), 1)
                bought = len(set(new_holdings) - set(holdings)) / size
                sold = len(set(holdings) - set(new_holdings)) / size
                rebalance_cost = bought * buy_cost + sold * sell_cost
                holdings = new_holdings
                positions.append({"date": current_date, "holdings": holdings, "turnover": round(bought, 4)})
            if holdings:
                exposure = exposure_by_date.get(current_date, 1.0) if exposure_by_date else 1.0
                gross = float(returns.loc[current_date, holdings].mean())
                day_return = exposure * gross - rebalance_cost * exposure
            else:
                day_return = 0.0
            dates.append(current_date)
            daily_returns.append(day_return)

        returns_series = pd.Series(daily_returns, index=dates)
        equity_values = initial_capital * (1 + returns_series).cumprod()
        equity_curve = pd.DataFrame({"trade_date": dates, "equity": equity_values.values, "daily_return": daily_returns})
        metrics = self.metrics.compute(returns_series)
        return BacktestResult(equity_curve, positions, metrics)

    def _load_price_panel(self, codes: list[str], start_date: date, end_date: date) -> pd.DataFrame:
        frames: list[pd.Series] = []
        for code in codes:
            quotes = self.storage.get_quotes(code, start_date.isoformat(), end_date.isoformat())
            if quotes.empty:
                continue
            series = pd.to_numeric(quotes.set_index("trade_date")["close"], errors="coerce").rename(code)
            frames.append(series)
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, axis=1).sort_index().ffill().dropna(how="all")

    def _load_quotes_by_code(self, codes: list[str], end_date: date) -> dict[str, pd.DataFrame]:
        """为按评分选股加载每只股票的完整 OHLCV（截止 end_date）。"""
        quotes_by_code: dict[str, pd.DataFrame] = {}
        for code in codes:
            quotes = self.storage.get_quotes(code, end_date=end_date.isoformat())
            if not quotes.empty:
                quotes_by_code[code] = quotes.sort_values("trade_date")
        return quotes_by_code

    def _exposure_series(self, prices: pd.DataFrame, tiers: dict | None = None) -> dict:
        """按市场状态给每个交易日一个总仓位上限(0-1)。

        用等权市场代理(全样本均值)自动判断 牛/熊/震荡/极端恐慌，映射到仓位档位 tiers
        (默认 settings.REGIME_TOTAL_POSITION)。熊市/恐慌自动降仓，控制回撤。
        """
        tiers = tiers or settings.REGIME_TOTAL_POSITION
        proxy = prices.mean(axis=1)
        ma20 = proxy.rolling(20).mean()
        ma60 = proxy.rolling(60).mean()
        ret3 = proxy.pct_change(3)
        ret20 = proxy.pct_change(20)
        exposure: dict = {}
        for ts in proxy.index:
            m20, m60, r3, r20 = ma20[ts], ma60[ts], ret3[ts], ret20[ts]
            if pd.isna(m20) or pd.isna(m60):
                regime = "shock"
            elif not pd.isna(r3) and r3 <= -0.06:
                regime = "extreme_fear"            # 近 3 日急跌：恐慌
            elif m20 > m60 and not (not pd.isna(r20) and r20 < -0.03):
                regime = "bull"                     # 短均线在长均线上方且近 20 日未明显走弱
            elif m20 < m60:
                regime = "bear"                     # 短均线下穿长均线：熊
            else:
                regime = "shock"                    # 其余：震荡
            exposure[ts.date() if hasattr(ts, "date") else ts] = tiers.get(regime, 0.6)
        return exposure

    def _members_asof(self, membership: dict, current_date: date) -> set:
        """取不晚于 current_date 的最近一期成分股名单(point-in-time，去幸存者偏差)。"""
        valid = [d for d in membership if d <= current_date]
        if not valid:
            valid = [min(membership)]  # 回测起点早于最早名单时，用最早一期兜底
        return membership[max(valid)]

    def _rebalance_dates(self, dates: pd.Index, freq: str) -> set:
        frame = pd.DataFrame(index=pd.to_datetime(dates))
        if freq == "weekly":
            selected = frame.groupby([frame.index.year, frame.index.isocalendar().week]).head(1).index
        else:
            selected = frame.groupby([frame.index.year, frame.index.month]).head(1).index
        return {item.date() for item in selected}

    def _momentum_scores(self, prices: pd.DataFrame, lookback: int) -> pd.Series:
        if len(prices) <= 1:
            return pd.Series(dtype=float)
        actual_lookback = min(lookback, len(prices) - 1)
        base = prices.iloc[-actual_lookback - 1]
        latest = prices.iloc[-1]
        return ((latest / base) - 1).dropna().sort_values(ascending=False)

    def _composite_scores(
        self,
        prices: pd.DataFrame,
        quotes_by_code: dict[str, pd.DataFrame],
        financials_by_code: dict[str, pd.DataFrame],
        stock_sector: dict[str, str],
        industry_hist: pd.DataFrame,
        current_date: date,
        regime: str,
    ) -> pd.Series:
        """在 current_date 用引擎对每只股票做时间点(point-in-time)综合评分。

        喂入截止当日的行情、财务历史(估值分位)、行业指数(行业强弱)；资金走量价代理；
        消息面无历史数据，回测中不参与(自动降级)。
        """
        industry_returns, industry_ranks = self._industry_strength_asof(industry_hist, current_date)
        scores: dict[str, float] = {}
        for code in prices.columns:
            quotes = quotes_by_code.get(code)
            if quotes is None:
                continue
            point_in_time = quotes[pd.to_datetime(quotes["trade_date"]).dt.date <= current_date]
            if len(point_in_time) < 60:
                continue
            financial_history = self._slice_financials(financials_by_code.get(code), current_date)
            financial = financial_history.iloc[-1].to_dict() if not financial_history.empty else {}
            sector = stock_sector.get(code)
            industry_ctx: dict[str, Any] = {}
            if sector and sector in industry_returns:
                industry_ctx = {"return_20d": industry_returns[sector], "rank_percentile": industry_ranks[sector]}
            context = {
                "stock_info": {"code": code, "industry_l1": sector},
                "quotes": point_in_time,
                "financial": financial,
                "financial_history": financial_history,
                "capital": pd.DataFrame(),
                "industry": industry_ctx,
                "news": [],
            }
            engine_results = {engine.name: engine.score(code, context) for engine in self.engines}
            composite = self.weight_manager.compute_composite(engine_results, regime)
            if composite > 0:
                scores[code] = composite
        if not scores:
            # 没有足够数据评分时退化为动量，保证回测仍能产出结果。
            return self._momentum_scores(prices, lookback=60)
        return pd.Series(scores).sort_values(ascending=False)

    def _load_stock_sectors(self, codes) -> dict[str, str]:
        """code → 一级行业名(中证)，用于行业引擎。"""
        from src.industry.sector_map import csi_sector

        stocks = self.storage.get_active_stocks()
        if stocks.empty:
            return {}
        mapping: dict[str, str] = {}
        for row in stocks.to_dict("records"):
            sector = csi_sector(row.get("industry_l1"))
            if sector:
                mapping[row["code"]] = sector
        return {code: mapping[code] for code in codes if code in mapping}

    def _slice_financials(self, history: pd.DataFrame | None, current_date: date) -> pd.DataFrame:
        if history is None or history.empty or "report_date" not in history:
            return pd.DataFrame()
        sliced = history[pd.to_datetime(history["report_date"]).dt.date <= current_date]
        return sliced.sort_values("report_date")

    def _industry_strength_asof(self, industry_hist: pd.DataFrame, current_date: date) -> tuple[dict[str, float], dict[str, float]]:
        """截止当日各一级行业近 20 日收益与排名分位(point-in-time)。"""
        if industry_hist.empty or "industry_name" not in industry_hist:
            return {}, {}
        hist = industry_hist[pd.to_datetime(industry_hist["trade_date"]).dt.date <= current_date]
        returns: dict[str, float] = {}
        for name, group in hist.groupby("industry_name"):
            close = pd.to_numeric(group.sort_values("trade_date")["close"], errors="coerce").dropna()
            if len(close) >= 21 and close.iloc[-21] != 0:
                returns[str(name)] = float(close.iloc[-1] / close.iloc[-21] - 1)
        if not returns:
            return {}, {}
        ordered = sorted(returns.items(), key=lambda item: item[1], reverse=True)
        ranks = {name: idx / len(ordered) for idx, (name, _) in enumerate(ordered, start=1)}
        return returns, ranks
