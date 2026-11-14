"""NHL collectors read the CURRENT season: no cap, no preseason, shrunk rates."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.predictions_models import (
    NHLGameStats,
    NHLGoalie,
    NHLGoalieActuals,
    NHLPlayer,
    NHLTeamStats,
)
from app.services.etl.nhl import _config as cfg
from app.services.etl.nhl import collect_historical_data as chd
from app.services.etl.nhl import nhl_api_client as api

SEASON = 20262027
PRIOR = 20252026
TODAY = date(2026, 11, 14)
NYR, NYI = 3, 2


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            m.__table__
            for m in (
                NHLGameStats,
                NHLGoalie,
                NHLGoalieActuals,
                NHLPlayer,
                NHLTeamStats,
            )
        ],
    )
    session = sessionmaker(bind=engine)()
    monkeypatch.setattr(chd, "db_session", session)
    monkeypatch.setattr(cfg, "db_session", session)
    monkeypatch.setattr(chd.time, "sleep", lambda *_: None)
    monkeypatch.setattr(chd, "now_eastern", lambda: datetime(2026, 11, 14, 12))
    yield session
    session.close()


def _game(db, gid, season, gtype, day, home, away, hs, as_, hsog, asog, state="OFF"):
    db.add(
        NHLGameStats(
            game_id=gid,
            season=season,
            game_type=gtype,
            game_date=day,
            game_state=state,
            home_team_id=home,
            home_team_name=f"T{home}",
            away_team_id=away,
            away_team_name=f"T{away}",
            home_score=hs,
            away_score=as_,
            home_sog=hsog,
            away_sog=asog,
        )
    )


# --- team stats --------------------------------------------------------------


def test_team_stats_current_season_regular_season_only_and_shrunk(db):
    _game(db, 2026020001, SEASON, 2, date(2026, 10, 10), NYR, NYI, 4, 2, 30, 20)
    _game(db, 2026020002, SEASON, 2, date(2026, 10, 12), NYI, NYR, 3, 1, 28, 24)
    # preseason, FINAL: ignored; last season's game: only feeds the NYR prior
    _game(db, 2026010005, SEASON, 1, date(2026, 9, 25), NYR, NYI, 10, 0, 50, 5, "FINAL")
    _game(db, 2025020009, PRIOR, 2, date(2026, 1, 5), NYR, 9, 2, 1, 25, 35, "OFF")
    db.add(NHLTeamStats(team_id=59, team_name="Utah Hockey Club", games_played=82))
    stale = db.query(NHLTeamStats).filter_by(team_id=59).one()
    stale.goals_for_per_game = 9.9
    stale.last_10_shots_for_per_game = 40.0
    db.commit()

    chd.calculate_team_stats(SEASON)

    rows = {t.team_id: t for t in db.query(NHLTeamStats).all()}
    nyr, nyi = rows[NYR], rows[NYI]
    assert (nyr.games_played, nyi.games_played) == (2, 2)
    assert (nyr.wins, nyr.losses, nyi.wins, nyi.losses) == (1, 1, 1, 1)
    assert (nyr.goals_for, nyr.goals_against) == (5, 5)
    assert (nyr.shots_for, nyr.shots_against) == (54, 48)
    assert (nyi.shots_for, nyi.shots_against) == (48, 54)
    # League level: this season's 4 team-games (gf 10, sf 102) shrunk toward last
    # season's per-team-game mean (gf 1.5, sf 30) by LEAGUE_PRIOR_TEAM_GAMES.
    k, lk = chd.TEAM_PRIOR_GAMES, chd.LEAGUE_PRIOR_TEAM_GAMES
    lg_g = (10 + lk * 1.5) / (4 + lk)
    lg_s = (102 + lk * 30) / (4 + lk)
    # NYR prior = its last-season rates (gf 2, ga 1, sf 25, sa 35) scaled to that level.
    assert nyr.goals_for_per_game == pytest.approx((5 + k * 2 * lg_g / 1.5) / (2 + k))
    assert nyr.goals_against_per_game == pytest.approx(
        (5 + k * 1 * lg_g / 1.5) / (2 + k)
    )
    assert nyr.shots_for_per_game == pytest.approx((54 + k * 25 * lg_s / 30) / (2 + k))
    assert nyr.shots_against_per_game == pytest.approx(
        (48 + k * 35 * lg_s / 30) / (2 + k)
    )
    # NYI has no last season: prior = the league level
    assert nyi.goals_for_per_game == pytest.approx((5 + k * lg_g) / (2 + k))
    assert nyi.shots_for_per_game == pytest.approx((48 + k * lg_s) / (2 + k))
    # last_10 stay raw, shooting pct comes from current games
    assert nyr.last_10_goals_for_per_game == pytest.approx(2.5)
    assert nyr.shooting_pct == pytest.approx(5 / 54)
    # stale team: 0 games, no rates
    s = rows[59]
    assert s.games_played == 0 and s.goals_for == 0
    assert s.goals_for_per_game is None and s.last_10_shots_for_per_game is None
    assert s.shooting_pct is None


def test_league_average_ignores_teams_without_current_games(db):
    db.add(
        NHLTeamStats(team_id=1, team_name="a", games_played=5, shots_for_per_game=30)
    )
    db.add(
        NHLTeamStats(team_id=2, team_name="b", games_played=0, shots_for_per_game=99)
    )
    db.add(
        NHLTeamStats(team_id=3, team_name="c", games_played=None, shots_for_per_game=99)
    )
    db.commit()
    assert cfg.get_league_avg_shots_for() == 30


# --- game collection ---------------------------------------------------------


def _boxscore(game_id, gtype=2):
    def side(tid, goalie):
        return {
            "id": tid,
            "placeName": {"default": f"T{tid}"},
            "score": 3,
            "sog": 30,
        }, {
            "goalies": [
                {
                    "playerId": goalie,
                    "name": {"default": f"G{goalie}"},
                    "starter": True,
                    "saves": 27,
                    "shotsAgainst": 30,
                    "savePctg": 0.9,
                    "goalsAgainst": 3,
                    "toi": "60:00",
                    "decision": "W",
                }
            ],
            "forwards": [],
            "defense": [],
        }

    home, home_players = side(NYR, 111)
    away, away_players = side(NYI, 222)
    return {
        "id": game_id,
        "season": SEASON,
        "gameType": gtype,
        "gameDate": "2026-10-10",
        "gameState": "OFF",
        "homeTeam": home,
        "awayTeam": away,
        "venue": {"default": "MSG"},
        "playerByGameStats": {"homeTeam": home_players, "awayTeam": away_players},
    }


class FakeClient:
    boxscore_calls: list = []

    def get_team_schedule(self, abbrev, season):
        if abbrev != "NYR":
            return {"games": []}
        games = [
            {"id": 2026020000 + i, "gameType": 2, "gameState": "OFF"}
            for i in range(1, 26)
        ]
        games.append({"id": 2026010005, "gameType": 1, "gameState": "FINAL"})
        games.append({"id": 2026020099, "gameType": 2, "gameState": "FUT"})
        games.append({"id": 2026030111, "gameType": 3, "gameState": "FINAL"})
        return {"games": games}

    def get_game_boxscore(self, game_id):
        FakeClient.boxscore_calls.append(game_id)
        return _boxscore(game_id, gtype=3 if game_id // 10000 % 100 == 3 else 2)


def test_collect_game_data_no_cap_incremental_skips_preseason(db, monkeypatch):
    monkeypatch.setattr(chd, "NHLAPIClient", FakeClient)
    FakeClient.boxscore_calls = []
    # the goalie actuals collector already wrote one of these rows
    db.add(
        NHLGoalieActuals(
            game_id=2026020001,
            game_date=date(2026, 10, 10),
            goalie_id=111,
            goalie_name="G111",
            team_name="T3",
            opponent_team_name="T2",
            actual_saves=27,
            actual_shots_against=30,
            actual_save_pct=0.9,
            actual_goals_against=3,
        )
    )
    db.commit()

    assert chd.collect_game_data(season=SEASON) == 26  # 25 regular + 1 playoff
    assert db.query(NHLGameStats).count() == 26
    assert 2026010005 not in FakeClient.boxscore_calls
    assert 2026020099 not in FakeClient.boxscore_calls
    assert (
        db.query(NHLGoalieActuals).filter_by(game_id=2026020001, goalie_id=111).count()
        == 1
    )
    assert db.query(NHLGoalieActuals).count() == 26 * 2

    FakeClient.boxscore_calls = []
    assert chd.collect_game_data(season=SEASON) == 0
    assert FakeClient.boxscore_calls == []


# --- skaters -----------------------------------------------------------------


def test_skater_url_asks_for_all_rows(monkeypatch):
    seen = []

    class Resp:
        status_code = 200

        def json(self):
            return {"data": [], "total": 0}

    monkeypatch.setattr(
        api.requests, "get", lambda url, timeout: seen.append(url) or Resp()
    )
    api.NHLAPIClient().get_skater_stats(SEASON)
    assert "limit=-1" in seen[0] and f"seasonId={SEASON}" in seen[0]


def _skater(pid, abbrev, pos, gp, shots):
    return {
        "playerId": pid,
        "skaterFullName": f"P{pid}",
        "teamAbbrevs": abbrev,
        "positionCode": pos,
        "gamesPlayed": gp,
        "goals": 1,
        "assists": 2,
        "points": 3,
        "shots": shots,
        "timeOnIcePerGame": 1000.0,
    }


class SkaterClient:
    def get_skater_stats(self, season):
        if season == SEASON:
            rows = [
                _skater(1, "NYR", "C", 2, 10),
                _skater(2, "NYI", "D", 4, 4),
                _skater(3, "NYI", "D", 4, 8),
                _skater(4, "TOR,UTA", "L", 1, 0),
            ]
        else:
            assert season == PRIOR
            rows = [_skater(1, "NYR", "C", 80, 240), _skater(2, "NYI", "D", 5, 50)]
        return {"data": rows, "total": len(rows)}


def test_skaters_shrunk_raw_fields_missing_zeroed_uta_68(db, monkeypatch):
    monkeypatch.setattr(chd, "NHLAPIClient", SkaterClient)
    db.add(
        NHLPlayer(
            player_id=99,
            name="Gone",
            team_id=3,
            team_name="x",
            position="C",
            games_played=50,
            shots=200,
            shots_per_game=4.0,
        )
    )
    db.commit()

    chd.collect_season_player_stats(SEASON)

    p = {x.player_id: x for x in db.query(NHLPlayer).all()}
    assert (p[1].games_played, p[1].shots, p[1].goals, p[1].points) == (2, 10, 1, 3)
    assert p[1].shots_per_game == pytest.approx((10 + 10 * 3.0) / 12)  # prior 240/80
    # prior season < 10 games: league D mean this season = 12/8 = 1.5
    assert p[2].shots_per_game == pytest.approx((4 + 10 * 1.5) / 14)
    assert p[3].shots_per_game == pytest.approx((8 + 10 * 1.5) / 14)
    assert p[99].games_played == 0 and p[99].shots_per_game == 0
    assert (p[4].team_id, p[4].team_name) == (68, "Utah Mammoth")


# --- goalies -----------------------------------------------------------------


def _actual(db, gid, day, goalie, saves, shots, decision="W", team="T3"):
    db.add(
        NHLGoalieActuals(
            game_id=gid,
            game_date=day,
            goalie_id=goalie,
            goalie_name=f"G{goalie}",
            team_name=team,
            opponent_team_name="T2",
            actual_saves=saves,
            actual_shots_against=shots,
            actual_save_pct=saves / shots,
            actual_goals_against=shots - saves,
            decision=decision,
        )
    )


def test_goalie_stats_current_season_only_and_shrunk(db):
    for i in range(10):  # last regular season: 290/320 = 0.90625
        _actual(db, 2025020000 + i + 1, date(2026, 1, 1) + timedelta(i), 1, 29, 32)
    for i in range(10):  # a season before that: must not count anywhere
        _actual(db, 2024020000 + i + 1, date(2025, 1, 1) + timedelta(i), 1, 20, 40)
    _actual(db, 2026010009, date(2026, 9, 20), 1, 5, 5)  # preseason: not counted
    _actual(db, 2026020010, date(2026, 11, 12), 1, 27, 30, "W")
    _actual(db, 2026020020, date(2026, 11, 13), 1, 27, 30, "L")
    _actual(db, 2026020021, date(2026, 11, 13), 2, 20, 20, "W", team="T2")
    _actual(db, 2025020050, date(2026, 3, 1), 3, 28, 30)  # no current game
    db.add(
        NHLGameStats(
            game_id=2026020020,
            season=SEASON,
            game_type=2,
            game_date=date(2026, 11, 13),
            game_state="OFF",
            home_team_id=NYR,
            home_team_name="New York",
            away_team_id=NYI,
            away_team_name="New York",
            home_goalie_id=1,
            away_goalie_id=2,
        )
    )
    # A goalie row with no stored game at all (stale numbers from an old build)
    db.add(NHLGoalie(player_id=4, name="G4", team_id=9, team_name="T9", games_played=2))
    db.commit()

    chd.calculate_goalie_stats(SEASON)

    g = {x.player_id: x for x in db.query(NHLGoalie).all()}
    assert g[4].games_played == 0 and g[4].save_pct is None
    g1 = g[1]
    assert g1.games_played == 2 and (g1.wins, g1.losses) == (1, 1)
    assert (g1.saves, g1.shots_against) == (54, 60)
    assert g1.save_pct == pytest.approx((54 + 300 * 290 / 320) / 360)
    assert g1.last_game_date == date(2026, 11, 13)
    assert (g1.last_game_saves, g1.last_game_shots) == (27, 30)
    assert g1.games_in_last_7_days == 2
    assert (g1.team_id, g1.team_name) == (NYR, "New York")
    assert g1.last_5_games_played == 2 and g1.last_5_save_pct == pytest.approx(0.9)
    # no prior season for G2: league pooled sv = (54 + 20) / 80
    assert g[2].save_pct == pytest.approx((20 + 300 * 74 / 80) / 320)
    assert g[2].team_id == NYI
    # G3 only has last season: kept row, no current look
    assert g[3].games_played == 0 and g[3].save_pct is None
    assert g[3].last_game_date == date(2026, 3, 1)
