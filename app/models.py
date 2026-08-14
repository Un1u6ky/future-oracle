from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    url: Mapped[str] = mapped_column(String(512))
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    raw_records: Mapped[list["RawRecord"]] = relationship(back_populates="source")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    coingecko_id: Mapped[str] = mapped_column(String(64), unique=True)
    keywords_json: Mapped[str] = mapped_column(Text)


class RawRecord(Base):
    __tablename__ = "raw_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    ingest_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ingest_runs.id"), nullable=True, index=True
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    record_key: Mapped[str] = mapped_column(String(256), index=True)
    payload_json: Mapped[str] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="raw_records")


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (
        UniqueConstraint("asset_id", "captured_at", name="uq_market_asset_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    is_live: Mapped[bool] = mapped_column(Boolean, default=True)
    price_usd: Mapped[float] = mapped_column(Float)
    change_24h_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_7d_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    low_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    turnover: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_records.id"), nullable=True
    )

    asset: Mapped[Asset] = relationship()


class FearGreed(Base):
    __tablename__ = "fear_greed"
    __table_args__ = (UniqueConstraint("captured_at", name="uq_fng_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    value: Mapped[int] = mapped_column(Integer)
    classification: Mapped[str] = mapped_column(String(32))
    raw_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_records.id"), nullable=True
    )


class NewsItem(Base):
    __tablename__ = "news_items"
    __table_args__ = (UniqueConstraint("url", name="uq_news_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1024))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[float] = mapped_column(Float)
    is_market_wide: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_records.id"), nullable=True
    )

    source: Mapped[Source] = relationship()
    mentions: Mapped[list["NewsMention"]] = relationship(back_populates="news")


class NewsMention(Base):
    __tablename__ = "news_mentions"
    __table_args__ = (
        UniqueConstraint("news_id", "asset_id", name="uq_news_asset"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_id: Mapped[int] = mapped_column(ForeignKey("news_items.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    news: Mapped[NewsItem] = relationship(back_populates="mentions")
    asset: Mapped[Asset] = relationship()


class Indicator(Base):
    __tablename__ = "indicators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, index=True)
    momentum: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    range_rev: Mapped[float] = mapped_column(Float)
    news: Mapped[float] = mapped_column(Float)
    fear_greed: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    news_count: Mapped[int] = mapped_column(Integer)
    news_coverage: Mapped[float] = mapped_column(Float)
    agreement: Mapped[float] = mapped_column(Float)
    volatility_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    breakdown_json: Mapped[str] = mapped_column(Text)

    asset: Mapped[Asset] = relationship()


class Forecast(Base):
    __tablename__ = "forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id"), index=True)
    indicator_id: Mapped[int] = mapped_column(ForeignKey("indicators.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime, index=True)
    horizon_hours: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # live | backtest
    direction: Mapped[str] = mapped_column(String(16))
    probability_up: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float)
    risk_level: Mapped[str] = mapped_column(String(16))
    risk_notes_json: Mapped[str] = mapped_column(Text)
    arguments_json: Mapped[str] = mapped_column(Text)
    used_data_json: Mapped[str] = mapped_column(Text)
    price_at_forecast: Mapped[float] = mapped_column(Float)
    resolve_after: Mapped[datetime] = mapped_column(DateTime, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    was_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    brier: Mapped[float | None] = mapped_column(Float, nullable=True)
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    asset: Mapped[Asset] = relationship()
    indicator: Mapped[Indicator] = relationship()


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    stats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ForecastUpdate(Base):
    __tablename__ = "forecast_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    forecast_id: Mapped[int] = mapped_column(ForeignKey("forecasts.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    field: Mapped[str] = mapped_column(String(64))
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
