from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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


class TagCreate(BaseModel):
    category_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=60)
    tag_score: int = Field(ge=0, le=10)


class TagResponse(BaseModel):
    id: int
    name: str
    category_id: int
    category_name: str | None = None
    tag_score: int


class TagCategoryResponse(BaseModel):
    id: int
    name: str
    category_weight: int
    tags: list[TagResponse] = Field(default_factory=list)


class TradeNodeTagUpdate(BaseModel):
    node_id: int = Field(gt=0)
    fixed_tags: dict[str, str] | None = None
    custom_tag_ids: list[int] | None = None
    note: str | None = None


class TradeUpdateRequest(BaseModel):
    node_updates: list[TradeNodeTagUpdate] = Field(min_length=1, max_length=20)


class TradeResponse(BaseModel):
    id: int
    symbol: str
    product: str
    status: str
    pnl: float | None = None
    computed_quality_score: float = 0.0


class UserSignupRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    phonenumber: str = Field(min_length=3, max_length=50)
    email: str = Field(min_length=5, max_length=100)
    password: str = Field(min_length=6, max_length=128)


class UserLoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=100)
    password: str = Field(min_length=6, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserPublic(BaseModel):
    id: int
    first_name: str
    last_name: str
    phonenumber: str
    email: str


class UserResponse(BaseModel):
    data: UserPublic

class NewPasswordRequest(BaseModel):
    token: str = Field(min_length=5, max_length=100)
    new_password: str = Field(min_length=6, max_length=128)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=5, max_length=100)

