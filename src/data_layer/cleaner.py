"""数据清洗与标准化。"""

from __future__ import annotations

from datetime import date
from typing import Iterable

import numpy as np
import pandas as pd
from loguru import logger


def _first_existing_column(df: pd.DataFrame, candidates: Iterable[str]) -> str | None:
    for column in candidates:
        if column in df.columns:
            return column
    return None


def _to_date_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.date


def _to_float_series(series: pd.Series) -> pd.Series:
    if series.dtype == object:
        series = series.astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False)
    return pd.to_numeric(series, errors="coerce").astype(float)


def _quarter_end(value: date | pd.Timestamp | str | None) -> date | None:
    if pd.isna(value):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    month = ((int(ts.month) - 1) // 3 + 1) * 3
    return pd.Timestamp(year=int(ts.year), month=month, day=1).to_period("M").end_time.date()


class DataCleaner:
    """数据清洗与标准化。"""

    QUOTE_COLUMN_MAP = {
        "日期": "trade_date",
        "股票代码": "code",
        "代码": "code",
        "开盘": "open",
        "最高": "high",
        "最低": "low",
        "收盘": "close",
        "成交量": "volume",
        "成交额": "amount",
        "换手率": "turnover",
        "涨跌幅": "pct_change",
    }

    STOCK_COLUMN_MAP = {
        "代码": "code",
        "股票代码": "code",
        "名称": "name",
        "股票简称": "name",
        "市场": "market",
        "行业": "industry_l1",
        "所属行业": "industry_l1",
        "上市时间": "list_date",
        "上市日期": "list_date",
    }

    FINANCIAL_COLUMN_MAP = {
        "日期": "report_date",
        "报告期": "report_date",
        "数据日期": "report_date",
        "trade_date": "report_date",
        "pe_ttm": "pe_ttm",
        "pb": "pb",
        "ps_ttm": "ps_ttm",
        # 东方财富个股估值 stock_value_em 的列名
        "PE(TTM)": "pe_ttm",
        "PE(动)": "pe_ttm",
        "市盈率(TTM)": "pe_ttm",
        "市盈率": "pe_ttm",
        "市净率": "pb",
        "市销率": "ps_ttm",
        "市销率(TTM)": "ps_ttm",
        "dv_ttm": "dividend_yield",
        "股息率": "dividend_yield",
        "股息率(TTM)": "dividend_yield",
        "净资产收益率": "roe",
        "加权净资产收益率": "roe",
        # 东财/同花顺 stock_financial_analysis_indicator 的真实列名（带百分号后缀）
        "加权净资产收益率(%)": "roe",
        "净资产收益率(%)": "roe",
        "摊薄净资产收益率(%)": "roe",
        "营业总收入": "revenue",
        "营业收入": "revenue",
        "归属母公司股东的净利润": "net_profit",
        "净利润": "net_profit",
        "营业总收入同比增长率": "revenue_yoy",
        "营业收入同比增长率": "revenue_yoy",
        "主营业务收入增长率(%)": "revenue_yoy",
        "营业收入增长率(%)": "revenue_yoy",
        "净利润同比增长率": "profit_yoy",
        "净利润增长率(%)": "profit_yoy",
        "销售毛利率": "gross_margin",
        "销售毛利率(%)": "gross_margin",
        "毛利率": "gross_margin",
        "资产负债率": "debt_ratio",
        "资产负债率(%)": "debt_ratio",
        "经营现金流量净额": "free_cash_flow",
    }

    CAPITAL_COLUMN_MAP = {
        "日期": "trade_date",
        "代码": "code",
        "股票代码": "code",
        "主力净流入-净额": "main_net_inflow",
        "主力净流入净额": "main_net_inflow",
        "北向资金净流入": "north_net_flow",
        "融资余额": "margin_balance",
        "股东户数": "holder_count",
    }

    INDUSTRY_COLUMN_MAP = {
        "日期": "trade_date",
        "板块代码": "industry_code",
        "代码": "industry_code",
        "板块名称": "industry_name",
        "名称": "industry_name",
        "收盘": "close",
        "涨跌幅": "pct_change",
        "成交量": "volume",
    }

    def clean_stocks(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗股票基础信息。"""
        if df.empty:
            return self._empty_stocks()
        result = self._rename(df, self.STOCK_COLUMN_MAP)
        result["code"] = result.get("code", pd.Series(dtype=str)).astype(str).str.extract(r"(\d{6})", expand=False)
        result["market"] = result.get("market", result["code"].map(self._infer_market)).fillna(result["code"].map(self._infer_market))
        result["name"] = result.get("name", "").astype(str)
        result["industry_l1"] = result.get("industry_l1", pd.Series(index=result.index, dtype=object))
        result["industry_l2"] = result.get("industry_l2", pd.Series(index=result.index, dtype=object))
        result["list_date"] = _to_date_series(result["list_date"]) if "list_date" in result else pd.Series(index=result.index, dtype=object)
        result["is_st"] = result["name"].str.contains("ST", case=False, na=False)
        result["is_active"] = True
        return result[["code", "name", "market", "industry_l1", "industry_l2", "list_date", "is_st", "is_active"]].dropna(subset=["code"])

    def clean_quotes(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗日线数据。"""
        if df.empty:
            return self._empty_quotes()
        result = self._rename(df, self.QUOTE_COLUMN_MAP)
        if "trade_date" not in result:
            logger.warning("日线数据缺少日期列")
            return self._empty_quotes()
        result["trade_date"] = _to_date_series(result["trade_date"])
        for column in ("open", "high", "low", "close", "volume", "amount", "turnover", "pct_change"):
            if column not in result:
                result[column] = np.nan
            result[column] = _to_float_series(result[column])
        if "code" not in result:
            result["code"] = None
        result = result.dropna(how="all").dropna(subset=["trade_date"]).sort_values("trade_date")
        return result[["code", "trade_date", "open", "high", "low", "close", "volume", "amount", "turnover", "pct_change"]]

    def clean_financial(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗财务数据。"""
        if df.empty:
            return self._empty_financial()
        result = self._rename(df, self.FINANCIAL_COLUMN_MAP)
        if "report_date" in result:
            result["report_date"] = result["report_date"].map(_quarter_end)
        else:
            result["report_date"] = None
        if "code" not in result:
            result["code"] = None
        numeric_columns = [
            "pe_ttm",
            "pb",
            "ps_ttm",
            "roe",
            "revenue",
            "net_profit",
            "revenue_yoy",
            "profit_yoy",
            "gross_margin",
            "debt_ratio",
            "free_cash_flow",
            "dividend_yield",
        ]
        for column in numeric_columns:
            if column not in result:
                result[column] = np.nan
            result[column] = _to_float_series(result[column])
        result = result.dropna(subset=["report_date"]).drop_duplicates(["code", "report_date"], keep="last")
        return result[["code", "report_date", *numeric_columns]]

    def clean_capital_flow(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗资金面数据。"""
        if df.empty:
            return self._empty_capital_flow()
        result = self._rename(df, self.CAPITAL_COLUMN_MAP)
        if "trade_date" in result:
            result["trade_date"] = _to_date_series(result["trade_date"])
        else:
            result["trade_date"] = None
        if "code" not in result:
            result["code"] = None
        for column in ("main_net_inflow", "north_net_flow", "margin_balance"):
            if column not in result:
                result[column] = np.nan
            result[column] = _to_float_series(result[column])
        if "holder_count" not in result:
            result["holder_count"] = np.nan
        result["holder_count"] = pd.to_numeric(result["holder_count"], errors="coerce").astype("Int64")
        result = result.dropna(subset=["trade_date"])
        return result[["code", "trade_date", "main_net_inflow", "north_net_flow", "margin_balance", "holder_count"]]

    def clean_industry_index(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗行业指数数据。"""
        if df.empty:
            return self._empty_industry_index()
        result = self._rename(df, self.INDUSTRY_COLUMN_MAP)
        result["trade_date"] = _to_date_series(result["trade_date"]) if "trade_date" in result else None
        if "industry_code" not in result:
            result["industry_code"] = None
        if "industry_name" not in result:
            result["industry_name"] = None
        for column in ("close", "pct_change", "volume"):
            if column not in result:
                result[column] = np.nan
            result[column] = _to_float_series(result[column])
        result = result.dropna(subset=["industry_code", "trade_date"])
        return result[["industry_code", "industry_name", "trade_date", "close", "pct_change", "volume"]]

    def _rename(self, df: pd.DataFrame, column_map: dict[str, str]) -> pd.DataFrame:
        normalized = df.copy()
        normalized.columns = [str(column).strip() for column in normalized.columns]
        renamed = normalized.rename(columns={column: column_map[column] for column in normalized.columns if column in column_map})
        # 多个原始列可能映射到同一目标列（如不同来源的 PE 列），去重保留第一个，避免重复列名。
        if renamed.columns.duplicated().any():
            renamed = renamed.loc[:, ~renamed.columns.duplicated()]
        return renamed

    def _infer_market(self, code: str | None) -> str | None:
        if not code or pd.isna(code):
            return None
        code = str(code)
        if code.startswith(("6", "9")):
            return "SH"
        if code.startswith(("0", "2", "3")):
            return "SZ"
        if code.startswith(("4", "8")):
            return "BJ"
        return None

    def _empty_stocks(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["code", "name", "market", "industry_l1", "industry_l2", "list_date", "is_st", "is_active"])

    def _empty_quotes(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["code", "trade_date", "open", "high", "low", "close", "volume", "amount", "turnover", "pct_change"])

    def _empty_financial(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["code", "report_date", "pe_ttm", "pb", "ps_ttm", "roe", "revenue", "net_profit", "revenue_yoy", "profit_yoy", "gross_margin", "debt_ratio", "free_cash_flow", "dividend_yield"])

    def _empty_capital_flow(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["code", "trade_date", "main_net_inflow", "north_net_flow", "margin_balance", "holder_count"])

    def _empty_industry_index(self) -> pd.DataFrame:
        return pd.DataFrame(columns=["industry_code", "industry_name", "trade_date", "close", "pct_change", "volume"])

