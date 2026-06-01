"""基于 diskcache 的本地数据缓存。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from diskcache import Cache
from loguru import logger

from config import settings


class DataCache:
    """
    本地磁盘缓存。

    缓存 key 格式建议：`{data_type}:{code}:{date}`。
    """

    def __init__(self, cache_dir: str | Path | None = None, ttl_hours: int | None = None) -> None:
        self.cache_dir = Path(cache_dir or settings.DATA_CACHE_DIR)
        self.ttl_seconds = int((ttl_hours or settings.CACHE_TTL_HOURS) * 3600)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache = Cache(str(self.cache_dir))

    def get(self, key: str) -> pd.DataFrame | None:
        """读取缓存中的 DataFrame。"""
        value: Any = self._cache.get(key)
        if value is None:
            return None
        if isinstance(value, pd.DataFrame):
            logger.debug(f"命中缓存: {key}")
            return value.copy()
        logger.warning(f"缓存内容类型异常，已忽略: {key}")
        return None

    def set(self, key: str, data: pd.DataFrame) -> None:
        """写入 DataFrame 缓存。"""
        self._cache.set(key, data.copy(), expire=self.ttl_seconds)
        logger.debug(f"写入缓存: {key}")

    def is_fresh(self, key: str) -> bool:
        """判断缓存是否仍有效。"""
        return self._cache.get(key) is not None

    def clear_expired(self) -> int:
        """清理过期缓存，返回清理条目数。"""
        expired_count = self._cache.expire()
        logger.info(f"已清理过期缓存 {expired_count} 条")
        return int(expired_count)

