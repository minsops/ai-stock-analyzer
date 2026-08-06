"""Baostock 数据源（免费、免 token）。

实现与 ``StockDataFetcher`` 相同的方法签名，可直接注入 ``DataUpdater``。
当 AKShare 的东方财富行情接口在某些网络环境下不可达时，可用 baostock 作为
A 股日线/估值的备用数据源。baostock 暂不提供个股资金流和行业指数，对应方法返回空。
"""

from __future__ import annotations

from datetime import date, timedelta
import threading
from typing import Any

import pandas as pd
from loguru import logger

QUOTE_COLUMNS = ["code", "trade_date", "open", "high", "low", "close", "volume", "amount", "turnover", "pct_change"]
FINANCIAL_COLUMNS = [
    "code", "report_date", "pe_ttm", "pb", "ps_ttm", "roe", "revenue", "net_profit",
    "revenue_yoy", "profit_yoy", "gross_margin", "debt_ratio", "free_cash_flow", "dividend_yield",
]
STOCK_COLUMNS = ["code", "name", "market", "industry_l1", "industry_l2", "list_date", "is_st", "is_active"]


class BaostockFetcher:
    """基于 baostock 的 A 股数据拉取器。"""

    _lock = threading.Lock()

    def __init__(self, valuation_lookback_years: int = 5, fetch_fundamentals: bool = True) -> None:
        self._bs = None
        self._logged_in = False
        self.valuation_lookback_years = valuation_lookback_years
        # 是否拉取季度基本面(ROE/同比/负债率等)；每只多几次接口调用，但让价值引擎完整生效。
        self.fetch_fundamentals = fetch_fundamentals

    @property
    def bs(self) -> Any:
        if self._bs is None:
            import baostock as bs

            self._bs = bs
        self._ensure_login()
        return self._bs

    def _ensure_login(self) -> None:
        if self._logged_in:
            return
        with self._lock:
            if self._logged_in:
                return
            result = self._bs.login()
            if result.error_code != "0":
                raise RuntimeError(f"baostock 登录失败: {result.error_msg}")
            self._logged_in = True
            logger.info("baostock 登录成功")

    def _normalize_code(self, code: str) -> str:
        digits = "".join(ch for ch in str(code) if ch.isdigit())
        return digits[-6:] if len(digits) >= 6 else digits

    def _to_bs_code(self, code: str) -> str:
        c = self._normalize_code(code)
        if c.startswith(("6", "9")):
            return f"sh.{c}"
        if c.startswith(("4", "8")):
            return f"bj.{c}"
        return f"sz.{c}"

    def _rs_to_df(self, rs) -> pd.DataFrame:
        rows: list[list[str]] = []
        while rs.error_code == "0" and rs.next():
            rows.append(rs.get_row_data())
        return pd.DataFrame(rows, columns=rs.fields) if rows else pd.DataFrame(columns=rs.fields)

    @staticmethod
    def _fmt(day: str) -> str:
        return f"{day[:4]}-{day[4:6]}-{day[6:]}" if len(day) == 8 and day.isdigit() else day

    def get_stock_list(self, with_industry: bool = True) -> pd.DataFrame:
        # query_all_stock 需要传一个交易日；从今天往回找直到拿到非空结果（跳过周末/节假日）。
        df = pd.DataFrame()
        probe = date.today()
        for _ in range(10):
            df = self._rs_to_df(self.bs.query_all_stock(day=probe.isoformat()))
            if not df.empty:
                break
            probe -= timedelta(days=1)
        if df.empty:
            return pd.DataFrame(columns=STOCK_COLUMNS)

        df = df[df["code"].str.match(r"(sh\.6|sz\.[03]|bj\.)", na=False)].copy()
        df["code6"] = df["code"].str.extract(r"\.(\d{6})", expand=False)
        df = df.dropna(subset=["code6"])
        name_col = "code_name" if "code_name" in df else "code"
        out = pd.DataFrame(
            {
                "code": df["code6"],
                "name": df[name_col].astype(str),
                "market": df["code6"].map(lambda c: "SH" if c.startswith(("6", "9")) else "BJ" if c.startswith(("4", "8")) else "SZ"),
                "industry_l1": None,
                "industry_l2": None,
                "list_date": None,
                "is_active": True,
            }
        )
        out["is_st"] = out["name"].str.contains("ST", case=False, na=False)
        # baostock 行业分类只需一次调用，开销很小，始终获取（行业轮动/分类依赖它）。
        industry = self._rs_to_df(self.bs.query_stock_industry())
        if not industry.empty and "industry" in industry:
            industry["code6"] = industry["code"].str.extract(r"\.(\d{6})", expand=False)
            mapping = dict(zip(industry["code6"], industry["industry"]))
            out["industry_l1"] = out["code"].map(mapping)
        return out[STOCK_COLUMNS].dropna(subset=["code"])

    def get_daily_quotes(self, code: str, start_date: str, end_date: str) -> pd.DataFrame:
        rs = self.bs.query_history_k_data_plus(
            self._to_bs_code(code),
            "date,open,high,low,close,volume,amount,turn,pctChg",
            start_date=self._fmt(start_date),
            end_date=self._fmt(end_date),
            frequency="d",
            adjustflag="2",
        )
        df = self._rs_to_df(rs)
        if df.empty:
            return pd.DataFrame(columns=QUOTE_COLUMNS)
        out = pd.DataFrame(
            {
                "code": self._normalize_code(code),
                "trade_date": pd.to_datetime(df["date"], errors="coerce").dt.date,
                "open": pd.to_numeric(df["open"], errors="coerce"),
                "high": pd.to_numeric(df["high"], errors="coerce"),
                "low": pd.to_numeric(df["low"], errors="coerce"),
                "close": pd.to_numeric(df["close"], errors="coerce"),
                "volume": pd.to_numeric(df["volume"], errors="coerce"),
                "amount": pd.to_numeric(df["amount"], errors="coerce"),
                "turnover": pd.to_numeric(df["turn"], errors="coerce"),
                "pct_change": pd.to_numeric(df["pctChg"], errors="coerce"),
            }
        )
        return out.dropna(subset=["trade_date"]).sort_values("trade_date")

    def get_financial_data(self, code: str) -> pd.DataFrame:
        """估值历史（PE/PB/PS）取自日线 k 数据（估值字段仅日线提供），按月降采样；
        基本面（ROE/同比增速/毛利率/资产负债率）取自季度盈利/成长/偿债接口，
        盖到最新一行(供 ValueEngine 取最新值)。"""
        end = date.today()
        start = end.replace(year=end.year - self.valuation_lookback_years)
        rs = self.bs.query_history_k_data_plus(
            self._to_bs_code(code),
            "date,peTTM,pbMRQ,psTTM",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            frequency="d",
            adjustflag="3",
        )
        df = self._rs_to_df(rs)
        if df.empty:
            return pd.DataFrame(columns=FINANCIAL_COLUMNS)
        df["dt"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["dt"])
        # 按月降采样，取每月最后一个交易日的估值，控制行数。
        df = df.groupby(df["dt"].dt.to_period("M"), as_index=False).tail(1)
        out = pd.DataFrame(
            {
                "code": self._normalize_code(code),
                "report_date": df["dt"].dt.date,
                "pe_ttm": pd.to_numeric(df["peTTM"], errors="coerce"),
                "pb": pd.to_numeric(df["pbMRQ"], errors="coerce"),
                "ps_ttm": pd.to_numeric(df["psTTM"], errors="coerce"),
            }
        )
        out = out.dropna(subset=["report_date"]).reset_index(drop=True)
        for column in FINANCIAL_COLUMNS:
            if column not in out:
                out[column] = pd.NA
        if self.fetch_fundamentals and not out.empty:
            fundamentals = self._latest_fundamentals(code)
            if fundamentals:
                latest_idx = out["report_date"].idxmax()
                for key, value in fundamentals.items():
                    out.loc[latest_idx, key] = value
        return out[FINANCIAL_COLUMNS]

    def _latest_fundamentals(self, code: str) -> dict[str, float]:
        """最新一期季度基本面：ROE、净利同比、营收同比、毛利率、资产负债率。"""
        bs_code = self._to_bs_code(code)
        today = date.today()
        year, quarter = today.year, (today.month - 1) // 3 + 1
        profit = pd.DataFrame()
        for _ in range(5):
            quarter -= 1
            if quarter == 0:
                quarter, year = 4, year - 1
            profit = self._rs_to_df(self.bs.query_profit_data(code=bs_code, year=year, quarter=quarter))
            if not profit.empty and self._num(profit, "roeAvg") is not None:
                break
        else:
            return {}

        growth = self._rs_to_df(self.bs.query_growth_data(code=bs_code, year=year, quarter=quarter))
        balance = self._rs_to_df(self.bs.query_balance_data(code=bs_code, year=year, quarter=quarter))
        prev_year_q = self._rs_to_df(self.bs.query_profit_data(code=bs_code, year=year - 1, quarter=quarter))

        result: dict[str, float] = {}
        # baostock 比率字段为小数，统一转百分比。
        roe = self._num(profit, "roeAvg")
        if roe is not None:
            result["roe"] = round(roe * 100, 4)
        gross = self._num(profit, "gpMargin")
        if gross is not None:
            result["gross_margin"] = round(gross * 100, 4)
        profit_yoy = self._num(growth, "YOYNI")
        if profit_yoy is not None:
            result["profit_yoy"] = round(profit_yoy * 100, 4)
        debt = self._num(balance, "liabilityToAsset")
        if debt is not None:
            result["debt_ratio"] = round(debt * 100, 4)
        revenue = self._num(profit, "MBRevenue")
        prev_revenue = self._num(prev_year_q, "MBRevenue")
        if revenue is not None and prev_revenue not in (None, 0):
            result["revenue_yoy"] = round((revenue / prev_revenue - 1) * 100, 4)
        net_profit = self._num(profit, "netProfit")
        if net_profit is not None:
            result["net_profit"] = net_profit
        return result

    def get_quarterly_fundamentals(self, code: str, years: int | None = None) -> pd.DataFrame:
        """逐季度历史基本面(point-in-time):ROE/毛利率/净利同比/营收同比/资产负债率。

        每行 report_date = 该季报的 **pubDate(发布日)**，从该日起才"可知"，故可直接用于
        point-in-time 因子检验，无前视偏差。只含基本面列(不含 pe/pb/ps，避免覆盖估值行)。
        """
        years = years or self.valuation_lookback_years
        bs_code = self._to_bs_code(code)
        today = date.today()
        year, quarter = today.year, (today.month - 1) // 3 + 1
        rows: list[dict] = []
        for _ in range(years * 4 + 2):
            quarter -= 1
            if quarter == 0:
                quarter, year = 4, year - 1
            profit = self._rs_to_df(self.bs.query_profit_data(code=bs_code, year=year, quarter=quarter))
            if profit.empty or self._num(profit, "roeAvg") is None:
                continue
            growth = self._rs_to_df(self.bs.query_growth_data(code=bs_code, year=year, quarter=quarter))
            balance = self._rs_to_df(self.bs.query_balance_data(code=bs_code, year=year, quarter=quarter))
            pub = profit["pubDate"].iloc[0] if "pubDate" in profit and not profit.empty else None
            stat = profit["statDate"].iloc[0] if "statDate" in profit and not profit.empty else None
            report_date = pd.to_datetime(pub or stat, errors="coerce")
            if pd.isna(report_date):
                continue
            row: dict = {"code": self._normalize_code(code), "report_date": report_date.date(), "_q": quarter}
            roe = self._num(profit, "roeAvg")
            if roe is not None:
                row["roe"] = round(roe * 100, 4)
            gross = self._num(profit, "gpMargin")
            if gross is not None:
                row["gross_margin"] = round(gross * 100, 4)
            profit_yoy = self._num(growth, "YOYNI")
            if profit_yoy is not None:
                row["profit_yoy"] = round(profit_yoy * 100, 4)
            debt = self._num(balance, "liabilityToAsset")
            if debt is not None:
                row["debt_ratio"] = round(debt * 100, 4)
            revenue = self._num(profit, "MBRevenue")
            if revenue is not None:
                row["revenue"] = revenue
            net_profit = self._num(profit, "netProfit")
            if net_profit is not None:
                row["net_profit"] = net_profit
            rows.append(row)
        if not rows:
            return pd.DataFrame(columns=["code", "report_date", "roe", "gross_margin", "profit_yoy", "revenue_yoy", "debt_ratio", "revenue", "net_profit"])
        out = pd.DataFrame(rows).sort_values("report_date").reset_index(drop=True)
        # 营收同比:同一季度(_q)与去年同季 MBRevenue 比较。
        if "revenue" in out:
            out["revenue_yoy"] = pd.NA
            for q, grp in out.groupby("_q"):
                grp = grp.sort_values("report_date")
                prev = grp["revenue"].shift(1)
                yoy = (grp["revenue"] / prev - 1) * 100
                out.loc[grp.index, "revenue_yoy"] = yoy.round(4)
        return out.drop(columns=["_q"], errors="ignore")

    @staticmethod
    def _num(df: pd.DataFrame, column: str) -> float | None:
        if df.empty or column not in df:
            return None
        value = pd.to_numeric(df[column], errors="coerce").dropna()
        return float(value.iloc[0]) if not value.empty else None

    def get_index_constituents(self, index: str) -> list[str]:
        """获取指数成分股代码（6位）。index: hs300 / zz500 / sz50。"""
        query = {
            "hs300": "query_hs300_stocks",
            "zz500": "query_zz500_stocks",
            "sz50": "query_sz50_stocks",
        }.get(index.lower())
        if query is None:
            return []
        df = self._rs_to_df(getattr(self.bs, query)())
        if df.empty or "code" not in df:
            return []
        return df["code"].str.extract(r"\.(\d{6})", expand=False).dropna().tolist()

    def get_capital_flow(self, code: str, recent_days: int = 60) -> pd.DataFrame:
        return pd.DataFrame(columns=["code", "trade_date", "main_net_inflow", "north_net_flow", "margin_balance", "holder_count"])

    def get_industry_index(self, recent_days: int = 120) -> pd.DataFrame:
        """中证一级行业指数(市值加权、官方)，作为宏观行业强弱来源。"""
        from src.industry.sector_map import CSI_SECTORS

        end = date.today()
        start = end - timedelta(days=int(recent_days * 1.6) + 10)
        frames: list[pd.DataFrame] = []
        for code, name in CSI_SECTORS.items():
            rs = self.bs.query_history_k_data_plus(
                f"sh.{code}", "date,close,volume,pctChg",
                start_date=start.isoformat(), end_date=end.isoformat(), frequency="d",
            )
            df = self._rs_to_df(rs)
            if df.empty:
                continue
            df = df.tail(recent_days)
            frames.append(
                pd.DataFrame(
                    {
                        "industry_code": code,
                        "industry_name": name,
                        "trade_date": pd.to_datetime(df["date"], errors="coerce").dt.date,
                        "close": pd.to_numeric(df["close"], errors="coerce"),
                        "pct_change": pd.to_numeric(df["pctChg"], errors="coerce"),
                        "volume": pd.to_numeric(df["volume"], errors="coerce"),
                    }
                )
            )
        if not frames:
            return pd.DataFrame(columns=["industry_code", "industry_name", "trade_date", "close", "pct_change", "volume"])
        return pd.concat(frames, ignore_index=True).dropna(subset=["trade_date"])

    def get_market_overview(self) -> dict:
        """用沪深300指数日线粗略给出大盘状态输入。"""
        end = date.today()
        start = end - timedelta(days=140)
        rs = self.bs.query_history_k_data_plus(
            "sh.000300", "date,close", start_date=start.isoformat(), end_date=end.isoformat(), frequency="d"
        )
        df = self._rs_to_df(rs)
        hs300 = (
            [{"date": row["date"], "close": row["close"]} for _, row in df.iterrows()]
            if not df.empty
            else []
        )
        return {"as_of": end.isoformat(), "hs300": hs300, "advancers": 0, "decliners": 0, "northbound": []}
