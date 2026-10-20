"""NBA season rollover: calendar, offseason filtering, career fallback,
defense window, roster safety."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import (
    PlayerCareerData,
    RecentGames,
    TeamDefenseStats,
)
from app.services.etl.nba import _season
from app.services.etl.nba import update_recent_games as urg
from app.services.etl.nba import update_team_defense_stats as utds
from app.services.etl.nba import update_team_roster as utr
from app.services.etl.nba.generate_no_steals import _career_row_for


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    for model in (RecentGames, PlayerCareerData, TeamDefenseStats):
        model.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


# --- calendar -----------------------------------------------------------


def test_season_labels():
    assert _season.season_start_year(date(2026, 10, 20)) == 2026
    assert _season.season_start_year(date(2027, 4, 1)) == 2026
    assert _season.season_label(2026) == "2026-27"
    assert _season.api_basketball_season(date(2026, 10, 21)) == "2026-2027"
    assert _season.api_basketball_season(date(2027, 2, 1)) == "2026-2027"


def test_regular_season_start_known_and_estimated():
    assert _season.regular_season_start(2026) == date(2026, 10, 20)
    # Every known opener matches the Tuesday-on-or-after-Oct-18 estimate.
    for year, opener in _season.REGULAR_SEASON_START.items():
        assert _season._estimated_regular_season_start(year) == opener
    assert _season.regular_season_start(2027) == date(2027, 10, 19)


@pytest.mark.parametrize(
    "d, offseason",
    [
        (date(2026, 6, 20), False),  # Finals
        (date(2026, 7, 12), True),  # Summer League
        (date(2026, 10, 15), True),  # preseason
        (date(2026, 10, 19), True),
        (date(2026, 10, 20), False),  # opening night
        (date(2027, 1, 10), False),
    ],
)
def test_is_offseason_date(d, offseason):
    assert _season.is_offseason_date(d) is offseason


# --- update_recent_games ------------------------------------------------


def test_process_day_skips_offseason_without_calling_api():
    with patch.object(urg, "api_request") as api:
        assert urg._process_day(date(2026, 10, 10)) == (0, 0)
    api.assert_not_called()


def test_is_nba_league_game():
    assert urg.is_nba_league_game({"league": "standard"})
    assert urg.is_nba_league_game({})  # field absent → keep
    assert not urg.is_nba_league_game({"league": "vegas"})
    assert not urg.is_nba_league_game({"league": "africa"})


def test_process_day_drops_summer_league_games(monkeypatch):
    calls = []

    def fake_api(endpoint, params=None):
        calls.append(endpoint)
        if endpoint == "games":
            return {"response": [{"id": 1, "league": "vegas", "teams": {}}]}
        raise AssertionError("box score fetched for a non-NBA game")

    monkeypatch.setattr(urg, "api_request", fake_api)
    monkeypatch.setattr(urg, "SessionLocal", MagicMock)
    assert urg._process_day(date(2026, 11, 1)) == (0, 0)
    assert calls == ["games"]


def test_stat_line_fields_maps_home_and_opponent():
    line = {"team": {"id": 17}, "points": 30, "min": "36", "totReb": 9}
    fields = urg.stat_line_fields(line, home_api_id=17, away_api_id=2)
    assert fields["home_game"] is True
    assert fields["opponent_team_id"] == 1610612738  # Celtics
    assert fields["points"] == 30 and fields["rebounds"] == 9


# --- generate_no_steals career fallback ----------------------------------


def _career(pid, season, steals):
    return PlayerCareerData(
        player_id=pid,
        season=season,
        steals=steals,
        minutes=100.0,
        last_updated=datetime(2026, 10, 1),
    )


def _game(pid, d):
    return RecentGames(player_id=pid, game_date=d, opponent_team_id=1, minutes=30)


def test_career_row_falls_back_to_last_season_early(db):
    opener = date(2026, 10, 20)
    db.add_all([_career(1, "2026-27", 1.0), _career(1, "2025-26", 90.0)])
    db.add_all(_game(1, opener + timedelta(days=i)) for i in range(2))
    db.commit()
    row = _career_row_for(db, 1, "2026-27", "2025-26", opener, date(2026, 10, 25))
    assert row.season == "2025-26"


def test_career_row_uses_current_season_after_sample(db):
    opener = date(2026, 10, 20)
    db.add_all([_career(1, "2026-27", 1.0), _career(1, "2025-26", 90.0)])
    db.add_all(_game(1, opener + timedelta(days=2 * i)) for i in range(6))
    db.commit()
    row = _career_row_for(db, 1, "2026-27", "2025-26", opener, date(2026, 11, 5))
    assert row.season == "2026-27"


def test_career_row_uses_whatever_exists(db):
    opener = date(2026, 10, 20)
    db.add(_career(2, "2026-27", 1.0))
    db.add(_career(3, "2025-26", 1.0))
    db.commit()
    today = date(2026, 10, 21)
    assert _career_row_for(db, 2, "2026-27", "2025-26", opener, today).season == (
        "2026-27"
    )
    assert _career_row_for(db, 3, "2026-27", "2025-26", opener, today).season == (
        "2025-26"
    )
    assert _career_row_for(db, 4, "2026-27", "2025-26", opener, today) is None


# --- team defense window ----------------------------------------------------


def test_defense_stats_use_last_n_games_across_seasons(db, monkeypatch):
    celtics = 1610612738
    # 30 games last season (10 pts each), one game this season (40 pts).
    last_season = [date(2026, 1, 1) + timedelta(days=i) for i in range(30)]
    for d in last_season:
        db.add(
            RecentGames(player_id=5, game_date=d, opponent_team_id=celtics, points=10)
        )
    db.add(
        RecentGames(
            player_id=5,
            game_date=date(2026, 10, 21),
            opponent_team_id=celtics,
            points=40,
        )
    )
    db.commit()

    monkeypatch.setattr(utds, "SessionLocal", lambda: db)
    monkeypatch.setattr(utds, "NBA_TEAM_NAMES", {celtics: "Boston Celtics"})
    monkeypatch.setattr(
        utds, "now_eastern", lambda: datetime(2026, 10, 22, 4, 0, tzinfo=utds.EASTERN)
    )
    db.close = lambda: None
    result = utds.run()

    assert result["teams_updated"] == 1
    row = db.query(TeamDefenseStats).filter_by(team_id=celtics).one()
    # 25-game window = 1 game at 40 + 24 games at 10 → 11.2, not 40.
    assert row.points_allowed_per_game == pytest.approx((40 + 24 * 10) / 25, abs=0.1)


# --- update_team_roster -------------------------------------------------------


@pytest.fixture
def fake_resolver(monkeypatch):
    ids = {"luka doncic": 1629029, "austin reaves": 1630559, "lebron james": 2544}

    def resolve(name, static_players=None, api_sports_id=None):
        key = utr.normalize_player_name(name)
        if key in ids:
            return ids[key]
        return 900_000_000 + api_sports_id if api_sports_id else None

    monkeypatch.setattr(utr, "resolve_nba_player_id", resolve)


LAL, DAL, CLE = 1610612747, 1610612742, 1610612739


def _espn(**extra):
    rosters = {1610612700 + i: [f"Filler {i}"] for i in range(30)}
    rosters.update(extra)
    return rosters


def test_merge_espn_overrides_stale_team_and_dedupes_trades(fake_resolver):
    api_players = [
        (DAL, "Luka Dončić", 10, "G"),  # stale: ESPN has him on the Lakers
        (LAL, "Austin Reaves", 11, "G"),
        (CLE, "Austin Reaves", 11, "G"),  # listed twice
        (LAL, "Rookie Guy", 12, "F"),
    ]
    espn = _espn(**{str(LAL): []})
    espn[LAL] = ["Luka Doncic", "Austin Reaves", "LeBron James"]
    entries, stats = utr.merge_rosters(api_players, espn)
    by_id = {e.player_id: e for e in entries}

    assert by_id[1629029].team_id == LAL
    assert by_id[1630559].team_id == LAL
    assert by_id[900_000_012].team_id == LAL  # rookie kept via synthetic id
    assert by_id[2544].team_id == LAL  # ESPN-only, real NBA.com id
    assert stats["espn_used"] and stats["espn_team_overrides"] == 1
    assert stats["espn_only_added"] == 1 and stats["synthetic_ids"] == 1


def test_merge_ignores_partial_espn(fake_resolver):
    entries, stats = utr.merge_rosters(
        [(DAL, "Luka Doncic", 10, "G")], {LAL: ["Luka Doncic"]}
    )
    assert not stats["espn_used"]
    assert entries[0].team_id == DAL


def test_run_keeps_existing_roster_when_incomplete(monkeypatch, fake_resolver):
    monkeypatch.setattr(
        utr,
        "_fetch_api_sports_players",
        lambda season: ([(LAL, "Luka Doncic", 1, "G")], 1, 0),
    )
    monkeypatch.setattr(utr, "fetch_team_rosters", lambda: {})
    session = MagicMock()
    monkeypatch.setattr(utr, "SessionLocal", lambda: session)
    result = utr.run()
    assert result["status"] == "error" and result["reason"] == "incomplete_roster"
    session.query.assert_not_called()


# --- update_player_career_data._find_api_player_id ---------------------------


def test_find_api_player_id_searches_last_name_first(monkeypatch):
    from app.services.etl.nba import update_player_career_data as upcd

    db = {
        "Gilgeous-Alexander": [
            {"id": 1, "firstname": "Shai", "lastname": "Gilgeous-Alexander"}
        ],
        # The old first-name-first search hit Cole Anthony and gave up.
        "Anthony": [{"id": 9, "firstname": "Cole", "lastname": "Anthony"}],
        "Davis": [{"id": 2, "firstname": "Anthony", "lastname": "Davis"}],
        "Jaquez": [{"id": 4, "firstname": "Jaime", "lastname": "Jaquez Jr."}],
    }
    calls = []

    def fake_api(endpoint, params=None):
        calls.append(params["search"])
        return {"response": db.get(params["search"], [])}

    monkeypatch.setattr(upcd, "api_request", fake_api)
    assert upcd._find_api_player_id("Shai Gilgeous-Alexander") == 1
    assert upcd._find_api_player_id("Anthony Davis") == 2
    assert upcd._find_api_player_id("Jaime Jaquez Jr.") == 4
    calls.clear()
    assert upcd._find_api_player_id("Nobody Here") is None
    assert calls == ["Here", "nobody"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("--", None),
        ("", None),
        (None, None),
        ("31", 31.0),
        ("32:30", 32.5),
        ("42.1", 42.1),
        ("+5", 5.0),
        (7, 7.0),
    ],
)
def test_stat_values_are_numeric_or_none(raw, expected):
    assert urg._num(raw) == expected


def test_stat_line_fields_handles_dnp_placeholders():
    line = {"team": {"id": 17}, "min": "--", "points": "--", "fgp": "--"}
    fields = urg.stat_line_fields(line, home_api_id=17, away_api_id=2)
    assert fields["minutes"] is None and fields["points"] is None
    assert fields["fg_percentage"] is None


def test_merge_expands_abbreviated_api_sports_names(monkeypatch):
    flagg = 1642843
    ids = {"cooper flagg": flagg}

    def resolve(name, static_players=None, api_sports_id=None):
        key = utr.normalize_player_name(name)
        if key in ids:
            return ids[key]
        return 900_000_000 + api_sports_id if api_sports_id else None

    monkeypatch.setattr(utr, "resolve_nba_player_id", resolve)
    espn = _espn()
    espn[DAL] = ["Cooper Flagg", "Chaney Johnson"]
    entries, stats = utr.merge_rosters(
        [(DAL, "C. Flagg", 10, "F"), (DAL, "C. Johnson", 11, "F")], espn
    )
    by_name = {e.player_name: e.player_id for e in entries}
    # One Cooper Flagg under his real id, no duplicate synthetic "C. Flagg".
    assert by_name["Cooper Flagg"] == flagg
    assert "C. Flagg" not in by_name
    assert by_name["Chaney Johnson"] == 900_000_011
    assert stats["espn_only_added"] == 0


def test_process_day_expands_box_score_names_from_roster(monkeypatch):
    class FakeQuery:
        def __init__(self, rows):
            self.rows = rows

        def __iter__(self):
            return iter(self.rows)

        def filter_by(self, **kw):
            return self

        def first(self):
            return None

    added = []

    class FakeDB:
        def query(self, *cols):
            if cols and cols[0] is RecentGames:
                return FakeQuery([])
            return FakeQuery([(1610612742, "Cooper Flagg")])

        def add(self, row):
            added.append(row)

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    def fake_api(endpoint, params=None):
        if endpoint == "games":
            return {
                "response": [
                    {
                        "id": 1,
                        "league": "standard",
                        "teams": {"home": {"id": 8}, "visitors": {"id": 2}},
                    }
                ]
            }
        return {
            "response": [
                {
                    "player": {"id": 55, "firstname": "C.", "lastname": "Flagg"},
                    "team": {"id": 8},
                    "min": "34",
                    "points": 22,
                }
            ]
        }

    monkeypatch.setattr(urg, "api_request", fake_api)
    monkeypatch.setattr(urg, "SessionLocal", FakeDB)
    monkeypatch.setattr(urg.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        urg,
        "resolve_nba_player_id",
        lambda name, api_sports_id=None: (
            1642843 if name == "Cooper Flagg" else 900_000_000 + api_sports_id
        ),
    )
    assert urg._process_day(date(2026, 11, 1)) == (1, 0)
    assert added[0].player_id == 1642843
