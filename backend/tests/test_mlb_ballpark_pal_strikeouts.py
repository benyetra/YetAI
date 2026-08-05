from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock


def test_bpp_pitcher_strikeouts_blend_and_override_matchup_source(monkeypatch):
    from app.services.etl.mlb import strikeouts

    assert hasattr(strikeouts, "maybe_apply_bpp_k_prior")

    session = MagicMock()
    row = SimpleNamespace(averages_json={"strikeouts": 8.0})
    calls = []

    monkeypatch.setattr(strikeouts, "ballpark_pal_enabled", lambda: True)
    monkeypatch.setattr(strikeouts, "bpp_k_prior_weight", lambda: 0.25)

    def load_player_proj(db, player_id, slate_date, role):
        calls.append((db, player_id, slate_date, role))
        return row

    monkeypatch.setattr(strikeouts.bpp_store, "load_player_proj", load_player_proj)

    projected_k, source = strikeouts.maybe_apply_bpp_k_prior(
        6.0,
        pitcher_id=42,
        slate_date=date(2026, 8, 5),
        matchup_source="observed",
        session=session,
    )

    assert projected_k == 6.5
    assert source == "ballpark_pal"
    assert calls == [(session, 42, date(2026, 8, 5), "pitcher")]


def test_bpp_pitcher_strikeouts_soft_fail_when_disabled(monkeypatch):
    from app.services.etl.mlb import strikeouts

    assert hasattr(strikeouts, "maybe_apply_bpp_k_prior")
    monkeypatch.setattr(strikeouts, "ballpark_pal_enabled", lambda: False)

    assert strikeouts.maybe_apply_bpp_k_prior(
        6.0,
        pitcher_id=42,
        slate_date=date(2026, 8, 5),
        matchup_source="observed",
        session=MagicMock(),
    ) == (6.0, "observed")


def test_bpp_pitcher_strikeouts_soft_fail_when_projection_missing(monkeypatch):
    from app.services.etl.mlb import strikeouts

    assert hasattr(strikeouts, "maybe_apply_bpp_k_prior")
    monkeypatch.setattr(strikeouts, "ballpark_pal_enabled", lambda: True)
    monkeypatch.setattr(strikeouts.bpp_store, "load_player_proj", lambda *_args: None)

    assert strikeouts.maybe_apply_bpp_k_prior(
        6.0,
        pitcher_id=42,
        slate_date=date(2026, 8, 5),
        matchup_source="shrunk",
        session=MagicMock(),
    ) == (6.0, "shrunk")
