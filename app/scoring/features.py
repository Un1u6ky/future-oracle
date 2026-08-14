from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, FearGreed, MarketSnapshot, NewsItem, NewsMention
from app.scoring.engine import score_components


def position_in_range(price: float, low: float | None, high: float | None) -> float | None:
    if low is None or high is None or high <= low:
        return None
    return (price - low) / (high - low)


def volatility_pct(price: float, low: float | None, high: float | None) -> float | None:
    if low is None or high is None or price <= 0:
        return None
    return 100.0 * (high - low) / price


def news_as_of(
    session: Session,
    asset_id: int,
    as_of: datetime,
    window_hours: int = 48,
) -> tuple[float, int, list[dict]]:
    """Recency-weighted news sentiment for one asset, using only items published <= as_of."""
    start = as_of - timedelta(hours=window_hours)
    rows = session.execute(
        select(NewsItem, NewsMention.weight)
        .join(NewsMention, NewsMention.news_id == NewsItem.id)
        .where(
            NewsMention.asset_id == asset_id,
            NewsItem.published_at <= as_of,
            NewsItem.published_at >= start,
        )
        .order_by(NewsItem.published_at.desc())
    ).all()

    half_life = 18.0
    weighted_sum = 0.0
    weight_sum = 0.0
    used: list[dict] = []
    for item, mention_weight in rows:
        age_h = max((as_of - item.published_at).total_seconds() / 3600.0, 0.0)
        decay = 0.5 ** (age_h / half_life)
        weight = mention_weight * decay
        weighted_sum += weight * item.sentiment
        weight_sum += weight
        used.append(
            {
                "title": item.title,
                "url": item.url,
                "published_at": item.published_at.isoformat(),
                "sentiment": item.sentiment,
                "weight": round(weight, 4),
                "source_id": item.source_id,
            }
        )
    sentiment = weighted_sum / weight_sum if weight_sum else 0.0
    return sentiment, len(used), used


def fear_greed_as_of(session: Session, as_of: datetime) -> FearGreed | None:
    return session.scalars(
        select(FearGreed)
        .where(FearGreed.captured_at <= as_of)
        .order_by(FearGreed.captured_at.desc())
        .limit(1)
    ).first()


def snapshot_as_of(session: Session, asset_id: int, as_of: datetime) -> MarketSnapshot | None:
    return session.scalars(
        select(MarketSnapshot)
        .where(MarketSnapshot.asset_id == asset_id, MarketSnapshot.captured_at <= as_of)
        .order_by(MarketSnapshot.captured_at.desc())
        .limit(1)
    ).first()


def compute_breakdown(session: Session, asset: Asset, snapshot: MarketSnapshot, as_of: datetime) -> dict:
    news_sentiment, news_count, news_used = news_as_of(session, asset.id, as_of)
    fng = fear_greed_as_of(session, as_of)
    pos = position_in_range(snapshot.price_usd, snapshot.low_24h, snapshot.high_24h)
    vol = volatility_pct(snapshot.price_usd, snapshot.low_24h, snapshot.high_24h)
    breakdown = score_components(
        change_24h_pct=snapshot.change_24h_pct,
        change_7d_pct=snapshot.change_7d_pct,
        volume_ratio=snapshot.volume_ratio,
        position_in_range=pos,
        news_sentiment=news_sentiment,
        news_count=news_count,
        fear_greed_value=fng.value if fng else None,
        volatility_pct=vol,
    )
    breakdown["used_data"] = {
        "asset": {"symbol": asset.symbol, "name": asset.name},
        "snapshot": {
            "captured_at": snapshot.captured_at.isoformat(),
            "price_usd": snapshot.price_usd,
            "change_24h_pct": snapshot.change_24h_pct,
            "change_7d_pct": snapshot.change_7d_pct,
            "volume_24h": snapshot.volume_24h,
            "market_cap": snapshot.market_cap,
            "high_24h": snapshot.high_24h,
            "low_24h": snapshot.low_24h,
            "volume_ratio": snapshot.volume_ratio,
            "turnover": snapshot.turnover,
        },
        "fear_greed": {
            "value": fng.value if fng else None,
            "classification": fng.classification if fng else None,
            "captured_at": fng.captured_at.isoformat() if fng else None,
        },
        "news": news_used,
        "keywords": json.loads(asset.keywords_json),
    }
    return breakdown
