from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import sleep

import feedparser

from app.config import (
    ASSETS,
    CHART_DAYS,
    COINGECKO_CHART_URL,
    COINGECKO_MARKETS_URL,
    CRYPTOCOMPARE_NEWS_URL,
    FEAR_GREED_URL,
    RSS_FEEDS,
)
from app.ingest.http import get_bytes, get_json


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def fetch_markets() -> list[dict]:
    ids = ",".join(item["coingecko_id"] for item in ASSETS)
    payload = get_json(
        COINGECKO_MARKETS_URL,
        params={
            "vs_currency": "usd",
            "ids": ids,
            "order": "market_cap_desc",
            "per_page": len(ASSETS),
            "page": 1,
            "sparkline": "true",
            "price_change_percentage": "24h,7d",
        },
    )
    if not isinstance(payload, list):
        raise RuntimeError("CoinGecko markets: unexpected payload")
    return payload


def fetch_chart(coingecko_id: str) -> dict:
    payload = get_json(
        COINGECKO_CHART_URL.format(id=coingecko_id),
        params={"vs_currency": "usd", "days": CHART_DAYS},
    )
    if not isinstance(payload, dict):
        raise RuntimeError(f"CoinGecko chart {coingecko_id}: unexpected payload")
    return payload


def fetch_charts(ids: list[str]) -> dict[str, dict]:
    charts: dict[str, dict] = {}
    for index, coin_id in enumerate(ids):
        try:
            charts[coin_id] = fetch_chart(coin_id)
        except Exception:
            continue
        if index < len(ids) - 1:
            sleep(1.3)
    return charts


def fetch_fear_greed(limit: int = 30) -> list[dict]:
    payload = get_json(FEAR_GREED_URL, params={"limit": limit, "format": "json"})
    if not isinstance(payload, dict) or "data" not in payload:
        raise RuntimeError("Fear & Greed: unexpected payload")
    return payload["data"]


def fetch_cryptocompare_news() -> list[dict]:
    payload = get_json(CRYPTOCOMPARE_NEWS_URL, params={"lang": "EN"})
    if not isinstance(payload, dict) or payload.get("Type") != 100:
        raise RuntimeError("CryptoCompare news: unexpected payload")
    return payload.get("Data") or []


def fetch_rss() -> list[tuple[str, dict]]:
    items: list[tuple[str, dict]] = []
    for code, url in RSS_FEEDS:
        try:
            raw = get_bytes(url)
        except Exception:
            continue
        parsed = feedparser.parse(raw)
        for entry in parsed.entries:
            published = _rss_datetime(entry)
            items.append(
                (
                    code,
                    {
                        "title": entry.get("title") or "",
                        "url": entry.get("link") or "",
                        "summary": _strip_html(entry.get("summary") or ""),
                        "published_at": published.isoformat() if published else None,
                    },
                )
            )
    return items


def _rss_datetime(entry) -> datetime | None:
    for key in ("published", "updated"):
        value = entry.get(key)
        if not value:
            continue
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except (TypeError, ValueError, OverflowError):
            continue
    if entry.get("published_parsed"):
        try:
            return datetime(*entry.published_parsed[:6])
        except (TypeError, ValueError):
            return None
    return None


def _strip_html(text: str) -> str:
    import re

    return re.sub(r"<[^>]+>", " ", text).strip()


def dump(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)
