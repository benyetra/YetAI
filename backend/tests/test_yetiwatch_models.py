"""Tests for YetiWatch Pydantic models and formatting."""

from datetime import date, datetime, timezone

from app.services.etl.wnba.yetiwatch.models import (
    ImpactDirection,
    ImpactMagnitude,
    YetiWatchSignalPayload,
    build_neutral_payload,
    build_news_string,
    format_impact_tag,
)


def test_example_payload_validates():
    raw = {
        "run_id": "wnba-2026-06-28-r3",
        "as_of": "2026-06-28T21:40:00Z",
        "player_id": "wnba_player_00123",
        "player_name": "Player A",
        "team_id": "wnba_team_007",
        "game_id": "wnba_game_2026_06_28_007_011",
        "opponent_id": "wnba_team_011",
        "game_start": "2026-06-28T23:00:00Z",
        "status": "available",
        "availability_prob": 0.95,
        "minutes_outlook": {
            "cap_min": 22,
            "delta_min": -8,
            "note": "On a minutes cap returning from ankle.",
        },
        "usage_delta": "neutral",
        "usage_delta_factor": None,
        "role_change": {"from": "starter", "to": "starter"},
        "signal_types": ["injury_status_change", "minutes_restriction"],
        "impact": {
            "direction": "down",
            "magnitude": "medium",
            "confidence": 0.82,
            "rationale": "Minutes capped on return, usage unchanged, so counting stats project lower.",
        },
        "related_subjects": [],
        "news_string": "Min cap ~22 on return from ankle; usage steady. [prod \u2193 med] 5:40p ET",
        "provenance": {
            "source_count": 3,
            "corroboration": "corroborated",
            "source_tiers": ["official", "beat_writer"],
            "latest_source_ts": "2026-06-28T21:36:00Z",
        },
    }
    payload = YetiWatchSignalPayload.model_validate(raw)
    assert payload.player_id == "wnba_player_00123"
    assert "\u2193" in payload.news_string


def test_neutral_payload_has_explicit_news():
    as_of = datetime(2026, 6, 28, 19, 0, tzinfo=timezone.utc)
    payload = build_neutral_payload(
        run_id="wnba-2026-06-28-r2",
        as_of=as_of,
        player_id=789,
        player_name="Player C",
        team_id=7,
        game_date=date(2026, 6, 28),
        opponent_id=11,
    )
    assert "No material news" in payload.news_string
    assert "[neutral]" in payload.news_string
    assert payload.impact.direction == ImpactDirection.NEUTRAL


def test_build_news_string_arrows():
    as_of = datetime(2026, 6, 28, 21, 40, tzinfo=timezone.utc)
    news = build_news_string(
        "Usage projects up.",
        as_of=as_of,
        direction=ImpactDirection.UP,
        magnitude=ImpactMagnitude.MEDIUM,
    )
    assert "\u2191" in news
    assert (
        format_impact_tag(ImpactDirection.DOWN, ImpactMagnitude.HIGH)
        == "[prod \u2193 high]"
    )
