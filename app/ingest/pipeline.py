from __future__ import annotations

import json
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import ASSETS, BACKTEST_DAYS, FORECAST_HORIZON_HOURS
from app.ingest.fetchers import (
    dump,
    fetch_charts,
    fetch_cryptocompare_news,
    fetch_fear_greed,
    fetch_markets,
    fetch_rss,
    utcnow,
)
from app.models import (
    Asset,
    FearGreed,
    Forecast,
    ForecastUpdate,
    Indicator,
    IngestRun,
    MarketSnapshot,
    NewsItem,
    NewsMention,
    RawRecord,
    Source,
)
from app.scoring.engine import actual_direction, brier_score, build_forecast
from app.scoring.features import compute_breakdown
from app.scoring.lexicon import headline_sentiment, is_market_wide, match_assets


def recompute_forecasts(session: Session) -> dict:
    """Rebuild indicators/forecasts from rows already in SQLite. No network."""
    session.execute(delete(ForecastUpdate))
    session.execute(delete(Forecast))
    session.execute(delete(Indicator))
    session.flush()
    assets = {a.coingecko_id: a for a in session.scalars(select(Asset)).all()}
    _recompute_cross_sectional_volume(session)
    live = _generate_live_forecasts(session, assets)
    backtest = _generate_backtests(session, assets, [])
    resolved = _resolve_due_forecasts(session)
    session.commit()
    return {"live": live, "backtest": backtest, "resolved": resolved}


def run_ingest(session: Session) -> IngestRun:
    run = IngestRun(started_at=utcnow(), status="running")
    session.add(run)
    session.flush()
    stats: dict = {"markets": 0, "charts": 0, "fear_greed": 0, "news": 0, "forecasts": 0}
    try:
        assets = {a.coingecko_id: a for a in session.scalars(select(Asset)).all()}
        sources = {s.code: s for s in session.scalars(select(Source)).all()}

        markets = _ingest_markets(session, run, assets, sources, stats)
        _ingest_charts(session, run, assets, sources, stats)
        _ingest_sparklines(session, markets, assets)
        _ingest_fear_greed(session, run, sources, stats)
        _ingest_news(session, run, assets, sources, stats)
        _recompute_cross_sectional_volume(session)

        live_count = _generate_live_forecasts(session, assets)
        backtest_count = _generate_backtests(session, assets, markets)
        resolved = _resolve_due_forecasts(session)
        stats["forecasts"] = live_count + backtest_count
        stats["resolved"] = resolved
        stats["live"] = live_count
        stats["backtest"] = backtest_count

        run.finished_at = utcnow()
        run.status = "ok"
        run.stats_json = json.dumps(stats)
        session.commit()
        return run
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        run = IngestRun(
            started_at=run.started_at,
            finished_at=utcnow(),
            status="error",
            error=str(exc),
            stats_json=json.dumps(stats),
        )
        session.add(run)
        session.commit()
        raise


def _source(sources: dict[str, Source], code: str) -> Source:
    if code not in sources:
        raise RuntimeError(f"Unknown source {code}")
    return sources[code]


def _store_raw(
    session: Session,
    source: Source,
    run: IngestRun,
    record_key: str,
    payload,
    fetched_at: datetime,
) -> RawRecord:
    raw = RawRecord(
        source_id=source.id,
        ingest_run_id=run.id,
        fetched_at=fetched_at,
        record_key=record_key[:256],
        payload_json=dump(payload),
    )
    session.add(raw)
    source.last_fetched_at = fetched_at
    source.last_status = "ok"
    source.last_error = None
    session.flush()
    return raw


def _mark_error(source: Source, error: str) -> None:
    source.last_status = "error"
    source.last_error = error[:1000]
    source.last_fetched_at = utcnow()


def _ingest_markets(
    session: Session,
    run: IngestRun,
    assets: dict[str, Asset],
    sources: dict[str, Source],
    stats: dict,
) -> list[dict]:
    source = _source(sources, "coingecko")
    now = utcnow()
    try:
        markets = fetch_markets()
    except Exception as exc:  # noqa: BLE001
        _mark_error(source, str(exc))
        raise
    raw = _store_raw(session, source, run, f"markets:{now.isoformat()}", markets, now)
    for row in markets:
        asset = assets.get(row.get("id"))
        if not asset:
            continue
        _upsert_snapshot(
            session,
            asset=asset,
            captured_at=now,
            is_live=True,
            price=float(row["current_price"]),
            change_24h=_f(row.get("price_change_percentage_24h_in_currency") or row.get("price_change_percentage_24h")),
            change_7d=_f(row.get("price_change_percentage_7d_in_currency")),
            volume=_f(row.get("total_volume")),
            market_cap=_f(row.get("market_cap")),
            high=_f(row.get("high_24h")),
            low=_f(row.get("low_24h")),
            raw_id=raw.id,
        )
        stats["markets"] += 1
    return markets


def _ingest_charts(
    session: Session,
    run: IngestRun,
    assets: dict[str, Asset],
    sources: dict[str, Source],
    stats: dict,
) -> None:
    source = _source(sources, "coingecko")
    now = utcnow()
    charts = fetch_charts(list(assets.keys()))
    for coin_id, chart in charts.items():
        asset = assets[coin_id]
        raw = _store_raw(session, source, run, f"chart:{coin_id}:{now.date()}", chart, now)
        daily = _resample_daily(chart)
        for day in daily:
            _upsert_snapshot(
                session,
                asset=asset,
                captured_at=day["captured_at"],
                is_live=False,
                price=day["price"],
                change_24h=day["change_24h"],
                change_7d=day["change_7d"],
                volume=day["volume"],
                market_cap=None,
                high=day["high"],
                low=day["low"],
                volume_ratio=day["volume_ratio"],
                raw_id=raw.id,
            )
        stats["charts"] += 1


def _ingest_sparklines(session: Session, markets: list[dict], assets: dict[str, Asset]) -> None:
    """If daily charts were rate-limited, build a coarse history from the 7d sparkline."""
    for row in markets:
        asset = assets.get(row.get("id"))
        if not asset:
            continue
        already = session.scalars(
            select(MarketSnapshot).where(
                MarketSnapshot.asset_id == asset.id,
                MarketSnapshot.is_live.is_(False),
            )
        ).first()
        if already:
            continue
        series = (row.get("sparkline_in_7d") or {}).get("price") or []
        if len(series) < 24:
            continue
        fake_chart = {
            "prices": [
                [(utcnow() - timedelta(hours=len(series) - i)).timestamp() * 1000, float(price)]
                for i, price in enumerate(series)
            ],
            "total_volumes": [],
        }
        for day in _resample_daily(fake_chart):
            _upsert_snapshot(
                session,
                asset=asset,
                captured_at=day["captured_at"],
                is_live=False,
                price=day["price"],
                change_24h=day["change_24h"],
                change_7d=day["change_7d"],
                volume=None,
                market_cap=None,
                high=day["high"],
                low=day["low"],
                raw_id=None,
                volume_ratio=None,
            )


def _ingest_fear_greed(
    session: Session,
    run: IngestRun,
    sources: dict[str, Source],
    stats: dict,
) -> None:
    source = _source(sources, "fear_greed")
    now = utcnow()
    try:
        rows = fetch_fear_greed(30)
    except Exception as exc:  # noqa: BLE001
        _mark_error(source, str(exc))
        return
    raw = _store_raw(session, source, run, f"fng:{now.date()}", rows, now)
    for row in rows:
        captured = datetime.utcfromtimestamp(int(row["timestamp"]))
        existing = session.scalars(
            select(FearGreed).where(FearGreed.captured_at == captured)
        ).first()
        if existing:
            existing.value = int(row["value"])
            existing.classification = row.get("value_classification") or "Unknown"
            existing.raw_record_id = raw.id
        else:
            session.add(
                FearGreed(
                    captured_at=captured,
                    value=int(row["value"]),
                    classification=row.get("value_classification") or "Unknown",
                    raw_record_id=raw.id,
                )
            )
        stats["fear_greed"] += 1


def _ingest_news(
    session: Session,
    run: IngestRun,
    assets: dict[str, Asset],
    sources: dict[str, Source],
    stats: dict,
) -> None:
    keyword_map = [
        (asset.id, json.loads(asset.keywords_json))
        for asset in assets.values()
    ]
    now = utcnow()

    cc_source = _source(sources, "cryptocompare_news")
    try:
        cc_items = fetch_cryptocompare_news()
        raw = _store_raw(session, cc_source, run, f"cc-news:{now.isoformat()}", cc_items, now)
        for item in cc_items:
            published = datetime.utcfromtimestamp(int(item["published_on"]))
            _store_news(
                session,
                source=cc_source,
                raw_id=raw.id,
                fetched_at=now,
                published_at=published,
                title=item.get("title") or "",
                url=item.get("url") or item.get("guid") or "",
                summary=item.get("body") or "",
                keyword_map=keyword_map,
                stats=stats,
            )
    except Exception as exc:  # noqa: BLE001
        _mark_error(cc_source, str(exc))

    try:
        rss_items = fetch_rss()
    except Exception:
        rss_items = []
    grouped: dict[str, list[dict]] = {}
    for code, payload in rss_items:
        grouped.setdefault(code, []).append(payload)
    for code, payloads in grouped.items():
        source = _source(sources, code)
        raw = _store_raw(session, source, run, f"rss:{code}:{now.isoformat()}", payloads, now)
        for payload in payloads:
            published = (
                datetime.fromisoformat(payload["published_at"])
                if payload.get("published_at")
                else now
            )
            _store_news(
                session,
                source=source,
                raw_id=raw.id,
                fetched_at=now,
                published_at=published,
                title=payload.get("title") or "",
                url=payload.get("url") or "",
                summary=payload.get("summary") or "",
                keyword_map=keyword_map,
                stats=stats,
            )


def _store_news(
    session: Session,
    *,
    source: Source,
    raw_id: int,
    fetched_at: datetime,
    published_at: datetime,
    title: str,
    url: str,
    summary: str,
    keyword_map: list[tuple[int, list[str]]],
    stats: dict,
) -> None:
    if not url or not title:
        return
    existing = session.scalars(select(NewsItem).where(NewsItem.url == url)).first()
    sentiment = headline_sentiment(title, summary)
    market_wide = is_market_wide(title, summary)
    hits = match_assets(title, keyword_map, summary)
    if existing:
        news = existing
        news.sentiment = sentiment
        news.summary = summary[:4000] if summary else news.summary
        news.is_market_wide = market_wide
    else:
        news = NewsItem(
            source_id=source.id,
            published_at=published_at,
            fetched_at=fetched_at,
            title=title,
            url=url,
            summary=(summary or "")[:4000] or None,
            sentiment=sentiment,
            is_market_wide=market_wide,
            raw_record_id=raw_id,
        )
        session.add(news)
        session.flush()
        stats["news"] += 1

    mentioned_ids = {asset_id for asset_id, _ in hits}
    if market_wide:
        for asset_id, _ in keyword_map:
            if asset_id not in mentioned_ids:
                hits.append((asset_id, 0.35))
    if not hits and not market_wide:
        # Unmatched headlines still sit in the news table, but do not score assets.
        return
    existing_mentions = {
        (m.news_id, m.asset_id)
        for m in session.scalars(select(NewsMention).where(NewsMention.news_id == news.id)).all()
    }
    for asset_id, weight in hits:
        key = (news.id, asset_id)
        if key in existing_mentions:
            continue
        session.add(NewsMention(news_id=news.id, asset_id=asset_id, weight=weight))
        existing_mentions.add(key)


def _recompute_cross_sectional_volume(session: Session) -> None:
    """If a live snapshot has no chart-based volume_ratio, use turnover vs basket median."""
    now_snaps = session.scalars(
        select(MarketSnapshot)
        .where(MarketSnapshot.is_live.is_(True))
        .order_by(MarketSnapshot.captured_at.desc())
    ).all()
    if not now_snaps:
        return
    latest_at = now_snaps[0].captured_at
    latest = [s for s in now_snaps if s.captured_at == latest_at]
    turnovers = [s.turnover for s in latest if s.turnover and s.turnover > 0]
    if not turnovers:
        return
    mid = median(turnovers)
    if mid <= 0:
        return
    for snap in latest:
        if snap.volume_ratio is None and snap.turnover:
            snap.volume_ratio = snap.turnover / mid


def _upsert_snapshot(
    session: Session,
    *,
    asset: Asset,
    captured_at: datetime,
    is_live: bool,
    price: float,
    change_24h: float | None,
    change_7d: float | None,
    volume: float | None,
    market_cap: float | None,
    high: float | None,
    low: float | None,
    raw_id: int | None,
    volume_ratio: float | None = None,
) -> MarketSnapshot:
    captured_at = _naive(captured_at)
    existing = session.scalars(
        select(MarketSnapshot).where(
            MarketSnapshot.asset_id == asset.id,
            MarketSnapshot.captured_at == captured_at,
        )
    ).first()
    turnover = (volume / market_cap) if volume and market_cap else None
    fields = dict(
        is_live=is_live,
        price_usd=price,
        change_24h_pct=change_24h,
        change_7d_pct=change_7d,
        volume_24h=volume,
        market_cap=market_cap,
        high_24h=high,
        low_24h=low,
        volume_ratio=volume_ratio,
        turnover=turnover,
        raw_record_id=raw_id,
    )
    if existing:
        for key, value in fields.items():
            if key == "volume_ratio" and value is None:
                continue
            if key == "is_live" and existing.is_live and not is_live:
                continue
            setattr(existing, key, value)
        return existing
    snap = MarketSnapshot(asset_id=asset.id, captured_at=captured_at, **fields)
    session.add(snap)
    session.flush()
    return snap


def _resample_daily(chart: dict) -> list[dict]:
    prices = chart.get("prices") or []
    volumes = chart.get("total_volumes") or []
    vol_by_day: dict[datetime, list[float]] = {}
    price_by_day: dict[datetime, list[float]] = {}
    for ts, price in prices:
        day = datetime.utcfromtimestamp(ts / 1000.0).replace(hour=0, minute=0, second=0, microsecond=0)
        price_by_day.setdefault(day, []).append(float(price))
    for ts, volume in volumes:
        day = datetime.utcfromtimestamp(ts / 1000.0).replace(hour=0, minute=0, second=0, microsecond=0)
        vol_by_day.setdefault(day, []).append(float(volume))
    days = sorted(price_by_day)
    rows: list[dict] = []
    volumes_daily: list[float] = []
    for day in days:
        series = price_by_day[day]
        close = series[-1]
        high = max(series)
        low = min(series)
        vol = (sum(vol_by_day.get(day, [0.0])) / max(len(vol_by_day.get(day, [1])), 1)) if day in vol_by_day else None
        volumes_daily.append(vol or 0.0)
        rows.append(
            {
                "captured_at": day,
                "price": close,
                "high": high,
                "low": low,
                "volume": vol,
            }
        )
    for index, row in enumerate(rows):
        prev = rows[index - 1]["price"] if index else None
        week = rows[index - 7]["price"] if index >= 7 else rows[0]["price"]
        row["change_24h"] = ((row["price"] - prev) / prev * 100.0) if prev else None
        row["change_7d"] = ((row["price"] - week) / week * 100.0) if week else None
        window = [v for v in volumes_daily[max(0, index - 6) : index + 1] if v]
        avg = sum(window) / len(window) if window else None
        row["volume_ratio"] = (row["volume"] / avg) if avg and row["volume"] else None
    return rows


def _generate_live_forecasts(session: Session, assets: dict[str, Asset]) -> int:
    now = utcnow()
    count = 0
    for asset in assets.values():
        snap = session.scalars(
            select(MarketSnapshot)
            .where(MarketSnapshot.asset_id == asset.id, MarketSnapshot.is_live.is_(True))
            .order_by(MarketSnapshot.captured_at.desc())
            .limit(1)
        ).first()
        if not snap:
            continue
        _write_forecast(session, asset, snap, now, kind="live")
        count += 1
    return count


def _generate_backtests(session: Session, assets: dict[str, Asset], _markets: list[dict]) -> int:
    count = 0
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    for asset in assets.values():
        history = session.scalars(
            select(MarketSnapshot)
            .where(MarketSnapshot.asset_id == asset.id, MarketSnapshot.is_live.is_(False))
            .order_by(MarketSnapshot.captured_at.asc())
        ).all()
        if len(history) < 3:
            # Fall back to sparkline-less history: skip
            continue
        by_day = {s.captured_at.replace(hour=0, minute=0, second=0, microsecond=0): s for s in history}
        days = sorted(by_day)
        usable = [d for d in days if d < today][-BACKTEST_DAYS:]
        for day in usable:
            nxt = day + timedelta(days=1)
            if nxt not in by_day:
                # next close may be today's live-ish daily row
                nxt_snap = _closest_after(history, nxt)
            else:
                nxt_snap = by_day[nxt]
            if not nxt_snap:
                continue
            existing = session.scalars(
                select(Forecast).where(
                    Forecast.asset_id == asset.id,
                    Forecast.kind == "backtest",
                    Forecast.as_of == day,
                )
            ).first()
            if existing:
                continue
            forecast = _write_forecast(session, asset, by_day[day], day, kind="backtest")
            _resolve_forecast(session, forecast, nxt_snap.price_usd, nxt_snap.captured_at)
            count += 1
    return count


def _closest_after(history: list[MarketSnapshot], target: datetime) -> MarketSnapshot | None:
    later = [s for s in history if s.captured_at >= target]
    return later[0] if later else None


def _write_forecast(
    session: Session,
    asset: Asset,
    snap: MarketSnapshot,
    as_of: datetime,
    kind: str,
) -> Forecast:
    breakdown = compute_breakdown(session, asset, snap, as_of)
    built = build_forecast(breakdown, _vol_from_snap(snap))
    indicator = Indicator(
        asset_id=asset.id,
        computed_at=utcnow(),
        as_of=as_of,
        momentum=built["components"]["momentum"],
        volume=built["components"]["volume"],
        range_rev=built["components"]["range"],
        news=built["components"]["news"],
        fear_greed=built["components"]["fear_greed"],
        score=built["score"],
        news_count=built["news_count"],
        news_coverage=built["news_coverage"],
        agreement=built["agreement"],
        volatility_pct=built.get("volatility_pct"),
        breakdown_json=json.dumps(built, ensure_ascii=False, default=str),
    )
    session.add(indicator)
    session.flush()

    if kind == "live":
        previous = session.scalars(
            select(Forecast)
            .where(Forecast.asset_id == asset.id, Forecast.kind == "live", Forecast.resolved_at.is_(None))
            .order_by(Forecast.created_at.desc())
            .limit(1)
        ).first()
        if previous and (utcnow() - previous.created_at) < timedelta(hours=2):
            _record_update(session, previous, "score", str(previous.indicator.score), str(built["score"]), "refresh")
            previous.indicator_id = indicator.id
            previous.direction = built["direction"]
            previous.probability_up = built["probability_up"]
            previous.confidence = built["confidence"]
            previous.risk_level = built["risk_level"]
            previous.risk_notes_json = json.dumps(built["risk_notes"], ensure_ascii=False)
            previous.arguments_json = json.dumps(built["arguments"], ensure_ascii=False)
            previous.used_data_json = json.dumps(built["used_data"], ensure_ascii=False, default=str)
            previous.price_at_forecast = snap.price_usd
            return previous

    forecast = Forecast(
        asset_id=asset.id,
        indicator_id=indicator.id,
        created_at=utcnow(),
        as_of=as_of,
        horizon_hours=FORECAST_HORIZON_HOURS,
        kind=kind,
        direction=built["direction"],
        probability_up=built["probability_up"],
        confidence=built["confidence"],
        risk_level=built["risk_level"],
        risk_notes_json=json.dumps(built["risk_notes"], ensure_ascii=False),
        arguments_json=json.dumps(built["arguments"], ensure_ascii=False),
        used_data_json=json.dumps(built["used_data"], ensure_ascii=False, default=str),
        price_at_forecast=snap.price_usd,
        resolve_after=as_of + timedelta(hours=FORECAST_HORIZON_HOURS),
    )
    session.add(forecast)
    session.flush()
    return forecast


def _vol_from_snap(snap: MarketSnapshot) -> float | None:
    if snap.high_24h is None or snap.low_24h is None or snap.price_usd <= 0:
        return None
    return 100.0 * (snap.high_24h - snap.low_24h) / snap.price_usd


def _resolve_due_forecasts(session: Session) -> int:
    now = utcnow()
    due = session.scalars(
        select(Forecast).where(
            Forecast.resolved_at.is_(None),
            Forecast.resolve_after <= now,
            Forecast.kind == "live",
        )
    ).all()
    count = 0
    for forecast in due:
        later = session.scalars(
            select(MarketSnapshot)
            .where(
                MarketSnapshot.asset_id == forecast.asset_id,
                MarketSnapshot.captured_at >= forecast.resolve_after,
            )
            .order_by(MarketSnapshot.captured_at.asc())
            .limit(1)
        ).first()
        if not later:
            continue
        _resolve_forecast(session, forecast, later.price_usd, later.captured_at)
        count += 1
    return count


def _resolve_forecast(
    session: Session,
    forecast: Forecast,
    actual_price: float,
    resolved_at: datetime,
) -> None:
    ret = (actual_price - forecast.price_at_forecast) / forecast.price_at_forecast * 100.0
    actual = actual_direction(ret)
    forecast.resolved_at = resolved_at
    forecast.actual_price = actual_price
    forecast.actual_return_pct = ret
    forecast.actual_direction = actual
    forecast.was_correct = forecast.direction == actual
    forecast.brier = brier_score(forecast.probability_up, ret)
    forecast.resolution_notes = (
        f"Цена {forecast.price_at_forecast:.4f} → {actual_price:.4f} ({ret:+.2f}%). "
        f"Прогноз {forecast.direction}, факт {actual}. "
        + ("Совпало." if forecast.was_correct else "Ошибка: знак или режим не совпал.")
    )
    _record_update(
        session,
        forecast,
        "was_correct",
        None,
        str(forecast.was_correct),
        forecast.resolution_notes,
    )


def _record_update(
    session: Session,
    forecast: Forecast,
    field: str,
    old: str | None,
    new: str | None,
    reason: str,
) -> None:
    session.add(
        ForecastUpdate(
            forecast_id=forecast.id,
            created_at=utcnow(),
            field=field,
            old_value=old,
            new_value=new,
            reason=reason,
        )
    )


def _naive(value: datetime) -> datetime:
    if value.tzinfo:
        return value.replace(tzinfo=None)
    return value


def _f(value) -> float | None:
    if value is None:
        return None
    return float(value)


# keep ASSETS imported for type clarity in charts fallback
_ = ASSETS
