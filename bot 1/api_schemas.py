from pydantic import BaseModel, Field
from typing import Any, Optional


class HealthResponse(BaseModel):
    status: str
    running: bool
    mode: str
    symbol: str
    price: float = 0.0
    balance: float = 0.0
    candles: int = 0
    uptime: str = ""


class MarketsResponse(BaseModel):
    symbol: str
    price: float = 0.0
    payout: float = 0.0
    sentiment: Optional[float] = None
    candles: int = 0


class AnalyzeResponse(BaseModel):
    symbol: str
    direction: str
    confidence: int = 0
    score: int = 0
    reasons: list[str] = Field(default_factory=list)
    trade_size: float = 0.0
    ai_analysis: str = ""
    timestamp: float = 0.0


class LiveSnapshotResponse(BaseModel):
    asset_id: str
    timeframe: str = "1m"
    price: Optional[float] = None
    sentiment: Optional[float] = None
    payout: Optional[float] = None
    candles: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: Optional[float] = None


class ExecuteTradeResponse(BaseModel):
    success: bool
    trade_id: str = ""
    pair: str = ""
    amount: float = 0.0
    direction: str = ""
    duration: int = 60


class TopSetupItemResponse(BaseModel):
    symbol: str
    direction: str
    confidence: int
    score: int
    payout: float = 0.0


class TopSetupsResponse(BaseModel):
    timeframe: str = "1m"
    category: str = "all"
    items: list[TopSetupItemResponse] = Field(default_factory=list)
