"""Deterministic headline scoring. No LLM in the prediction path."""

from __future__ import annotations

import re

BULLISH = (
    "etf approved",
    "spot etf",
    "all-time high",
    "record high",
    "breaks out",
    "breakout",
    "bullish",
    "rally",
    "rallies",
    "surge",
    "surges",
    "soars",
    "soaring",
    "jumps",
    "inflow",
    "inflows",
    "accumulation",
    "institutional",
    "adoption",
    "partnership",
    "upgrade",
    "mainnet",
    "buyback",
    "undervalued",
    "rebounds",
    "recovery",
    "green",
    "ath",
)

BEARISH = (
    "hack",
    "hacked",
    "exploit",
    "lawsuit",
    "sues",
    "sued",
    "ban",
    "banned",
    "crackdown",
    "liquidation",
    "liquidations",
    "sell-off",
    "selloff",
    "sell off",
    "bearish",
    "crash",
    "crashes",
    "collapse",
    "fraud",
    "outflow",
    "outflows",
    "sec charges",
    "charges",
    "probe",
    "investigation",
    "default",
    "bankrupt",
    "dump",
    "dumps",
    "plunge",
    "plunges",
    "tumbles",
    "slump",
    "warning",
    "risk-off",
)

MARKET_WIDE = (
    "crypto market",
    "cryptocurrency market",
    "digital assets",
    "risk appetite",
    "macro",
    "fed ",
    "interest rate",
    "inflation",
    "stock market",
)

_WORD_BOUNDARY_SKIP = {"etf approved", "spot etf", "sec charges"}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _contains(haystack: str, needle: str) -> bool:
    if needle in _WORD_BOUNDARY_SKIP or " " in needle:
        return needle in haystack
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def headline_sentiment(title: str, summary: str | None = None) -> float:
    """Return sentiment in [-1, 1] from a fixed lexicon.

    score = (bull - bear) / (bull + bear), or 0 if no keywords matched.
    """
    text = _normalize(f"{title} {summary or ''}")
    bull = sum(1 for phrase in BULLISH if _contains(text, phrase))
    bear = sum(1 for phrase in BEARISH if _contains(text, phrase))
    if bull + bear == 0:
        return 0.0
    return (bull - bear) / (bull + bear)


def is_market_wide(title: str, summary: str | None = None) -> bool:
    text = _normalize(f"{title} {summary or ''}")
    return any(_contains(text, phrase) for phrase in MARKET_WIDE)


def match_assets(
    title: str,
    assets: list[tuple[int, list[str]]],
    summary: str | None = None,
) -> list[tuple[int, float]]:
    """assets: list of (asset_id, keywords). Returns (asset_id, weight)."""
    text = _normalize(f"{title} {summary or ''}")
    hits: list[tuple[int, float]] = []
    for asset_id, keywords in assets:
        if any(_contains(text, kw) for kw in keywords):
            hits.append((asset_id, 1.0))
    return hits
