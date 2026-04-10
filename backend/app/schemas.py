from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class DirectionTag(str, Enum):
    LONG = "Long"
    SHORT = "Short"


class StrategyTag(str, Enum):
    BREAKOUT = "Breakout"
    PULLBACK = "Pullback"
    PRICE_ACTION = "Price action"
    REVERSAL = "Reversal"


class MarketContextTag(str, Enum):
    TRENDING_DAY = "trending day"
    RANGE_DAY = "Range day"
    HIGH_VOLATILITY = "High volatility"
    EXPIRY_DAY = "Expiry day"
    NEWS_DRIVEN = "News driven"


class ExecutionTag(str, Enum):
    GOOD_RR = "good R:R"
    POOR_RR = "Poor R:R"
    OVERSIZED = "Oversized"
    PERFECT_ENTRY = "Perfect entry"
    EARLY_ENTRY = "Early entry"
    LATE_ENTRY = "Late entry"
    PREMATURE_EXIT = "Premature exit"
    PERFECT_EXIT = "Perfect exit"
    LATE_EXIT = "Late exit"


class ResultQualityTag(str, Enum):
    A_PLUS = "a+"
    RULE_BREAK = "Rule break"
    SLIPPAGE = "Slippage"
    FOLLOWED_PLAN = "Followed plan"
    NO_PLAN = "No plan"
    OVERTRADED = "Overtraded"
    RANDOM_TRADE = "Random trade"
    IMPULSIVE = "Impulsive"


class OutcomeTag(str, Enum):
    TARGET_HIT = "Target hit"
    STOP_HIT = "Stop hit"
    PARTIAL_EXIT = "Partial exit"
    TIME_EXIT = "Time exit"
    MANUAL_CLOSE = "Manual close"


class MockEntryRequest(BaseModel):
    event_id: str | None = None
    timestamp: datetime | None = None
    symbol: str = Field(min_length=1, max_length=40)
    product: str = Field(default="MIS", min_length=1, max_length=20)
    quantity: int = Field(gt=0)
    average_price: float = Field(gt=0)


class MockExitRequest(BaseModel):
    event_id: str | None = None
    timestamp: datetime | None = None
    symbol: str = Field(min_length=1, max_length=40)
    product: str = Field(default="MIS", min_length=1, max_length=20)
    average_price: float = Field(gt=0)
    pnl: float = 0.0


class MockBatchRequest(BaseModel):
    events: list[dict[str, Any]]


class CustomTagCreate(BaseModel):
    name: str = Field(min_length=3, max_length=50)
    category: str | None = Field(default=None, max_length=30)


class CustomTagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=3, max_length=50)
    category: str | None = Field(default=None, max_length=30)
