"""API 数据模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


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


class ScanRequest(BaseModel):
    top_n: int = 50
    filters: dict = Field(default_factory=dict)


class ScanTaskResponse(BaseModel):
    task_id: str
    status: str


class BacktestRequest(BaseModel):
    start_date: str
    end_date: str
    initial_capital: float = 100_000
    rebalance_freq: str = "monthly"
    top_n: int = 10
    position_rule: str = "equal"

