from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Asset, FearGreed, Forecast, IngestRun, NewsItem, Source

DIRECTION_RU = {"up": "рост", "down": "снижение", "sideways": "боковик"}
RISK_RU = {"low": "низкий", "medium": "средний", "high": "высокий"}


def parse_json(value: str | None, default):
    if not value:
        return default
    return json.loads(value)


def fmt_price(value: float | None) -> str:
    if value is None:
        return "—"
    if value >= 1000:
        return f"{value:,.0f}".replace(",", " ")
    if value >= 1:
        return f"{value:,.2f}".replace(",", " ")
    return f"{value:.6f}"


def fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:+.{digits}f}%"


def fmt_when(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d.%m.%Y %H:%M")


def accuracy_stats(session: Session) -> dict:
    rows = session.scalars(select(Forecast).where(Forecast.resolved_at.is_not(None))).all()
    total = len(rows)
    correct = sum(1 for row in rows if row.was_correct)
    brier = (sum(row.brier for row in rows if row.brier is not None) / total) if total else None
    baseline_down = (sum(1 for row in rows if row.actual_direction == "down") / total * 100.0) if total else None
    return {
        "resolved": total,
        "correct": correct,
        "accuracy": (correct / total * 100.0) if total else None,
        "brier": float(brier) if brier is not None else None,
        "baseline_down": baseline_down,
    }


def latest_live_forecasts(session: Session) -> list[tuple[Asset, Forecast]]:
    assets = session.scalars(select(Asset).order_by(Asset.id)).all()
    result: list[tuple[Asset, Forecast]] = []
    for asset in assets:
        forecast = session.scalars(
            select(Forecast)
            .where(Forecast.asset_id == asset.id, Forecast.kind == "live")
            .order_by(Forecast.created_at.desc())
            .limit(1)
        ).first()
        if forecast:
            result.append((asset, forecast))
    return result


def latest_fng(session: Session) -> FearGreed | None:
    return session.scalars(select(FearGreed).order_by(FearGreed.captured_at.desc()).limit(1)).first()


def last_run(session: Session) -> IngestRun | None:
    return session.scalars(select(IngestRun).order_by(IngestRun.started_at.desc()).limit(1)).first()


def serialize_forecast(forecast: Forecast, asset: Asset) -> dict:
    return {
        "id": forecast.id,
        "symbol": asset.symbol,
        "name": asset.name,
        "kind": forecast.kind,
        "as_of": forecast.as_of.isoformat(),
        "created_at": forecast.created_at.isoformat(),
        "direction": forecast.direction,
        "direction_ru": DIRECTION_RU[forecast.direction],
        "probability_up": forecast.probability_up,
        "confidence": forecast.confidence,
        "risk_level": forecast.risk_level,
        "risk_level_ru": RISK_RU[forecast.risk_level],
        "risk_notes": parse_json(forecast.risk_notes_json, []),
        "arguments": parse_json(forecast.arguments_json, []),
        "used_data": parse_json(forecast.used_data_json, {}),
        "price_at_forecast": forecast.price_at_forecast,
        "score": forecast.indicator.score,
        "components": {
            "momentum": forecast.indicator.momentum,
            "volume": forecast.indicator.volume,
            "range": forecast.indicator.range_rev,
            "news": forecast.indicator.news,
            "fear_greed": forecast.indicator.fear_greed,
        },
        "breakdown": parse_json(forecast.indicator.breakdown_json, {}),
        "resolved": forecast.resolved_at is not None,
        "actual_direction": forecast.actual_direction,
        "actual_return_pct": forecast.actual_return_pct,
        "was_correct": forecast.was_correct,
        "brier": forecast.brier,
        "resolution_notes": forecast.resolution_notes,
    }


def source_rows(session: Session) -> list[Source]:
    return session.scalars(select(Source).order_by(Source.id)).all()


def recent_news(session: Session, limit: int = 25) -> list[NewsItem]:
    return session.scalars(select(NewsItem).order_by(NewsItem.published_at.desc()).limit(limit)).all()
