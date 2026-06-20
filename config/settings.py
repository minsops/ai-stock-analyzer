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

# 数据更新并发（网络 I/O 密集，适度并发可显著提速）
UPDATE_MAX_WORKERS = int(os.getenv("UPDATE_MAX_WORKERS", "8"))
INDUSTRY_MAP_MAX_WORKERS = int(os.getenv("INDUSTRY_MAP_MAX_WORKERS", "8"))

# A股行情数据域名直连：很多用户开了 Clash/VPN 全局代理，会把这些国内行情请求
# 也代理到境外，导致连接被重置（RemoteDisconnected）。这里把它们加入 NO_PROXY，
# 让 requests/httpx 对这些域名直连，绕过系统/全局代理。设 AKSHARE_BYPASS_PROXY=0 可关闭。
AKSHARE_DIRECT_DOMAINS = os.getenv(
    "AKSHARE_DIRECT_DOMAINS",
    "eastmoney.com,push2.eastmoney.com,push2his.eastmoney.com,sina.com.cn,sinajs.cn,qq.com,legulegu.com,hexun.com,cninfo.com.cn",
)
if os.getenv("AKSHARE_BYPASS_PROXY", "1") == "1":
    _existing_no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    _merged_no_proxy = ",".join(part for part in (_existing_no_proxy, AKSHARE_DIRECT_DOMAINS) if part)
    os.environ["NO_PROXY"] = _merged_no_proxy
    os.environ["no_proxy"] = _merged_no_proxy

# DeepSeek API（OpenAI 兼容的 chat/completions 接口）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_TIMEOUT_SECONDS = int(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "60"))
DEEPSEEK_TEMPERATURE = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.3"))
# deepseek-chat 现为混合推理模型，会先产出 reasoning_content 再产出 content，
# token 预算要足够大，否则推理吃满 max_tokens 导致 content 为空。
DEEPSEEK_MAX_TOKENS = int(os.getenv("DEEPSEEK_MAX_TOKENS", "3000"))
DEEPSEEK_RETRY_TIMES = int(os.getenv("DEEPSEEK_RETRY_TIMES", "2"))

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
# 各市场状态下的总仓位上限(自动按牛/震荡/熊/极恐切换，控制回撤而不过度牺牲牛市收益)。
# "进取"档经回测在控回撤与保收益之间最平衡(3年回撤 -15% vs 满仓 -19%，收益 110% vs 121%)。
REGIME_TOTAL_POSITION = {
    "bull": 1.00,
    "shock": 0.80,
    "bear": 0.40,
    "extreme_fear": 0.10,   # 极度恐慌(近 3 日急跌)近乎清仓，最大化回撤保护
    "extreme_greed": 0.60,
}

# 因子倾斜(路线B落地):扫描排序时把综合分向稳健因子集(低PE+ROE+净利同比+60日反转)
# 轻度倾斜。每单位因子组合 z(截面、行业+市值中性化)给综合分加的"分数点"，0=关闭。
# 经回测验证(scripts/factor_tilt_backtest.py)倾斜净改善 年化+夏普+回撤;但因子在同段样本
# 选出，存在过拟合风险，故默认保守(温和倾斜)、可经 FACTOR_TILT_STRENGTH 环境变量调/关。
FACTOR_TILT_STRENGTH = float(os.getenv("FACTOR_TILT_STRENGTH", "4.0"))

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
