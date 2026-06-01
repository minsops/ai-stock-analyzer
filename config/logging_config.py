"""loguru 日志配置。"""

from __future__ import annotations

import sys

from loguru import logger

from config import settings


def setup_logging() -> None:
    """初始化日志输出到终端和文件。"""
    settings.ensure_directories()
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level}</level> | {name}:{function}:{line} - {message}",
    )
    logger.add(
        settings.LOG_DIR / "app.log",
        level=settings.LOG_LEVEL,
        rotation="10 MB",
        retention="14 days",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
    )


setup_logging()

