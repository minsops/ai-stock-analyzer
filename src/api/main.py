"""FastAPI 应用入口。"""

from __future__ import annotations

from fastapi import FastAPI

from config.logging_config import setup_logging
from src.api.routes import backtest, dashboard, industry, ranking, regime, scan, stock, watchlist


setup_logging()

app = FastAPI(title="AI 量化选股分析系统", version="0.1.0")

app.include_router(stock.router, prefix="/api/v1")
app.include_router(scan.router, prefix="/api/v1")
app.include_router(ranking.router, prefix="/api/v1")
app.include_router(regime.router, prefix="/api/v1")
app.include_router(backtest.router, prefix="/api/v1")
app.include_router(industry.router, prefix="/api/v1")
app.include_router(watchlist.router, prefix="/api/v1")
app.include_router(dashboard.router)  # 浏览器仪表盘页面在根路径 /


@app.get("/api/v1/health")
def health() -> dict:
    return {"status": "ok"}

