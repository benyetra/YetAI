"""Tests for NBA FanDuel line fetch + core stat projection wiring."""

from __future__ import annotations

from contextlib import ExitStack
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.etl.nba import (
    generate_assists_predictions as ast_mod,
    generate_points_predictions as pts_mod,
    generate_rebounds_predictions as reb_mod,
    store_actuals as sa_mod,
)
from app.services.etl.nba import _fanduel_lines as fdl
from app.services.etl.nba._fanduel_lines import (
    PROP_MARKETS,
    apply_fanduel_to_projection,
    fetch_fanduel_prop_for_player,
)


def test_fetch_fanduel_prop_returns_none_without_event():
    with patch(
        "app.services.etl.nba._fanduel_lines.get_event_id_for_game", return_value=None
    ):
        line, flag = fetch_fanduel_prop_for_player(
            "Boston Celtics",
            "Los Angeles Lakers",
            "Jayson Tatum",
            PROP_MARKETS["points"],
            28.5,
        )
    assert line is None
    assert flag is None


def test_fetch_fanduel_prop_returns_line_when_api_responds():
    with (
        patch(
            "app.services.etl.nba._fanduel_lines.get_event_id_for_game",
            return_value="evt-1",
        ),
        patch(
            "app.services.etl.nba._fanduel_lines.get_fanduel_line",
            return_value=(24.5, -110.0, "o"),
        ),
    ):
        line, flag = fetch_fanduel_prop_for_player(
            "Boston Celtics",
            "Los Angeles Lakers",
            "Jayson Tatum",
            PROP_MARKETS["points"],
            28.5,
        )
    assert line == 24.5
    assert flag == "o"


def test_apply_fanduel_to_projection_sets_orm_fields():
    row = SimpleNamespace(fanduel_line=None, fanduel_over_under=None)
    with patch(
        "app.services.etl.nba._fanduel_lines.fetch_fanduel_prop_for_player",
        return_value=(18.5, "u"),
    ):
        attached = apply_fanduel_to_projection(
            row,
            team_name="Celtics",
            opponent_team_name="Lakers",
            player_name="Jayson Tatum",
            market=PROP_MARKETS["rebounds"],
            projection=9.2,
        )
    assert attached is True
    assert row.fanduel_line == 18.5
    assert row.fanduel_over_under == "u"


def _run_generator_with_fd_mock(module, *, projected: float, market_key: str):
    today = date(2026, 5, 24)
    player = SimpleNamespace(
        player_id=42,
        player_name="Test Player",
        team_name="Boston Celtics",
        opponent_team_name="Los Angeles Lakers",
        opponent_team_id=99,
    )
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = [player]
    mock_db.query.return_value.filter.return_value.first.return_value = None

    with ExitStack() as stack:
        stack.enter_context(patch.object(module, "SessionLocal", return_value=mock_db))
        ne = stack.enter_context(patch.object(module, "now_eastern"))
        stack.enter_context(
            patch.object(module, "_is_injured", return_value=(False, None))
        )
        stack.enter_context(patch.object(module, "get_metadata", return_value={}))
        stack.enter_context(
            patch.object(module, "model_version_from_metadata", return_value="xgb-test")
        )
        fd = stack.enter_context(
            patch.object(module, "apply_fanduel_to_projection", return_value=True)
        )
        if module is pts_mod:
            stack.enter_context(
                patch.object(module, "build_points_features", return_value={"x": 1})
            )
            stack.enter_context(
                patch.object(module, "predict_points", return_value=projected)
            )
        else:
            stack.enter_context(
                patch.object(module, "build_features", return_value={"x": 1})
            )
            stack.enter_context(patch.object(module, "predict", return_value=projected))
        ne.return_value.date.return_value = today
        summary = module.run()

    fd.assert_called_once()
    _args, kwargs = fd.call_args
    assert kwargs["market"] == PROP_MARKETS[market_key]
    assert kwargs["projection"] == pytest.approx(projected)
    return summary, mock_db, projected


@pytest.mark.parametrize(
    "module,stat_attr,market_key,projected",
    [
        (pts_mod, "projected_points", "points", 22.3),
        (reb_mod, "projected_rebounds", "rebounds", 7.1),
        (ast_mod, "projected_assists", "assists", 7.1),
    ],
)
def test_generators_attach_fanduel_line_to_upsert(
    module, stat_attr, market_key, projected
):
    summary, mock_db, projected = _run_generator_with_fd_mock(
        module, projected=projected, market_key=market_key
    )
    added = mock_db.add.call_args[0][0]
    assert getattr(added, stat_attr) == pytest.approx(projected)
    assert summary["fanduel_lines_attached"] == 1
    assert summary["fanduel_line_coverage_pct"] == 100.0


def test_generators_coverage_pct_partial_lines():
    today = date(2026, 5, 24)
    players = [
        SimpleNamespace(
            player_id=i,
            player_name=f"P{i}",
            team_name="Celtics",
            opponent_team_name="Lakers",
            opponent_team_id=99,
        )
        for i in (1, 2)
    ]
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = players
    mock_db.query.return_value.filter.return_value.first.return_value = None

    with (
        patch.object(pts_mod, "SessionLocal", return_value=mock_db),
        patch.object(pts_mod, "now_eastern") as ne,
        patch.object(pts_mod, "_is_injured", return_value=(False, None)),
        patch.object(pts_mod, "build_points_features", return_value={"x": 1}),
        patch.object(pts_mod, "predict_points", return_value=20.0),
        patch.object(pts_mod, "get_metadata", return_value={}),
        patch.object(pts_mod, "model_version_from_metadata", return_value="xgb-test"),
        patch.object(
            pts_mod,
            "apply_fanduel_to_projection",
            side_effect=[True, False],
        ),
    ):
        ne.return_value.date.return_value = today
        summary = pts_mod.run()

    assert summary["fanduel_lines_attached"] == 1
    assert summary["fanduel_line_coverage_pct"] == 50.0


def test_store_actuals_grades_ou_and_reports_coverage():
    target = date(2026, 5, 23)
    proj = SimpleNamespace(
        player_id=1,
        player_name="Test",
        opponent_team_name="LAL",
        projected_rebounds=8.0,
        fanduel_line=7.5,
        fanduel_over_under="over",
    )
    recent = SimpleNamespace(player_id=1, rebounds=10)
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.side_effect = [
        [proj],
        [recent],
    ]
    mock_db.query.return_value.filter.return_value.first.return_value = None

    with patch.object(sa_mod, "SessionLocal", return_value=mock_db):
        out = sa_mod._store_stat(
            mock_db,
            "rebounds",
            sa_mod.STAT_CONFIG["rebounds"],
            target,
        )

    assert out["written"] == 1
    assert out["ou_graded"] == 1
    assert out["projections_with_line"] == 1
    assert out["ou_line_coverage_pct"] == 100.0
    assert out["ou_graded_coverage_pct"] == 100.0
    added = mock_db.add.call_args[0][0]
    assert added.correct_prediction is True


def test_compute_correct_prediction_under_side():
    proj = SimpleNamespace(fanduel_line=20.5, fanduel_over_under="u")
    assert sa_mod._compute_correct_prediction(proj, 18.0, True) is True
    assert sa_mod._compute_correct_prediction(proj, 22.0, True) is False


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _events_payload():
    return [{"id": "evt1", "home_team": "Boston Celtics", "away_team": "Miami Heat"}]


def _odds_payload(market, *, book_key="fanduel", book_title="FanDuel"):
    def outcome(desc, name, point):
        return {"description": desc, "name": name, "point": point, "price": -110}

    return {
        "bookmakers": [
            {
                "key": book_key,
                "title": book_title,
                "markets": [
                    {
                        "key": market,
                        "outcomes": [
                            outcome("Jayson Tatum", "Over", 27.5),
                            outcome("Jayson Tatum", "Under", 27.5),
                            outcome("Jaylen Brown", "Over", 24.5),
                            outcome("Jaylen Brown", "Under", 24.5),
                        ],
                    }
                ],
            }
        ]
    }


def test_event_and_odds_lookups_are_memoized_per_run(monkeypatch):
    """One HTTP call per sport-events and per (event, market), not per player."""
    fdl.clear_cache()
    monkeypatch.setattr(fdl.settings, "ODDS_API_KEY", "test-key", raising=False)
    calls: list[str] = []

    def fake_sync_get(
        url,
        *,
        params=None,
        headers=None,
        caller="sync",
        timeout=30,
        raise_for_status=True,
    ):
        calls.append(url)
        if url.endswith("/events"):
            return _FakeResp(_events_payload())
        return _FakeResp(_odds_payload(params["markets"]))

    monkeypatch.setattr(fdl, "sync_odds_get", fake_sync_get)

    # Resolving the same game twice (order swapped) hits /events once.
    assert (
        fdl.get_event_id_for_game("basketball_nba", "Boston Celtics", "Miami Heat")
        == "evt1"
    )
    assert (
        fdl.get_event_id_for_game("basketball_nba", "Miami Heat", "Boston Celtics")
        == "evt1"
    )
    assert sum(u.endswith("/events") for u in calls) == 1

    # Two players in the same (event, market) share one odds HTTP call.
    line_tatum = fdl.get_fanduel_line(
        "basketball_nba", "evt1", "Jayson Tatum", "player_points", 30.0
    )
    line_brown = fdl.get_fanduel_line(
        "basketball_nba", "evt1", "Jaylen Brown", "player_points", 20.0
    )
    assert sum(u.endswith("/odds") for u in calls) == 1
    # Projection above the line -> over; well below -> under.
    assert line_tatum[2] == "o"
    assert line_brown[2] == "u"

    # A different market is a distinct cache key -> exactly one more odds call.
    fdl.get_fanduel_line(
        "basketball_nba", "evt1", "Jayson Tatum", "player_rebounds", 8.0
    )
    assert sum(u.endswith("/odds") for u in calls) == 2

    fdl.clear_cache()


def test_get_event_id_for_game_normalizes_wnba_aliases(monkeypatch):
    fdl.clear_cache()
    monkeypatch.setattr(fdl.settings, "ODDS_API_KEY", "test-key", raising=False)

    def fake_sync_get(url, **kwargs):
        if url.endswith("/events"):
            return _FakeResp(
                [
                    {
                        "id": "evt-wnba",
                        "home_team": "Los Angeles Sparks",
                        "away_team": "Las Vegas Aces",
                    }
                ]
            )
        return _FakeResp({})

    monkeypatch.setattr(fdl, "sync_odds_get", fake_sync_get)
    assert (
        fdl.get_event_id_for_game(
            "basketball_wnba", "Los Angeles Sparks", "Las Vegas Aces"
        )
        == "evt-wnba"
    )
    assert (
        fdl.get_event_id_for_game("basketball_wnba", "LA Sparks", "Las Vegas Aces")
        == "evt-wnba"
    )
    fdl.clear_cache()


def test_get_fanduel_line_accepts_bookmaker_key_without_title(monkeypatch):
    fdl.clear_cache()
    monkeypatch.setattr(fdl.settings, "ODDS_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(
        fdl,
        "_get_event_market_odds",
        lambda *a, **k: _odds_payload("player_points", book_title=""),
    )
    line, _price, flag = fdl.get_fanduel_line(
        "basketball_nba", "evt1", "Jayson Tatum", "player_points", 30.0
    )
    assert line == 27.5
    assert flag == "o"
    fdl.clear_cache()


def test_clear_cache_forces_refetch(monkeypatch):
    fdl.clear_cache()
    monkeypatch.setattr(fdl.settings, "ODDS_API_KEY", "test-key", raising=False)
    calls: list[str] = []

    def fake_sync_get(
        url,
        *,
        params=None,
        headers=None,
        caller="sync",
        timeout=30,
        raise_for_status=True,
    ):
        calls.append(url)
        if url.endswith("/events"):
            return _FakeResp(_events_payload())
        return _FakeResp(_odds_payload(params["markets"]))

    monkeypatch.setattr(fdl, "sync_odds_get", fake_sync_get)

    fdl.get_fanduel_line(
        "basketball_nba", "evt1", "Jayson Tatum", "player_points", 30.0
    )
    fdl.clear_cache()
    fdl.get_fanduel_line(
        "basketball_nba", "evt1", "Jayson Tatum", "player_points", 30.0
    )
    assert sum(u.endswith("/odds") for u in calls) == 2

    fdl.clear_cache()
