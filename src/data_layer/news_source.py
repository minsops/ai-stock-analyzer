"""消息面数据源：个股公告/新闻拉取(东方财富公告接口，httpx 线程安全)。

只取标题与日期等结构化字段，供 NewsEngine 做规则情绪打分、供 DeepSeek 做深度研判。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import httpx
from loguru import logger

ANN_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"


class NewsFetcher:
    """个股公告拉取器。"""

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def get_recent_news(self, code: str, days: int = 30, limit: int = 30) -> list[dict[str, str]]:
        """返回最近 days 天、至多 limit 条公告：[{code, pub_date, title, source}]。"""
        digits = "".join(ch for ch in str(code) if ch.isdigit())[-6:]
        params = {
            "sr": -1,
            "page_size": max(limit, 20),
            "page_index": 1,
            "ann_type": "A",
            "client_source": "web",
            "stock_list": digits,
            "f_node": 0,
            "s_node": 0,
        }
        try:
            response = httpx.get(ANN_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug(f"公告拉取失败 {digits}: {exc}")
            return []

        data = payload.get("data")
        items = data.get("list", []) if isinstance(data, dict) else []
        cutoff = date.today() - timedelta(days=days)
        results: list[dict[str, str]] = []
        for item in items:
            pub = str(item.get("notice_date", ""))[:10]
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            try:
                pub_date = datetime.strptime(pub, "%Y-%m-%d").date()
            except ValueError:
                continue
            if pub_date < cutoff:
                continue
            # pub_date 用 date 对象，便于直接写入 SQLite Date 列。
            results.append({"code": digits, "pub_date": pub_date, "title": title, "source": "eastmoney"})
            if len(results) >= limit:
                break
        return results
