from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class TradeStatus(str, Enum):
    PENDING_ENTRY = "pending_entry"
    ACTIVE = "active"
    PENDING_EXIT = "pending_exit"
    COMPLETE = "complete"


class NodeType(str, Enum):
    ENTRY = "entry"
    MID = "mid"
    EXIT = "exit"


class TagCategory(Base):
    __tablename__ = "tag_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    normalized_name: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    category_weight: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    tags: Mapped[list[Tag]] = relationship("Tag", back_populates="category", cascade="all, delete-orphan")


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("category_id", "normalized_name", name="uq_tag_category_normalized_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("tag_categories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60), index=True)
    normalized_name: Mapped[str] = mapped_column(String(60), index=True)
    tag_score: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    category: Mapped[TagCategory] = relationship("TagCategory", back_populates="tags")


class PositionState(Base):
    __tablename__ = "position_states"
    __table_args__ = (UniqueConstraint("symbol", "product", name="uq_position_symbol_product"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    product: Mapped[str] = mapped_column(String(20), index=True)
    net_quantity: Mapped[int] = mapped_column(Integer, default=0)
    average_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("broker_accounts.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    product: Mapped[str] = mapped_column(String(20), index=True)
    instrument_token: Mapped[int] = mapped_column(Integer, index=True)
    direction: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[int] = mapped_column(Integer)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), index=True)
    source_open_event: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_close_event: Mapped[str | None] = mapped_column(String(80), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    nodes: Mapped[list[TradeNode]] = relationship("TradeNode", back_populates="trade", cascade="all, delete-orphan")
    embeddings: Mapped[list[NodeEmbedding]] = relationship("NodeEmbedding", back_populates="trade", cascade="all, delete-orphan")
    user: Mapped[User] = relationship("User")
    account: Mapped[BrokerAccount] = relationship("BrokerAccount")

class TradeNode(Base):
    __tablename__ = "trade_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), index=True)
    node_type: Mapped[str] = mapped_column(String(10), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fixed_tags: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    sliders: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    is_locked: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    trade: Mapped[Trade] = relationship("Trade", back_populates="nodes")
    custom_tags: Mapped[list[CustomTag]] = relationship(
        "CustomTag",
        secondary="node_custom_tags",
        back_populates="nodes",
    )
    attachments: Mapped[list[Attachment]] = relationship(
        "Attachment",
        back_populates="node",
        cascade="all, delete-orphan",
    )
    embedding: Mapped[NodeEmbedding | None] = relationship(
        "NodeEmbedding",
        back_populates="node",
        uselist=False,
        cascade="all, delete-orphan",
    )


class NodeEmbedding(Base):
    __tablename__ = "node_embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), index=True)
    trade_node_id: Mapped[int] = mapped_column(ForeignKey("trade_nodes.id", ondelete="CASCADE"), unique=True, index=True)
    node_type: Mapped[str] = mapped_column(String(10), index=True)
    embedding_model: Mapped[str] = mapped_column(String(120), default="deterministic-hash-v1")
    embedding_provider: Mapped[str] = mapped_column(String(80), default="deterministic")
    embedding_dimension: Mapped[int] = mapped_column(Integer)
    serialized_state: Mapped[str] = mapped_column(Text)
    vector: Mapped[list[float]] = mapped_column(JSON)
    pnl_at_storage: Mapped[float | None] = mapped_column(Float, nullable=True)
    vector_store_backend: Mapped[str] = mapped_column(String(30), default="database")
    vector_store_synced: Mapped[bool] = mapped_column(Boolean, default=True)
    vector_store_doc_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    vector_store_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    trade: Mapped[Trade] = relationship("Trade", back_populates="embeddings")
    node: Mapped[TradeNode] = relationship("TradeNode", back_populates="embedding")


class BehavioralProfile(Base):
    __tablename__ = "behavioral_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_key: Mapped[str] = mapped_column(String(80), unique=True, index=True, default="global")
    user_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    sweet_spot_centroid: Mapped[list[float]] = mapped_column(JSON, default=list)
    danger_zone_centroid: Mapped[list[float]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RetrospectiveReport(Base):
    __tablename__ = "retrospective_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_key: Mapped[str] = mapped_column(String(80), index=True, default="global")
    timeframe_days: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trade_count: Mapped[int] = mapped_column(Integer, default=0)
    synthesis_model: Mapped[str] = mapped_column(String(120), default="fallback-template")
    synthesis_source: Mapped[str] = mapped_column(String(60), default="fallback")
    report_markdown: Mapped[str] = mapped_column(Text)
    retrieval_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    feature_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    drift_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CustomTag(Base):
    __tablename__ = "custom_tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    normalized_name: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    nodes: Mapped[list[TradeNode]] = relationship(
        "TradeNode",
        secondary="node_custom_tags",
        back_populates="custom_tags",
    )


class NodeCustomTag(Base):
    __tablename__ = "node_custom_tags"
    __table_args__ = (UniqueConstraint("node_id", "tag_id", name="uq_node_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("trade_nodes.id", ondelete="CASCADE"), index=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("custom_tags.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("trade_nodes.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_key: Mapped[str] = mapped_column(String(400), unique=True)
    mime_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column(Integer)
    caption: Mapped[str | None] = mapped_column(String(255), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checksum_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    node: Mapped[TradeNode] = relationship("TradeNode", back_populates="attachments")


class MockEvent(Base):
    __tablename__ = "mock_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(20), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="processed")
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # phonenumber is nullable so OAuth users (who don't supply one) can register
    phonenumber: Mapped[str | None] = mapped_column(String(80), unique=True, index=True, nullable=True)
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # hashed_password is nullable for OAuth-only users
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    # OAuth fields — populated when the user signs in via a third-party provider
    auth_provider: Mapped[str] = mapped_column(String(40), default="local", index=True)
    provider_user_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship("User")


class BrokerAccount(Base):
    __tablename__ = "broker_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    broker_user_id: Mapped[str] = mapped_column(String(80), index=True)
    user_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    broker: Mapped[str] = mapped_column(String(40), default="zerodha", index=True)
    access_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    user: Mapped[User] = relationship("User")