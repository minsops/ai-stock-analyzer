"""趋势评分引擎。"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.engines.base_engine import BaseEngine, ScoreResult


class TrendEngine(BaseEngine):
    """趋势评分引擎。"""

    WEIGHTS = {
        "ma_alignment": 0.25,
        "macd": 0.20,
        "rsi": 0.15,
        "bollinger": 0.15,
        "volume_trend": 0.15,
        "atr": 0.10,
    }

    @property
    def name(self) -> str:
        return "trend"

    def score(self, code: str, data: dict[str, Any]) -> ScoreResult:
        quotes = data.get("quotes")
        if not isinstance(quotes, pd.DataFrame) or quotes.empty or "close" not in quotes:
            return ScoreResult(0.0, 0.0, {}, ["趋势数据不足，暂不参与综合评分"], False)

        q = quotes.sort_values("trade_date").copy()
        for column in ("open", "high", "low", "close", "volume"):
            q[column] = pd.to_numeric(q.get(column), errors="coerce")
        close = q["close"]
        scores: dict[str, float] = {}
        details: dict[str, Any] = {}
        signals: list[str] = []

        ma_windows = [5, 10, 20, 60, 120]
        mas = {window: close.rolling(window).mean().iloc[-1] for window in ma_windows if len(close) >= window}
        if len(mas) >= 2:
            checks = [mas[a] > mas[b] for a, b in zip(ma_windows, ma_windows[1:], strict=False) if a in mas and b in mas]
            scores["ma_alignment"] = len([item for item in checks if item]) / len(checks) * 100 if checks else np.nan
            details["ma_alignment_count"] = len([item for item in checks if item])
            signals.append(f"均线多头排列 {details['ma_alignment_count']}/{len(checks)}")
        else:
            scores["ma_alignment"] = np.nan

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        macd_bar = (dif - dea) * 2
        if len(macd_bar.dropna()) >= 2:
            scores["macd"] = 100.0 if dif.iloc[-1] > dea.iloc[-1] and macd_bar.iloc[-1] > 0 and macd_bar.iloc[-1] > macd_bar.iloc[-2] else 0.0 if dif.iloc[-1] < dea.iloc[-1] else 50.0
            details["macd_bar"] = float(macd_bar.iloc[-1])
            signals.append("MACD 偏强" if scores["macd"] >= 80 else "MACD 偏弱" if scores["macd"] <= 20 else "MACD 中性")
        else:
            scores["macd"] = np.nan

        rsi = self._rsi(close, 14)
        if not pd.isna(rsi):
            scores["rsi"] = self._score_rsi(rsi)
            details["rsi14"] = rsi
            signals.append(f"RSI(14) {rsi:.1f}")
        else:
            scores["rsi"] = np.nan

        if len(close) >= 20:
            mid = close.rolling(20).mean().iloc[-1]
            std = close.rolling(20).std().iloc[-1]
            upper = mid + 2 * std
            lower = mid - 2 * std
            last = close.iloc[-1]
            scores["bollinger"] = 80.0 if mid <= last <= upper else 40.0 if lower <= last < mid else 60.0 if last > upper else 30.0
            details["bollinger"] = {"mid": float(mid), "upper": float(upper), "lower": float(lower)}
        else:
            scores["bollinger"] = np.nan

        if len(q) >= 20 and "volume" in q:
            vol5 = q["volume"].rolling(5).mean().iloc[-1]
            vol20 = q["volume"].rolling(20).mean().iloc[-1]
            price_up = close.iloc[-1] > close.iloc[-5]
            ratio = vol5 / vol20 if vol20 else np.nan
            scores["volume_trend"] = 100.0 if ratio > 1.5 and price_up else 20.0 if ratio < 0.8 and not price_up else 60.0
            details["volume_ratio_5_20"] = float(ratio)
        else:
            scores["volume_trend"] = np.nan

        atr_pct = self._atr_pct(q)
        if not pd.isna(atr_pct):
            scores["atr"] = 100.0 if 0.02 <= atr_pct <= 0.05 else 60.0 if 0.01 <= atr_pct <= 0.08 else 30.0
            details["atr_pct"] = atr_pct
        else:
            scores["atr"] = np.nan

        return self._weighted_result(scores, self.WEIGHTS, details, signals, total_items=len(self.WEIGHTS))

    def _rsi(self, close: pd.Series, window: int) -> float:
        if len(close) < window + 1:
            return np.nan
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(window).mean()
        loss = (-delta.clip(upper=0)).rolling(window).mean()
        rs = gain / loss.replace(0, np.nan)
        value = 100 - (100 / (1 + rs.iloc[-1]))
        return float(value) if not pd.isna(value) else 100.0

    def _score_rsi(self, rsi: float) -> float:
        if 40 <= rsi <= 60:
            return 80.0
        if 20 <= rsi < 40 or 60 < rsi <= 80:
            return 60.0
        if rsi < 20:
            return 30.0
        return 20.0

    def _atr_pct(self, q: pd.DataFrame) -> float:
        if len(q) < 15 or not {"high", "low", "close"}.issubset(q.columns):
            return np.nan
        previous_close = q["close"].shift(1)
        tr = pd.concat(
            [(q["high"] - q["low"]), (q["high"] - previous_close).abs(), (q["low"] - previous_close).abs()],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        close = q["close"].iloc[-1]
        return float(atr / close) if close else np.nan

