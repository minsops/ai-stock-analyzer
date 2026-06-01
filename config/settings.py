"""全局配置。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# 路径
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
DB_DIR = DATA_DIR / "db"

# 数据库
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_DIR / 'stock_analyzer.db'}")

# 数据采集
FETCH_DELAY_SECONDS = float(os.getenv("FETCH_DELAY_SECONDS", "0.5"))
FETCH_RETRY_TIMES = int(os.getenv("FETCH_RETRY_TIMES", "3"))
FETCH_RETRY_INTERVAL_SECONDS = float(os.getenv("FETCH_RETRY_INTERVAL_SECONDS", "2"))
FETCH_TIMEOUT_SECONDS = int(os.getenv("FETCH_TIMEOUT_SECONDS", "30"))
CACHE_TTL_HOURS = int(os.getenv("DATA_CACHE_TTL_HOURS", "12"))
DATA_CACHE_DIR = Path(os.getenv("DATA_CACHE_DIR", str(RAW_DATA_DIR)))

# 评分引擎
LOOKBACK_TRADING_DAYS = 250
VALUATION_LOOKBACK_YEARS = 5

# 过滤规则
FILTER_RULES = {
    "exclude_st": True,
    "exclude_new_stock_days": 365,
    "min_daily_amount": 5_000_000,
    "exclude_suspended": True,
    "max_pe_ttm": 300,
    "min_pe_ttm": 0,
    "max_debt_ratio": 90,
}

# 冲突处理
CONFLICT_THRESHOLD = 40
QUARANTINE_THRESHOLD = 60

# 仓位管理
MAX_SINGLE_POSITION = 0.20
MAX_INDUSTRY_POSITION = 0.40
REGIME_TOTAL_POSITION = {
    "bull": 0.80,
    "shock": 0.60,
    "bear": 0.40,
    "extreme_fear": 0.20,
    "extreme_greed": 0.50,
}

# 回测
BACKTEST_COMMISSION_RATE = 0.0003
BACKTEST_SLIPPAGE = 0.001
BACKTEST_STAMP_TAX = 0.001
RISK_FREE_RATE = 0.02

# API
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", "8000"))

# 日志
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = PROJECT_ROOT / "logs"


def ensure_directories() -> None:
    """创建运行所需目录。"""
    for path in (DATA_DIR, RAW_DATA_DIR, PROCESSED_DATA_DIR, DB_DIR, LOG_DIR, DATA_CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)


ensure_directories()

