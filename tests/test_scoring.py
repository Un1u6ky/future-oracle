import math

import pytest

from app.scoring.engine import (
    WEIGHTS,
    actual_direction,
    brier_score,
    build_forecast,
    direction_from_score,
    probability_up,
    score_components,
)
from app.scoring.lexicon import headline_sentiment, match_assets


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-12


def test_worked_example_numbers_add_up():
    """The README / card arithmetic. If this fails, the UI is lying."""
    result = score_components(
        change_24h_pct=4.2,
        change_7d_pct=8.0,
        volume_ratio=1.35,
        position_in_range=0.88,
        news_sentiment=0.45,
        news_count=6,
        fear_greed_value=32,
        volatility_pct=5.0,
    )
    m24 = 4.2 / 15.0
    m7 = 8.0 / 25.0
    momentum = 0.65 * m24 + 0.35 * m7
    volume = math.tanh(1.35 - 1.0)
    range_rev = (0.5 - 0.88) * 2.0
    news = 0.45
    fng = (50 - 32) / 50.0
    expected = 0.28 * momentum + 0.18 * volume + 0.12 * range_rev + 0.25 * news + 0.17 * fng

    assert result["components"]["momentum"] == pytest.approx(momentum, rel=1e-5)
    assert result["components"]["volume"] == pytest.approx(volume, rel=1e-5)
    assert result["components"]["range"] == pytest.approx(range_rev, rel=1e-5)
    assert result["components"]["news"] == pytest.approx(news, rel=1e-5)
    assert result["components"]["fear_greed"] == pytest.approx(fng, rel=1e-5)
    assert result["score"] == pytest.approx(expected, rel=1e-5)
    assert abs(sum(result["weighted"].values()) - result["score"]) < 1e-6
    assert result["direction"] == "up"
    assert result["probability_up"] == pytest.approx(1 / (1 + math.exp(-3.2 * expected)), rel=1e-5)
    assert result["agreement"] == pytest.approx(0.8)
    assert result["confidence"] == pytest.approx(
        100 * (0.50 * abs(expected) + 0.32 * 0.8 + 0.18 * 1.0), rel=1e-4
    )


def test_sideways_corridor():
    result = score_components(
        change_24h_pct=0.4,
        change_7d_pct=0.2,
        volume_ratio=1.0,
        position_in_range=0.5,
        news_sentiment=0.0,
        news_count=0,
        fear_greed_value=50,
    )
    assert abs(result["score"]) < 0.12
    assert result["direction"] == "sideways"
    assert 0.45 < result["probability_up"] < 0.55


def test_resolution_rules():
    assert actual_direction(1.2) == "up"
    assert actual_direction(-1.2) == "down"
    assert actual_direction(0.1) == "sideways"
    assert brier_score(0.8, 2.0) == pytest.approx(0.04)
    assert brier_score(0.8, -2.0) == pytest.approx(0.64)


def test_lexicon_and_matching():
    assert headline_sentiment("Bitcoin ETF approved, inflows surge") > 0.5
    assert headline_sentiment("Exchange hack triggers crash and liquidations") < -0.5
    assert headline_sentiment("Weather in Lisbon stays mild") == 0.0
    hits = match_assets("Solana breaks out after outage", [(1, ["bitcoin"]), (2, ["solana", "sol"])])
    assert hits == [(2, 1.0)]


def test_risk_notes_are_data_driven():
    built = build_forecast(
        score_components(
            change_24h_pct=12.0,
            change_7d_pct=20.0,
            volume_ratio=0.5,
            position_in_range=0.95,
            news_sentiment=-0.6,
            news_count=1,
            fear_greed_value=82,
            volatility_pct=12.0,
        ),
        12.0,
    )
    assert built["risk_level"] in {"medium", "high"}
    assert built["arguments"]
    assert any("Объём" in note or "новост" in note.lower() or "жадност" in note.lower() for note in built["risk_notes"])


def test_low_volume_does_not_flip_momentum():
    result = score_components(
        change_24h_pct=-6.0,
        change_7d_pct=-8.0,
        volume_ratio=0.55,
        position_in_range=0.5,
        news_sentiment=0.0,
        news_count=0,
        fear_greed_value=50,
    )
    assert result["components"]["momentum"] < 0
    assert result["components"]["volume"] == 0.0


def test_direction_thresholds():
    assert direction_from_score(0.13) == "up"
    assert direction_from_score(-0.13) == "down"
    assert direction_from_score(0.0) == "sideways"
