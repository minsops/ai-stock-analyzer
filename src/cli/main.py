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
from src.engines import CapitalEngine, EventEngine, IndustryEngine, NewsEngine, TrendEngine, ValueEngine
from src.fusion import ConflictResolver, RegimeDetector, StockFilter, StockRanker, WeightManager
from src.industry import IndustryRanker
from src.llm import LLMAnalyst
from src.risk import PositionSizer
from src.valuation import HistoricalValuation


console = Console()


def make_fetcher(source: str = "akshare"):
    """按数据源返回拉取器。baostock 作为网络受限时的免费备用源。"""
    if source == "baostock":
        from src.data_layer.baostock_source import BaostockFetcher

        return BaostockFetcher()
    return StockDataFetcher()


def make_ranker() -> StockRanker:
    storage = DataStorage()
    fetcher = StockDataFetcher()
    return StockRanker(
        fetcher=fetcher,
        storage=storage,
        engines=[ValueEngine(), TrendEngine(), CapitalEngine(), IndustryEngine(), EventEngine(), NewsEngine()],
        regime_detector=RegimeDetector(),
        weight_manager=WeightManager(),
        conflict_resolver=ConflictResolver(),
        stock_filter=StockFilter(),
    )


def _refresh_news(days: int = 30, limit: int = 30, workers: int = 10, codes: list[str] | None = None) -> dict:
    """刷新消息面公告(供 update-news 命令与调度器复用)。返回 {written, covered}。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from src.data_layer.news_source import NewsFetcher

    storage = DataStorage()
    storage.init_db()
    fetcher = NewsFetcher()
    code_list = codes or pd.read_sql("SELECT DISTINCT code FROM daily_quotes", storage.engine)["code"].tolist()
    if not code_list:
        return {"written": 0, "covered": 0}
    total = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(fetcher.get_recent_news, code, days, limit): code for code in code_list}
        for future in as_completed(futures):
            items = future.result()
            if items:
                total += storage.upsert_news(pd.DataFrame(items))
    return {"written": total, "covered": len(code_list)}


def _refresh_capital(workers: int = 4, codes: list[str] | None = None) -> dict:
    """刷新真实主力资金(供 update-capital 命令与调度器复用)。返回 {written, covered, failed}。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    storage = DataStorage()
    storage.init_db()
    fetcher = StockDataFetcher()  # akshare 源，需能连东财
    code_list = codes or pd.read_sql("SELECT DISTINCT code FROM daily_quotes", storage.engine)["code"].tolist()
    if not code_list:
        return {"written": 0, "covered": 0, "failed": 0}
    total, failed = 0, 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(fetcher.get_capital_flow, code): code for code in code_list}
        for future in as_completed(futures):
            try:
                flow = future.result()
            except Exception:  # noqa: BLE001
                failed += 1
                continue
            if not flow.empty:
                total += storage.upsert_capital_flow(flow)
    return {"written": total, "covered": len(code_list), "failed": failed}


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
@click.option("--sample", type=int, default=None, help="只取列表前 N 只，快速 bootstrap 体验")
@click.option("--codes", default=None, help="只更新指定代码，逗号分隔，如 000001,600519")
@click.option("--index", "index_names", default=None, help="只更新指数成分股，逗号分隔(hs300,zz500,sz50)，需 --source baostock")
@click.option("--years", type=int, default=None, help="行情拉取年数，覆盖默认窗口")
@click.option("--workers", type=int, default=None, help="并发线程数，默认读配置 UPDATE_MAX_WORKERS")
@click.option("--source", type=click.Choice(["akshare", "baostock"]), default="akshare", help="数据源：akshare(东方财富) 或 baostock(免费免token，网络受限时备用)")
@click.option("--include-slow-data", is_flag=True, help="增量更新时也拉取财务、资金和行业数据")
def update_data(
    full_update: bool,
    incremental: bool,
    limit: int | None,
    sample: int | None,
    codes: str | None,
    index_names: str | None,
    years: int | None,
    workers: int | None,
    source: str,
    include_slow_data: bool,
) -> None:
    """全量 / 增量更新数据。"""
    storage = DataStorage()
    fetcher = make_fetcher(source)
    code_list = [code.strip() for code in codes.split(",") if code.strip()] if codes else None
    if index_names:
        index_codes: list[str] = []
        for name in (item.strip() for item in index_names.split(",") if item.strip()):
            members = fetcher.get_index_constituents(name)
            console.print(f"指数 {name} 成分股 {len(members)} 只")
            index_codes.extend(members)
        code_list = list(dict.fromkeys((code_list or []) + index_codes))
    summary = DataUpdater(fetcher, storage).update(
        full=full_update,
        limit=limit,
        include_slow_data=include_slow_data or full_update,
        codes=code_list,
        sample=sample,
        max_workers=workers,
        years=years,
    )
    console.print("[green]数据更新完成[/green]")
    console.print(summary.to_dict())


@cli.command("update-news")
@click.option("--days", type=int, default=30, help="拉取最近多少天公告")
@click.option("--limit", type=int, default=30, help="每只股票最多公告条数")
@click.option("--workers", type=int, default=10, help="并发线程数(httpx 线程安全)")
@click.option("--codes", default=None, help="只更新指定代码，逗号分隔；默认更新已有行情的股票")
def update_news(days: int, limit: int, workers: int, codes: str | None) -> None:
    """拉取个股公告/新闻(消息面引擎数据)。"""
    code_list = [code.strip() for code in codes.split(",") if code.strip()] if codes else None
    result = _refresh_news(days=days, limit=limit, workers=workers, codes=code_list)
    if result["covered"] == 0:
        console.print("[yellow]没有可更新的股票，请先拉取行情[/yellow]")
        return
    console.print(f"[green]消息面更新完成[/green] 写入 {result['written']} 条，覆盖 {result['covered']} 只")


@cli.command("update-capital")
@click.option("--workers", type=int, default=4, help="并发线程数(东财有限流，建议 ≤6)")
@click.option("--codes", default=None, help="只更新指定代码，逗号分隔；默认更新已有行情的股票")
def update_capital(workers: int, codes: str | None) -> None:
    """拉取个股真实主力资金净流入(akshare/东方财富)，供资金引擎用真实数据替代量价代理。

    需运行在能访问东方财富的网络(如部署服务器)。拉到后资金引擎自动优先用真实资金。
    """
    code_list = [code.strip() for code in codes.split(",") if code.strip()] if codes else None
    result = _refresh_capital(workers=workers, codes=code_list)
    if result["covered"] == 0:
        console.print("[yellow]没有可更新的股票，请先拉取行情[/yellow]")
        return
    console.print(
        f"[green]资金面更新完成[/green] 写入 {result['written']} 条，覆盖 {result['covered']} 只，失败 {result['failed']}"
    )


@cli.command("score")
@click.argument("stock_code")
@click.option("--ai", "with_ai", is_flag=True, help="评分后追加 DeepSeek AI 综合分析")
def score(stock_code: str, with_ai: bool) -> None:
    """对单只股票评分。"""
    ranker = make_ranker()
    ensure_recent_quotes(ranker.storage, ranker.fetcher, stock_code)
    report = ranker.score_single(stock_code)
    render_score_report(report)
    if with_ai:
        render_ai_analysis(LLMAnalyst().analyze(report))


@cli.command("analyze")
@click.argument("stock_code")
def analyze(stock_code: str) -> None:
    """对单只股票评分并生成 DeepSeek AI 分析。"""
    ranker = make_ranker()
    ensure_recent_quotes(ranker.storage, ranker.fetcher, stock_code)
    report = ranker.score_single(stock_code)
    render_score_report(report)
    render_ai_analysis(LLMAnalyst().analyze(report))


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


@cli.command("industry-scan")
@click.option("--top-industries", type=int, default=8, help="选取近一年最热门的行业数量")
@click.option("--lookback-days", type=int, default=250, help="行业涨幅回看交易日数(约一年)")
@click.option("--min-industry-stocks", type=int, default=15, help="行业最少样本数，低于此不计入热门(避免小样本虚高)")
@click.option("--min-pick", type=int, default=20, help="每个行业至少取的股票数")
@click.option("--max-pick", type=int, default=50, help="每个行业至多取的股票数")
@click.option("--top-show", type=int, default=8, help="每个行业明细展示的前几只")
@click.option("--ai", "with_ai", is_flag=True, help="为每个热门行业生成产业链(上下游/合作商)AI分析")
def industry_scan(top_industries: int, lookback_days: int, min_industry_stocks: int, min_pick: int, max_pick: int, top_show: int, with_ai: bool) -> None:
    """近一年热门行业 + 行业内分类选股 + 产业链分析。"""
    ranker = make_ranker()
    # 用 baostock 取大盘状态(akshare 行情域名在部分网络不可达)，失败则默认震荡。
    try:
        market_data = make_fetcher("baostock").get_market_overview()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]大盘状态获取失败，按震荡处理: {exc}[/yellow]")
        market_data = {}
    detected = ranker.regime_detector.detect(market_data)
    console.print(f"市场状态: [bold]{detected[0]}[/bold] (置信度 {detected[1]:.0%})")

    def scorer(code: str) -> dict:
        return ranker.score_single(code, market_data=market_data, detected_regime=detected)

    selections = IndustryRanker(ranker.storage).select(
        top_industries=top_industries,
        lookback_days=lookback_days,
        min_stocks=min_industry_stocks,
        scorer=scorer,
        min_pick=min_pick,
        max_pick=max_pick,
    )
    if not selections:
        console.print("[red]没有足够数据计算行业热度，请先用 update-data 拉取个股行情(建议 --index hs300,zz500)。[/red]")
        return

    overview = Table(title=f"近一年热门行业 Top {len(selections)}")
    for column in ("排名", "行业", "近一年均涨幅", "中位涨幅", "样本数", "入选数"):
        overview.add_column(column)
    for sel in selections:
        overview.add_row(
            str(sel.rank), sel.industry, f"{sel.mean_return:.1%}", f"{sel.median_return:.1%}",
            str(sel.stock_count), str(len(sel.top_stocks)),
        )
    console.print(overview)

    analyst = LLMAnalyst() if with_ai else None
    for sel in selections:
        table = Table(title=f"{sel.industry} | 入选 {len(sel.top_stocks)} 只 (展示前 {min(top_show, len(sel.top_stocks))})")
        for column in ("代码", "名称", "综合评分", "近一年涨幅"):
            table.add_column(column)
        for stock in sel.top_stocks[:top_show]:
            table.add_row(
                stock.get("code", ""), str(stock.get("name", "")),
                f"{stock.get('composite_score', 0):.2f}", f"{stock.get('return_1y', 0):.1%}",
            )
        console.print(table)
        if analyst is not None:
            render_industry_chain(analyst.analyze_industry_chain(sel.industry, sel.top_stocks))


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
@click.option("--method", default="score", type=click.Choice(["score", "momentum"]), help="选股方式：综合评分或动量基准")
@click.option("--timing", is_flag=True, help="开启熊市择时降仓(按市场状态缩放总仓位)")
def backtest(start_date: str, end_date: str, top_n: int, freq: str, capital: float, method: str, timing: bool) -> None:
    """运行基础回测。"""
    storage = DataStorage()
    result = BacktestSimulator(storage).run(
        {
            "start_date": start_date,
            "end_date": end_date,
            "top_n": top_n,
            "rebalance_freq": freq,
            "initial_capital": capital,
            "selection": method,
            "regime_timing": timing,
        }
    )
    console.print(result.metrics)


@cli.command("serve")
@click.option("--port", type=int, default=8000, help="服务端口")
def serve(port: int) -> None:
    """启动 FastAPI 服务。"""
    import uvicorn

    uvicorn.run("src.api.main:app", host="0.0.0.0", port=port, reload=False)


@cli.command("schedule")
@click.option("--update-time", default="17:30", help="每日增量更新时间(收盘后)，24h HH:MM")
@click.option("--scan-time", default="18:00", help="每日评分扫描时间，HH:MM(须晚于更新)")
@click.option("--top-n", type=int, default=30, help="每日扫描落库的排行条数")
@click.option("--source", type=click.Choice(["akshare", "baostock"]), default="akshare", help="行情数据源")
@click.option("--with-news/--no-news", default=True, help="扫描前是否刷新消息面公告")
@click.option("--with-capital/--no-capital", default=False, help="扫描前是否刷新真实主力资金(需能连东财)")
@click.option("--news-days", type=int, default=30, help="消息面回看天数")
@click.option("--capital-workers", type=int, default=4, help="资金面并发线程数(东财限流，建议≤6)")
@click.option("--run-once", is_flag=True, help="立即跑一遍(更新→[资金]→[消息]→扫描)后退出，不进入常驻循环")
def schedule_cmd(
    update_time: str,
    scan_time: str,
    top_n: int,
    source: str,
    with_news: bool,
    with_capital: bool,
    news_days: int,
    capital_workers: int,
    run_once: bool,
) -> None:
    """容器内常驻调度器:每日定时增量更新+评分扫描(可选消息/资金)，刷新仪表盘数据。

    部署时作为独立进程长驻(docker-compose 的 scheduler 服务)，替代脆弱的宿主机 crontab。
    """
    import time

    from src.scheduler import SchedulerService

    updater = DataUpdater(make_fetcher(source), DataStorage())
    news_fn = (lambda: _refresh_news(days=news_days)) if with_news else None
    capital_fn = (lambda: _refresh_capital(workers=capital_workers)) if with_capital else None
    service = SchedulerService(updater, make_ranker(), news_fn=news_fn, capital_fn=capital_fn)

    if run_once:
        console.print("[cyan]立即执行一遍每日任务…[/cyan]")
        for result in (
            service.run_daily_update(),
            service.run_daily_capital(),
            service.run_daily_news(),
            service.run_daily_scan(top_n=top_n),
        ):
            tag = "[green]OK[/green]" if result.ok else "[red]FAIL[/red]"
            console.print(f"{tag} {result.name}: {result.detail}")
        return

    service.register_daily_jobs(update_time=update_time, scan_time=scan_time, top_n=top_n)
    console.print(
        f"[green]调度器已启动[/green] 更新 {update_time} · 扫描 {scan_time} · TopN {top_n}"
        f"{' · 消息' if with_news else ''}{' · 资金' if with_capital else ''}(Ctrl+C 退出)"
    )
    while True:
        service.run_pending()
        time.sleep(30)


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
    available = report.get("available_engines")
    total = report.get("total_engines")
    engine_note = f"  参与引擎: {available}/{total}" if available is not None else ""
    if available is not None and total and available <= 2:
        engine_note += " [yellow](信号偏薄，综合分参考性有限)[/yellow]"
    console.print(f"市场状态: {report['regime']}  过滤: {report['filter_reason']}  冲突: {report['conflict_action']}{engine_note}")
    render_trade_plan(report.get("trade_plan"))


def render_trade_plan(plan: dict | None) -> None:
    if not plan or not plan.get("available"):
        return
    console.print()
    console.print(f"[bold]交易计划[/bold] (现价 {plan['last_close']}  操作: {plan['action']}  周期: {plan['horizon']})")
    console.print(
        f"  建议买入区间: [green]{plan['entry_low']} ~ {plan['entry_high']}[/green]"
        f"   止损: [red]{plan['stop_loss']}[/red]"
        f"   技术目标: {plan['target_technical']} (+{plan['upside_technical_pct']}%, 风报比 {plan['risk_reward']})"
    )
    if plan.get("target_value") is not None:
        console.print(f"  价值目标(PE回归中位): {plan['target_value']} ({plan['upside_value_pct']:+}%)")
    console.print("[dim]价格建议基于技术/估值测算，仅供研究参考，不构成投资建议。[/dim]")


def render_industry_chain(chain: dict) -> None:
    if not chain.get("available"):
        console.print(f"[yellow]产业链分析不可用：{chain.get('reason', '未知原因')}[/yellow]")
        return
    console.print(f"[bold cyan]产业链分析 · {chain.get('industry', '')}[/bold cyan]  模型: {chain.get('model', '-')}")
    if chain.get("summary"):
        console.print(f"  概述: {chain['summary']}")
    for title, key in (("上游", "upstream"), ("下游", "downstream"), ("合作配套", "partners"), ("风险", "risks")):
        items = chain.get(key) or []
        if items:
            console.print(f"  {title}: " + "；".join(str(item) for item in items))
    beneficiaries = chain.get("chain_beneficiaries") or []
    if beneficiaries:
        console.print("  产业链受益标的:")
        for item in beneficiaries[:10]:
            if isinstance(item, dict):
                code = f"({item.get('code')})" if item.get("code") else ""
                console.print(f"    - {item.get('name', '')}{code} [{item.get('role', '')}] {item.get('reason', '')}")
    console.print("[dim]产业链分析由 AI 生成，仅供研究参考，可能存在偏差。[/dim]")


def render_ai_analysis(analysis: dict) -> None:
    if not analysis.get("available"):
        console.print(f"[yellow]AI 分析不可用：{analysis.get('reason', '未知原因')}[/yellow]")
        return
    console.print()
    rating = analysis.get("rating") or "-"
    confidence = analysis.get("confidence")
    confidence_text = f"{confidence:.0%}" if isinstance(confidence, (int, float)) else "-"
    console.print(f"[bold magenta]AI 评级:[/bold magenta] {rating}  置信度: {confidence_text}  模型: {analysis.get('model', '-')}")
    if analysis.get("summary"):
        console.print(f"[bold]结论:[/bold] {analysis['summary']}")
    for title, key in (("看多", "bull_points"), ("看空", "bear_points"), ("风险", "risks")):
        items = analysis.get(key) or []
        if items:
            console.print(f"[bold]{title}:[/bold] " + "；".join(str(item) for item in items))
    if analysis.get("suggested_action"):
        console.print(f"[bold]操作建议:[/bold] {analysis['suggested_action']}")
    console.print("[dim]AI 分析仅供研究参考，不构成投资建议。[/dim]")


if __name__ == "__main__":
    cli()
