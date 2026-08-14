"""Transparent scoring. Every number on a forecast card comes from here."""

from __future__ import annotations

import math
from typing import Any

WEIGHTS = {
    "momentum": 0.28,
    "volume": 0.18,
    "range": 0.12,
    "news": 0.25,
    "fear_greed": 0.17,
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

MOMENTUM_24H_SCALE = 15.0
MOMENTUM_7D_SCALE = 25.0
MOMENTUM_24H_MIX = 0.65
MOMENTUM_7D_MIX = 0.35
SIDEWAYS_THRESHOLD = 0.12
SIGMOID_K = 3.2
RESOLVE_MOVE_PCT = 0.5
NEWS_COVERAGE_TARGET = 5.0


def clip(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def momentum_score(change_24h_pct: float | None, change_7d_pct: float | None) -> tuple[float, dict]:
    m24 = clip((change_24h_pct or 0.0) / MOMENTUM_24H_SCALE)
    m7 = clip((change_7d_pct or 0.0) / MOMENTUM_7D_SCALE)
    value = MOMENTUM_24H_MIX * m24 + MOMENTUM_7D_MIX * m7
    return value, {
        "change_24h_pct": change_24h_pct,
        "change_7d_pct": change_7d_pct,
        "m24": round(m24, 6),
        "m7": round(m7, 6),
        "formula": f"{MOMENTUM_24H_MIX}*(Δ24h/{MOMENTUM_24H_SCALE}) + {MOMENTUM_7D_MIX}*(Δ7d/{MOMENTUM_7D_SCALE})",
    }


def volume_score(volume_ratio: float | None, momentum: float) -> tuple[float, dict]:
    """High volume confirms the momentum sign; low volume shrinks toward 0, never flips it."""
    if volume_ratio is None:
        return 0.0, {"volume_ratio": None, "note": "нет истории объёма — сигнал = 0"}
    confirmation = max(math.tanh(volume_ratio - 1.0), 0.0)
    sign = 1.0 if momentum >= 0 else -1.0
    value = sign * confirmation
    return value, {
        "volume_ratio": volume_ratio,
        "confirmation": round(confirmation, 6),
        "formula": "sign(momentum) * max(tanh(volume_ratio - 1), 0)",
    }


def range_score(position_in_range: float | None) -> tuple[float, dict]:
    """Mean-reversion inside the 24h range: near high → slightly bearish."""
    if position_in_range is None:
        return 0.0, {"position_in_range": None, "note": "нет high/low — сигнал = 0"}
    value = clip((0.5 - position_in_range) * 2.0)
    return value, {
        "position_in_range": position_in_range,
        "formula": "clip((0.5 - position) * 2)",
    }


def fear_greed_score(value: int | None) -> tuple[float, dict]:
    """Contrarian: extreme fear is a plus, extreme greed is a minus."""
    if value is None:
        return 0.0, {"fear_greed": None, "note": "индекс недоступен — сигнал = 0"}
    score = clip((50.0 - float(value)) / 50.0)
    return score, {
        "fear_greed": value,
        "formula": "(50 - F&G) / 50",
    }


def news_coverage(news_count: int) -> float:
    return clip(news_count / NEWS_COVERAGE_TARGET, 0.0, 1.0)


def score_components(
    *,
    change_24h_pct: float | None,
    change_7d_pct: float | None,
    volume_ratio: float | None,
    position_in_range: float | None,
    news_sentiment: float,
    news_count: int,
    fear_greed_value: int | None,
    volatility_pct: float | None = None,
) -> dict[str, Any]:
    momentum, momentum_meta = momentum_score(change_24h_pct, change_7d_pct)
    volume, volume_meta = volume_score(volume_ratio, momentum)
    range_rev, range_meta = range_score(position_in_range)
    fng, fng_meta = fear_greed_score(fear_greed_value)
    news = clip(news_sentiment)

    components = {
        "momentum": momentum,
        "volume": volume,
        "range": range_rev,
        "news": news,
        "fear_greed": fng,
    }
    weighted = {name: WEIGHTS[name] * value for name, value in components.items()}
    score = sum(weighted.values())
    agreement = _agreement(score, components)
    coverage = news_coverage(news_count)
    confidence = confidence_pct(
        score=score,
        agreement=agreement,
        news_coverage_value=coverage,
        volatility_pct=volatility_pct,
    )
    return {
        "components": {k: round(v, 6) for k, v in components.items()},
        "weights": dict(WEIGHTS),
        "weighted": {k: round(v, 6) for k, v in weighted.items()},
        "score": round(score, 6),
        "agreement": round(agreement, 6),
        "news_count": news_count,
        "news_coverage": round(coverage, 6),
        "confidence": round(confidence, 4),
        "direction": direction_from_score(score),
        "probability_up": round(probability_up(score), 6),
        "meta": {
            "momentum": momentum_meta,
            "volume": volume_meta,
            "range": range_meta,
            "fear_greed": fng_meta,
            "news": {"sentiment": news, "count": news_count},
        },
    }


def _agreement(score: float, components: dict[str, float]) -> float:
    if abs(score) < 1e-9:
        return 0.5
    target = 1 if score > 0 else -1
    signed = []
    for value in components.values():
        if value > 0.02:
            signed.append(1)
        elif value < -0.02:
            signed.append(-1)
    if not signed:
        return 0.5
    return sum(1 for item in signed if item == target) / len(signed)


def probability_up(score: float) -> float:
    return 1.0 / (1.0 + math.exp(-SIGMOID_K * score))


def direction_from_score(score: float) -> str:
    if score > SIDEWAYS_THRESHOLD:
        return "up"
    if score < -SIDEWAYS_THRESHOLD:
        return "down"
    return "sideways"


def confidence_pct(
    *,
    score: float,
    agreement: float,
    news_coverage_value: float,
    volatility_pct: float | None,
    stale: bool = False,
) -> float:
    """How much we trust the score, 0–100. Separate from P(up)."""
    raw = 0.50 * abs(score) + 0.32 * agreement + 0.18 * news_coverage_value
    if volatility_pct is not None and volatility_pct > 8.0:
        raw *= 0.85
    if stale:
        raw *= 0.80
    return clip(raw, 0.0, 1.0) * 100.0


def risk_from_breakdown(breakdown: dict[str, Any], volatility_pct: float | None) -> tuple[str, list[str]]:
    notes: list[str] = []
    components = breakdown["components"]
    score = breakdown["score"]
    opposing = [
        name
        for name, value in components.items()
        if abs(value) > 0.05 and (value > 0) != (score > 0) and abs(score) > 1e-9
    ]
    if opposing:
        notes.append(
            "Противоречие сигналов: "
            + ", ".join(_label(name) for name in opposing)
            + " смотрят против итогового знака."
        )
    if abs(score) < SIDEWAYS_THRESHOLD:
        notes.append(
            f"Итоговый score {score:+.3f} внутри коридора ±{SIDEWAYS_THRESHOLD} — рынок скорее боковой."
        )
    if breakdown["news_count"] < 2:
        notes.append("Мало релевантных новостей: сентимент легко переворачивается одной статьёй.")
    if volatility_pct is not None and volatility_pct > 8.0:
        notes.append(
            f"Внутридневной диапазон {volatility_pct:.1f}% — шум может съесть 24-часовой сигнал."
        )
    volume_ratio = breakdown["meta"]["volume"].get("volume_ratio")
    if volume_ratio is not None and volume_ratio < 0.75:
        notes.append(
            f"Объём {volume_ratio:.2f}× от среднего — движение может быть неподтверждённым."
        )
    fng = breakdown["meta"]["fear_greed"].get("fear_greed")
    if fng is not None and fng >= 75:
        notes.append(f"Fear & Greed = {fng} (жадность): контрастный сигнал может опоздать.")
    if fng is not None and fng <= 20:
        notes.append(f"Fear & Greed = {fng} (страх): отскок не обязан случиться завтра.")

    if len(notes) >= 3 or (opposing and volatility_pct and volatility_pct > 8):
        level = "high"
    elif notes:
        level = "medium"
    else:
        level = "low"
        notes.append("Сигналы согласованы, волатильность обычная — основной риск: новость вне выборки.")
    return level, notes


def arguments_from_breakdown(breakdown: dict[str, Any]) -> list[str]:
    args: list[str] = []
    meta = breakdown["meta"]
    comps = breakdown["components"]
    chg = meta["momentum"].get("change_24h_pct")
    chg7 = meta["momentum"].get("change_7d_pct")
    if chg is not None:
        args.append(
            f"Импульс: 24ч {chg:+.2f}%, 7д {chg7:+.2f}% → momentum = {comps['momentum']:+.3f} "
            f"(вес {WEIGHTS['momentum']:.0%})."
        )
    vol = meta["volume"].get("volume_ratio")
    if vol is None:
        args.append("Объём: истории нет, сигнал обнулён.")
    elif abs(comps["volume"]) < 1e-6:
        args.append(
            f"Объём {vol:.2f}× среднего — ниже нормы, confirmation = 0 → volume = 0 "
            f"(вес {WEIGHTS['volume']:.0%})."
        )
    else:
        args.append(
            f"Объём {vol:.2f}× среднего подтверждает знак импульса → volume = {comps['volume']:+.3f} "
            f"(вес {WEIGHTS['volume']:.0%})."
        )
    pos = meta["range"].get("position_in_range")
    if pos is not None:
        args.append(
            f"Цена на {pos:.0%} 24ч-диапазона → mean-reversion {comps['range']:+.3f} "
            f"(вес {WEIGHTS['range']:.0%})."
        )
    args.append(
        f"Новости: сентимент {comps['news']:+.3f} по {breakdown['news_count']} заголовкам "
        f"(вес {WEIGHTS['news']:.0%})."
    )
    fng = meta["fear_greed"].get("fear_greed")
    if fng is not None:
        args.append(
            f"Fear & Greed = {fng} (контрарий) → {comps['fear_greed']:+.3f} "
            f"(вес {WEIGHTS['fear_greed']:.0%})."
        )
    args.append(
        "Сумма: "
        + " + ".join(f"{w:+.4f}" for w in breakdown["weighted"].values())
        + f" = {breakdown['score']:+.4f}."
    )
    return args


def build_forecast(breakdown: dict[str, Any], volatility_pct: float | None) -> dict[str, Any]:
    risk_level, risk_notes = risk_from_breakdown(breakdown, volatility_pct)
    return {
        **breakdown,
        "risk_level": risk_level,
        "risk_notes": risk_notes,
        "arguments": arguments_from_breakdown(breakdown),
        "volatility_pct": volatility_pct,
    }


def actual_direction(return_pct: float) -> str:
    if return_pct > RESOLVE_MOVE_PCT:
        return "up"
    if return_pct < -RESOLVE_MOVE_PCT:
        return "down"
    return "sideways"


def outcome_target(return_pct: float) -> float:
    """1 if up, 0 if down, 0.5 if sideways — for Brier score on P(up)."""
    direction = actual_direction(return_pct)
    if direction == "up":
        return 1.0
    if direction == "down":
        return 0.0
    return 0.5


def brier_score(probability_up_value: float, return_pct: float) -> float:
    target = outcome_target(return_pct)
    return (probability_up_value - target) ** 2


def _label(name: str) -> str:
    return {
        "momentum": "импульс",
        "volume": "объём",
        "range": "диапазон",
        "news": "новости",
        "fear_greed": "Fear & Greed",
    }[name]
