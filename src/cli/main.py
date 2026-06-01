"""命令行入口。"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys

import click
import pandas as pd
from rich.console import Console
from rich.table import Table

from config.logging_config import setup_logging
from src.backtest import BacktestSimulator
from src.data_layer import DataStorage, DataUpdater, StockDataFetcher
from src.engines import CapitalEngine, EventEngine, IndustryEngine, TrendEngine, ValueEngine
from src.fusion import ConflictResolver, RegimeDetector, StockFilter, StockRanker, WeightManager
from src.risk import PositionSizer
from src.valuation import HistoricalValuation


console = Console()


def make_ranker() -> StockRanker:
    storage = DataStorage()
    fetcher = StockDataFetcher()
    return StockRanker(
        fetcher=fetcher,
        storage=storage,
        engines=[ValueEngine(), TrendEngine(), CapitalEngine(), IndustryEngine(), EventEngine()],
        regime_detector=RegimeDetector(),
        weight_manager=WeightManager(),
        conflict_resolver=ConflictResolver(),
        stock_filter=StockFilter(),
    )


@click.group()
def cli() -> None:
    """AI 量化选股分析系统。"""
    setup_logging()


@cli.command("init-db")
def init_db() -> None:
    """初始化数据库表结构。"""
    storage = DataStorage()
    storage.init_db()
    console.print("[green]数据库初始化完成[/green]")


@cli.command("update-data")
@click.option("--full", "full_update", is_flag=True, help="执行全量更新")
@click.option("--incremental", is_flag=True, help="执行增量更新")
@click.option("--limit", type=int, default=None, help="限制更新股票数量，便于调试")
@click.option("--include-slow-data", is_flag=True, help="增量更新时也拉取财务、资金和行业数据")
def update_data(full_update: bool, incremental: bool, limit: int | None, include_slow_data: bool) -> None:
    """全量 / 增量更新数据。"""
    storage = DataStorage()
    fetcher = StockDataFetcher()
    summary = DataUpdater(fetcher, storage).update(full=full_update, limit=limit, include_slow_data=include_slow_data or full_update)
    console.print("[green]数据更新完成[/green]")
    console.print(summary.to_dict())


@cli.command("score")
@click.argument("stock_code")
def score(stock_code: str) -> None:
    """对单只股票评分。"""
    ranker = make_ranker()
    ensure_recent_quotes(ranker.storage, ranker.fetcher, stock_code)
    report = ranker.score_single(stock_code)
    render_score_report(report)


@cli.command("scan")
@click.option("--top-n", type=int, default=50, help="输出 Top N")
def scan(top_n: int) -> None:
    """全市场扫描。"""
    ranker = make_ranker()
    result = ranker.scan_all(top_n=top_n)
    table = Table(title=f"综合评分 Top {top_n}")
    for column in ("排名", "代码", "名称", "行业", "综合评分"):
        table.add_column(column)
    for idx, row in enumerate(result.to_dict("records"), start=1):
        table.add_row(str(idx), row["code"], str(row.get("name", "")), str(row.get("industry", "")), f"{row['composite_score']:.2f}")
    console.print(table)


@cli.command("regime")
def regime() -> None:
    """输出当前市场状态。"""
    fetcher = StockDataFetcher()
    detector = RegimeDetector()
    regime_name, confidence, details = detector.detect(fetcher.get_market_overview())
    console.print(f"市场状态: [bold]{regime_name}[/bold]，置信度: {confidence:.2f}")
    console.print(details)


@cli.command("valuation")
@click.argument("stock_code")
def valuation(stock_code: str) -> None:
    """输出估值分析报告。"""
    storage = DataStorage()
    valuation_service = HistoricalValuation(storage)
    table = Table(title=f"{stock_code} 历史估值")
    table.add_column("指标")
    table.add_column("当前值")
    table.add_column("分位")
    table.add_column("判断")
    for metric in ("pe_ttm", "pb", "ps_ttm", "dividend_yield"):
        result = valuation_service.compute_percentile(stock_code, metric)
        percentile = result.get("percentile")
        table.add_row(
            metric,
            "-" if result.get("current_value") is None else f"{result['current_value']:.2f}",
            "-" if percentile is None else f"{percentile:.0%}",
            result.get("assessment", "unknown"),
        )
    console.print(table)


@cli.command("position")
@click.argument("stock_code")
@click.option("--score", "composite_score", type=float, required=True, help="综合评分")
@click.option("--regime", "regime_name", default="shock", help="市场状态")
@click.option("--capital", type=float, required=True, help="总资金")
def position(stock_code: str, composite_score: float, regime_name: str, capital: float) -> None:
    """输出仓位建议。"""
    suggestion = PositionSizer().suggest(stock_code, composite_score, regime_name, capital)
    console.print(suggestion)


@cli.command("backtest")
@click.option("--start", "start_date", required=True, help="开始日期 YYYY-MM-DD")
@click.option("--end", "end_date", required=True, help="结束日期 YYYY-MM-DD")
@click.option("--top-n", type=int, default=10, help="持仓数量")
@click.option("--freq", default="monthly", type=click.Choice(["weekly", "monthly"]), help="调仓频率")
@click.option("--capital", type=float, default=100_000, help="初始资金")
def backtest(start_date: str, end_date: str, top_n: int, freq: str, capital: float) -> None:
    """运行基础回测。"""
    storage = DataStorage()
    result = BacktestSimulator(storage).run(
        {
            "start_date": start_date,
            "end_date": end_date,
            "top_n": top_n,
            "rebalance_freq": freq,
            "initial_capital": capital,
        }
    )
    console.print(result.metrics)


@cli.command("serve")
@click.option("--port", type=int, default=8000, help="服务端口")
def serve(port: int) -> None:
    """启动 FastAPI 服务。"""
    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=port, reload=False)


def ensure_recent_quotes(storage: DataStorage, fetcher: StockDataFetcher, code: str) -> None:
    if not storage.get_quotes(code).empty:
        return
    end = date.today()
    start = end - timedelta(days=365)
    quotes = fetcher.get_daily_quotes(code, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    if not quotes.empty:
        storage.upsert_daily_quotes(quotes)


def render_score_report(report: dict) -> None:
    title = f"{report['name']} ({report['code']}) 综合评分: {report['composite_score']:.2f}/100"
    table = Table(title=title)
    table.add_column("引擎")
    table.add_column("分数")
    table.add_column("置信度")
    table.add_column("核心信号")
    for name, detail in report["engine_scores"].items():
        table.add_row(
            name,
            f"{detail['score']:.2f}",
            f"{detail['confidence']:.0%}",
            "；".join(detail.get("signals", [])[:3]),
        )
    console.print(table)
    console.print(f"市场状态: {report['regime']}  过滤: {report['filter_reason']}  冲突: {report['conflict_action']}")


if __name__ == "__main__":
    cli()
