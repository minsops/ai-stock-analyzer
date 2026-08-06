"""API 数据模型。"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class EngineScoreDetail(BaseModel):
    score: float
    confidence: float
    signals: list[str]
    details: dict
    available: bool = True


class ConflictInfo(BaseModel):
    engine_a: str
    engine_b: str
    score_a: float
    score_b: float
    gap: float
    recommendation: str


class ScoreReport(BaseModel):
    code: str
    name: str
    composite_score: float
    available_engines: int | None = None
    total_engines: int | None = None
    regime: str
    weights: dict[str, float]
    engine_scores: dict[str, EngineScoreDetail]
    conflicts: list[ConflictInfo]
    filter_passed: bool
    quarantined: bool
    valuation: dict
    scored_at: str


class RankingItem(BaseModel):
    rank: int
    code: str
    name: str | None = None
    industry: str | None = None
    composite_score: float
    value_score: float | None = None
    trend_score: float | None = None
    capital_score: float | None = None
    industry_score: float | None = None
    event_score: float | None = None
    pe_percentile: float | None = None
    signals: list[str] = Field(default_factory=list)


class RankingResponse(BaseModel):
    date: str
    regime: str
    total_scanned: int
    total_passed_filter: int
    items: list[RankingItem]


class RegimeResponse(BaseModel):
    date: str
    regime: str
    confidence: float
    details: dict


class FilterOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exclude_st: StrictBool | None = None
    exclude_new_stock_days: int | None = Field(default=None, ge=0, strict=True)
    min_daily_amount: float | None = Field(default=None, ge=0, strict=True)
    exclude_suspended: StrictBool | None = None
    max_pe_ttm: float | None = Field(default=None, strict=True)
    min_pe_ttm: float | None = Field(default=None, strict=True)
    max_debt_ratio: float | None = Field(default=None, ge=0, le=100, strict=True)

    @model_validator(mode="after")
    def validate_pe_range(self) -> "FilterOverrides":
        if self.min_pe_ttm is not None and self.max_pe_ttm is not None and self.min_pe_ttm > self.max_pe_ttm:
            raise ValueError("min_pe_ttm 不能大于 max_pe_ttm")
        return self


class ScanRequest(BaseModel):
    top_n: int = Field(default=50, ge=1)
    filters: FilterOverrides = Field(default_factory=FilterOverrides)


class ScanTaskResponse(BaseModel):
    task_id: str
    status: str


class BacktestRequest(BaseModel):
    start_date: date
    end_date: date
    initial_capital: float = Field(default=100_000, gt=0)
    rebalance_freq: Literal["weekly", "monthly"] = "monthly"
    top_n: int = Field(default=10, ge=1)
    position_rule: str = "equal"
    # selection: "score"（系统综合评分）或 "momentum"（动量基准）
    selection: Literal["score", "momentum"] = "score"

    @model_validator(mode="after")
    def validate_date_range(self) -> "BacktestRequest":
        if self.start_date > self.end_date:
            raise ValueError("start_date 不能晚于 end_date")
        return self
