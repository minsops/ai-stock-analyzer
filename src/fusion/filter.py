"""股票硬性过滤规则。"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from config import settings


class StockFilter:
    """硬性过滤规则，不通过直接排除。"""

    DEFAULT_RULES = settings.FILTER_RULES

    def __init__(self, rules: dict[str, Any] | None = None) -> None:
        self.rules = {**self.DEFAULT_RULES, **(rules or {})}

    def apply(self, code: str, stock_info: dict[str, Any], quotes: pd.DataFrame, financial: dict[str, Any] | None = None) -> tuple[bool, str]:
        financial = financial or {}
        name = str(stock_info.get("name", ""))
        if self.rules["exclude_st"] and (stock_info.get("is_st") or "ST" in name.upper()):
            return False, "ST 股票被过滤"

        list_date = stock_info.get("list_date")
        if self.rules["exclude_new_stock_days"] and list_date:
            listed_days = (date.today() - pd.to_datetime(list_date).date()).days
            if listed_days < self.rules["exclude_new_stock_days"]:
                return False, f"上市不足 {self.rules['exclude_new_stock_days']} 天"

        if quotes is None or quotes.empty:
            return False, "缺少行情数据"

        recent = quotes.sort_values("trade_date").tail(20)
        if self.rules["exclude_suspended"] and "volume" in recent and pd.to_numeric(recent["volume"], errors="coerce").tail(1).fillna(0).iloc[-1] == 0:
            return False, "最近交易日疑似停牌"

        if self.rules["min_daily_amount"] and "amount" in recent:
            avg_amount = pd.to_numeric(recent["amount"], errors="coerce").mean()
            if pd.notna(avg_amount) and avg_amount < self.rules["min_daily_amount"]:
                return False, f"日均成交额 {avg_amount:.0f} 低于阈值"

        pe = financial.get("pe_ttm")
        if pe is not None and pd.notna(pe):
            if self.rules["max_pe_ttm"] is not None and pe > self.rules["max_pe_ttm"]:
                return False, f"PE {pe:.2f} 高于阈值"
            if self.rules["min_pe_ttm"] is not None and pe < self.rules["min_pe_ttm"]:
                return False, f"PE {pe:.2f} 低于阈值"

        # 金融业(银行/保险/证券)天然高杠杆(资产负债率常 >90%)，不适用一般负债率上限。
        industry_name = str(stock_info.get("industry_l1") or "")
        is_financial = any(keyword in industry_name for keyword in ("银行", "保险", "证券", "金融", "货币", "资本市场"))
        debt_ratio = financial.get("debt_ratio")
        if not is_financial and debt_ratio is not None and pd.notna(debt_ratio) and debt_ratio > self.rules["max_debt_ratio"]:
            return False, f"资产负债率 {debt_ratio:.2f}% 高于阈值"
        return True, "通过过滤"

