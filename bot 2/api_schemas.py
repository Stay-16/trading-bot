from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GenericDictModel(BaseModel):
    model_config = {"extra": "allow"}


class HealthResponse(BaseModel):
    title: str
    connection: str
    balance: float | None = None
    open_trades: int = 0
    history_size: int = 0
    performance: dict[str, Any] = Field(default_factory=dict)
    webapp_url: str | None = None


class SymbolHealthResponse(BaseModel):
    score: int = 0
    update_speed: int = 0
    data_stability: int = 0
    grade: str = "weak"


class LiveMarketEntryResponse(BaseModel):
    id: str
    pair_key: str
    display_name: str
    market_type: str
    payout: float | None = None
    quotex_symbol: str
    symbol: str
    health: SymbolHealthResponse


class MarketsResponse(BaseModel):
    category: str
    counts: dict[str, int]
    items: list[LiveMarketEntryResponse]


class TopSetupItemResponse(BaseModel):
    asset: LiveMarketEntryResponse
    direction: str
    confidence: int
    score: float
    trend_condition: str = "normal"
    market_condition: str = "normal"
    health: SymbolHealthResponse
    multi_timeframe: dict[str, Any] = Field(default_factory=dict)
    payout_filter: dict[str, Any] = Field(default_factory=dict)
    price_action_score: int = 0
    breakout_structure: dict[str, Any] = Field(default_factory=dict)


class TopSetupsResponse(BaseModel):
    timeframe: str
    category: str
    items: list[TopSetupItemResponse]


class LiveSnapshotResponse(BaseModel):
    asset_id: str
    timeframe: str
    price: float | None = None
    sentiment: float | None = None
    payout: float | None = None
    candles: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: float | None = None


class ExecuteTradeResponse(BaseModel):
    success: bool
    trade_id: str
    pair: str
    amount: float
    direction: str
    duration: int


class AnalyzeResponse(BaseModel):
    asset: dict[str, Any]
    timeframe: str
    direction: str
    confidence: int
    raw_confidence: int = 0
    risk_level: str = "medium"
    decision_score: int = 0
    analysis_method: str = "unknown"
    models_used: list[str] = Field(default_factory=list)
    model_weights: dict[str, float] = Field(default_factory=dict)
    traditional: dict[str, Any] = Field(default_factory=dict)
    lstm_signal: dict[str, Any] = Field(default_factory=dict)
    market_context: dict[str, Any] = Field(default_factory=dict)
    technical_summary: str = ""
    market_insights: dict[str, Any] = Field(default_factory=dict)
    performance: dict[str, Any] = Field(default_factory=dict)
    decision_reasons: list[str] = Field(default_factory=list)
    candle_pattern: str = "N/A"
    degraded: bool = False
    degraded_reason: str = ""
    price_series: list[dict[str, Any]] = Field(default_factory=list)
    live_price: float | None = None
    live_sentiment: float | None = None
    live_payout: float | None = None
    symbol_health: dict[str, Any] = Field(default_factory=dict)
    multi_timeframe: dict[str, Any] = Field(default_factory=dict)
    market_regime: dict[str, Any] = Field(default_factory=dict)
    payout_filter: dict[str, Any] = Field(default_factory=dict)
    candlestick_pattern_detail: dict[str, Any] = Field(default_factory=dict)
    support_resistance: dict[str, Any] = Field(default_factory=dict)
    breakout_structure: dict[str, Any] = Field(default_factory=dict)
    price_action_score: int = 0
    quad_analysis: dict[str, Any] = Field(default_factory=dict)
    ai_voting: dict[str, Any] = Field(default_factory=dict)
    live_analysis_steps: list[dict[str, Any]] = Field(default_factory=list)
    best_entry: dict[str, Any] = Field(default_factory=dict)
