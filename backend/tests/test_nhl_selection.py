"""NHL selection: who is projected, line matching, event matching, pregame refresh, preseason."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import (
    NHLGoalieActuals,
    NHLGoaliePredictions,
    NHLPlayer,
    NHLPlayerShotsActuals,
    NHLPlayerShotsPredictions,
    NHLTeamTotalsActuals,
    NHLTeamTotalsPredictions,
)
from app.services.etl.nhl import daily_predictions as dp
from app.services.etl.nhl import generate_daily_predictions as gdp
from app.services.nhl_accuracy_service import _nhl_rows

D = date(2026, 11, 13)
TABLES = [
    NHLGoalieActuals,
    NHLGoaliePredictions,
    NHLPlayer,
    NHLPlayerShotsActuals,
    NHLPlayerShotsPredictions,
    NHLTeamTotalsActuals,
    NHLTeamTotalsPredictions,
]


def _game(home, home_abbrev, away, away_abbrev, game_id=1, game_type=2):
    return {
        "id": game_id,
        "gameType": game_type,
        "startTimeUTC": "2030-01-01T23:00:00Z",
        "homeTeam": {"id": 23, "abbrev": home_abbrev, "placeName": {"default": home}},
        "awayTeam": {"id": 3, "abbrev": away_abbrev, "placeName": {"default": away}},
    }


@pytest.fixture
def session():
    eng = create_engine("sqlite://")
    for t in TABLES:
        t.__table__.create(eng)
    return sessionmaker(bind=eng)()


def _player(session, pid, name, team_id, gp, spg):
    session.add(
        NHLPlayer(
            player_id=pid,
            name=name,
            team_id=team_id,
            team_name="x",
            position="C",
            games_played=gp,
            shots_per_game=spg,
        )
    )


def _lines(**by_name):
    return {
        n: {"line": v, "over_odds": -110, "under_odds": -110}
        for n, v in by_name.items()
    }


class FakeClient:
    rosters: dict = {}

    def get_team_roster(self, abbrev):
        if self.rosters.get(abbrev) is None:
            raise RuntimeError("down")
        return {
            "forwards": [{"id": i} for i in self.rosters[abbrev]],
            "defensemen": [],
            "goalies": [],
        }


@pytest.fixture
def shots_run(monkeypatch, session):
    monkeypatch.setattr(dp, "db_session", session)
    monkeypatch.setattr(dp, "_pregame", lambda games: games)
    monkeypatch.setattr(dp, "NHLAPIClient", FakeClient)
    monkeypatch.setattr(
        dp,
        "predict_player_shots",
        lambda player_id, **kw: {
            "player_name": session.query(NHLPlayer)
            .filter_by(player_id=player_id)
            .one()
            .name,
            "predicted_shots": 3.0,
        },
    )
    monkeypatch.setattr(
        dp,
        "enrich_player_shots_prediction_for_write",
        lambda pred, shots_line, extra_features: {
            "predicted_shots": 3.0,
            "model_version": "t",
            "features_used": {},
        },
    )

    def go(lines):
        monkeypatch.setattr(
            gdp, "get_player_shots_odds_for_event", lambda *a, **k: lines
        )
        events = [
            {
                "id": "e",
                "away_team": "Vancouver Canucks",
                "home_team": "Montréal Canadiens",
            }
        ]
        dp.generate_player_predictions(
            [_game("Montréal", "MTL", "Vancouver", "VAN")], events
        )
        return {r.player_id: r for r in session.query(NHLPlayerShotsPredictions).all()}

    return go


def test_roster_and_sample_gate(shots_run, session):
    # 100 retired (off roster, high rate); 101 rostered with 3 GP; 102-107 top six;
    # 108 rostered, 6 GP, has a line but is outside the top six; 109 off-roster with a line.
    _player(session, 100, "Retired Guy", 23, 40, 9.0)
    _player(session, 101, "Rookie Three", 23, 3, 8.0)
    for i, pid in enumerate(range(102, 108)):
        _player(session, pid, f"Top {pid}", 23, 20, 5.0 - i * 0.1)
    _player(session, 108, "Depth Six", 23, 6, 1.0)
    _player(session, 109, "Traded Away", 23, 30, 0.5)
    session.commit()
    FakeClient.rosters = {"MTL": [101, *range(102, 109)], "VAN": [999]}
    got = shots_run(_lines(**{"Depth Six": 1.5, "Traded Away": 2.5}))
    assert set(got) == {*range(102, 109)}
    assert got[108].shots_line == 1.5 and got[102].shots_line is None


def test_roster_failure_skips_team(shots_run, session):
    _player(session, 102, "Top", 23, 20, 5.0)
    session.commit()
    FakeClient.rosters = {"MTL": None, "VAN": None}
    assert shots_run({}) == {}


def test_line_matching_by_accent_and_initial():
    lines = _lines(**{"Jack Hughes": 3.5, "Juraj Slafkovský": 2.5})
    assert dp.find_player_line(lines, "Juraj Slafkovsky")["line"] == 2.5
    assert dp.find_player_line(lines, None, "J. Hughes")["line"] == 3.5
    assert dp.find_player_line(lines, "Jack Hughes", "x")["line"] == 3.5
    assert dp.find_player_line(lines, "Quinn Hughes") == {}  # no initial clash
    assert (
        dp.find_player_line(_lines(**{"A Smith": 1, "B Smith": 2}), None, "C. Smith")
        == {}
    )


@pytest.mark.parametrize(
    "home,habbr,away,aabbr,ev_home,ev_away",
    [
        (
            "Montréal",
            "MTL",
            "Vancouver",
            "VAN",
            "Montréal Canadiens",
            "Vancouver Canucks",
        ),
        ("Montreal", "MTL", "Utah", "UTA", "Montréal Canadiens", "Utah Mammoth"),
        ("Utah", "UTA", "New York", "NYR", "Utah Mammoth", "New York Rangers"),
        ("New York", "NYI", "St. Louis", "STL", "New York Islanders", "St Louis Blues"),
    ],
)
def test_event_matching_every_team(home, habbr, away, aabbr, ev_home, ev_away):
    events = [{"id": "x", "away_team": ev_away, "home_team": ev_home}]
    assert dp.find_odds_event(events, home, habbr, away, aabbr)["id"] == "x"
    assert dp.find_odds_event(events[:0], home, habbr, away, aabbr) is None


def test_refresh_writes_three_markets_from_one_payload_per_event(monkeypatch, session):
    gdp.clear_nhl_event_odds_cache()
    monkeypatch.setattr(dp, "db_session", session)
    monkeypatch.setattr(dp, "_pregame", lambda games: games)
    monkeypatch.setattr(dp, "NHLAPIClient", FakeClient)
    FakeClient.rosters = {"MTL": [102], "VAN": [999]}
    _player(session, 102, "Juraj Slafkovský", 23, 20, 3.0)
    session.commit()
    payload = {
        "bookmakers": [
            {
                "key": "draftkings",
                "markets": [
                    {
                        "key": "player_shots_on_goal",
                        "outcomes": [
                            {
                                "name": "Over",
                                "description": "Juraj Slafkovsky",
                                "price": -110,
                                "point": 2.5,
                            },
                            {
                                "name": "Under",
                                "description": "Juraj Slafkovsky",
                                "price": -110,
                                "point": 2.5,
                            },
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -110, "point": 6.5},
                            {"name": "Under", "price": -110, "point": 6.5},
                        ],
                    },
                ],
            }
        ]
    }
    fetches = []

    def fake_get(url, **kw):
        fetches.append(kw["params"]["markets"])

        class R:
            status_code = 200

            def json(self):
                return payload

        return R()

    monkeypatch.setattr(gdp, "ODDS_API_KEY", "k")
    monkeypatch.setattr("app.services.odds_api_sync.sync_odds_get", fake_get)
    monkeypatch.setattr(
        dp,
        "predict_player_shots",
        lambda player_id, **kw: {
            "player_name": "Juraj Slafkovský",
            "predicted_shots": 3.0,
        },
    )
    monkeypatch.setattr(
        dp,
        "enrich_player_shots_prediction_for_write",
        lambda pred, shots_line, extra_features: {
            "predicted_shots": 3.0,
            "model_version": "t",
            "features_used": {},
        },
    )
    monkeypatch.setattr(
        dp,
        "predict_team_total_goals",
        lambda **kw: {
            "predicted_home_goals": 3.0,
            "predicted_away_goals": 3.5,
            "predicted_total_goals": 6.5,
            "suggested_ou_line": 6.5,
        },
    )
    monkeypatch.setattr(
        dp,
        "enrich_team_totals_prediction_for_write",
        lambda pred, draftkings_ou_line, extra_features: {
            "predicted_total_goals": 7.0,
            "model_version": "t",
            "features_used": {},
        },
    )
    monkeypatch.setattr(
        dp,
        "generate_goalie_predictions",
        lambda games, ev, **kw: len(
            [gdp.get_goalie_saves_odds_for_event("e", "h", "a", **kw)]
        ),
    )
    events = [
        {"id": "e", "away_team": "Vancouver Canucks", "home_team": "Montréal Canadiens"}
    ]
    sched = {
        "gameWeek": [
            {
                "games": [
                    dict(
                        _game("Montréal", "MTL", "Vancouver", "VAN"),
                        gameState="FUT",
                        startTimeUTC="2026-11-13T23:00:00Z",
                    )
                ]
            }
        ]
    }
    from datetime import datetime

    with (
        patch.object(dp, "now_eastern") as now,
        patch.object(dp.NHLAPIClient, "get_schedule", create=True, return_value=sched),
        patch.object(dp, "get_nhl_events_from_odds_api", return_value=events),
        patch("app.services.etl.nhl._db.init_session"),
        patch("app.services.etl.nhl._db.close_session"),
    ):
        now.return_value.date.return_value = D
        out = dp.run_goalie_refresh()
    assert fetches == [gdp._NHL_EVENT_ODDS_MARKETS]  # one call, all three markets
    assert out["player_predictions"] == 1 and out["team_totals_predictions"] == 1
    shot = session.query(NHLPlayerShotsPredictions).one()
    assert shot.shots_line == 2.5
    assert session.query(NHLTeamTotalsPredictions).one().draftkings_ou_line == 6.5


def test_preseason_game_not_written():
    games = [
        _game("A", "AAA", "B", "BBB", game_type=1),
        _game("C", "CCC", "D", "DDD", game_id=2, game_type=2),
    ]
    assert [g["id"] for g in dp._pregame(games)] == [2]


def test_preseason_rows_not_graded(session):
    pre, reg = 2026010005, 2026020005
    session.add_all(
        [
            NHLPlayerShotsPredictions(
                game_date=D,
                player_id=1,
                player_name="a",
                team_name="t",
                opponent_team_name="o",
                predicted_shots=3,
                shots_line=2.5,
                betting_recommendation="OVER 2.5",
            ),
            NHLPlayerShotsPredictions(
                game_date=D,
                player_id=2,
                player_name="b",
                team_name="t",
                opponent_team_name="o",
                predicted_shots=3,
                shots_line=2.5,
                betting_recommendation="OVER 2.5",
            ),
            NHLPlayerShotsActuals(
                game_id=pre,
                game_date=D,
                player_id=1,
                player_name="a",
                team_name="t",
                actual_shots=4,
            ),
            NHLPlayerShotsActuals(
                game_id=reg,
                game_date=D,
                player_id=2,
                player_name="b",
                team_name="t",
                actual_shots=4,
            ),
            NHLTeamTotalsPredictions(
                game_date=D,
                home_team_id=1,
                home_team_name="h",
                away_team_id=2,
                away_team_name="a",
                predicted_home_goals=3,
                predicted_away_goals=3,
                predicted_total_goals=6,
                suggested_ou_line=6,
                draftkings_ou_line=5.5,
                confidence=1,
                betting_recommendation="OVER 5.5",
            ),
            NHLTeamTotalsActuals(
                game_id=pre,
                game_date=D,
                home_team_id=1,
                home_team_name="h",
                away_team_id=2,
                away_team_name="a",
                actual_home_goals=3,
                actual_away_goals=3,
                actual_total_goals=6,
            ),
            NHLGoaliePredictions(
                game_date=D,
                game_id=pre,
                goalie_id=7,
                goalie_name="g",
                team_id=1,
                team_name="t",
                opponent_team_id=2,
                opponent_team_name="o",
                is_home=True,
                predicted_saves=25,
                predicted_shots_against=27,
                predicted_save_pct=0.9,
                confidence=1,
                saves_line=24.5,
                betting_recommendation="OVER 24.5",
            ),
            NHLGoalieActuals(
                game_id=pre,
                game_date=D,
                goalie_id=7,
                goalie_name="g",
                team_name="t",
                opponent_team_name="o",
                actual_saves=26,
                actual_shots_against=28,
                actual_save_pct=0.93,
                actual_goals_against=2,
            ),
        ]
    )
    session.commit()
    rows = _nhl_rows(session, start=D, end=D)
    assert [r["actual_shots"] for r in rows["player_shots"]] == [4]
    assert rows["team_totals"] == [] and rows["goalie"] == []
