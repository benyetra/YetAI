"""Every team name our own tables can produce resolves to exactly one real ESPN team."""

import json
from datetime import date
from pathlib import Path

import pytest

from app.services import espn_results as er

FIX = Path(__file__).parent / "fixtures" / "espn"


def _teams(league: str) -> list[dict]:
    return json.loads((FIX / f"{league}_teams.json").read_text())


def _resolve(name: str, teams: list[dict]) -> list[str]:
    """Teams the name matches the way find_game does: exact pass, else loose pass."""
    for loose in (False, "strong", True):
        hits = [t["displayName"] for t in teams if er._team_matches(name, t, loose)]
        if hits:
            return hits
    return []


def _names() -> list[tuple[str, str, str]]:
    from app.services.etl.mlb._enrichment_helpers import MLB_STATSAPI_TO_ODDS_TEAM
    from app.services.etl.nba._espn import NBA_TEAM_NAMES
    from app.services.etl.nba.update_game_lines import TEAM_NAME_FIX
    from app.services.etl.nfl import team_names as nfl
    from app.services.etl.nhl.collect_historical_data import NHL_TEAMS
    from app.services.etl.wnba._team_id_map import ODDS_API_NAME_ALIAS, WNBA_ID_TO_NAME

    rows = []
    rows += [("nba", n, "NBA_TEAM_NAMES") for n in NBA_TEAM_NAMES.values()]
    rows += [
        ("nba", n, "TEAM_NAME_FIX") for n in (*TEAM_NAME_FIX, *TEAM_NAME_FIX.values())
    ]
    # what normalize_team_name produces for every alias/abbreviation (the grader never sees "LAS")
    rows += [
        ("nfl", nfl.normalize_team_name(n), f"nfl alias {n}")
        for n in nfl._ALIAS_TO_CANONICAL
    ]
    rows += [("nfl", n, "nfl names") for n in nfl._CANONICAL_NAMES]
    rows += [("nhl", t["name"], "NHL_TEAMS") for t in NHL_TEAMS.values()]
    rows += [("wnba", n, "WNBA names") for n in WNBA_ID_TO_NAME.values()]
    rows += [("wnba", n, "WNBA alias") for n in ODDS_API_NAME_ALIAS]
    rows += [("mlb", n, "mlb odds") for n in MLB_STATSAPI_TO_ODDS_TEAM.values()]
    # Odds API spellings that differ from ESPN's displayName
    rows += [("nhl", n, "odds api") for n in ("Montréal Canadiens", "St Louis Blues")]
    rows += [("nhl", "Utah Hockey Club", "renamed franchise")]
    rows += [("mlb", n, "odds api") for n in ("Oakland Athletics", "Athletics")]
    rows += [("nba", "Los Angeles Clippers", "odds api")]
    return rows


# Our own tables carry a few names ESPN's /teams list cannot know about.
NOT_IN_ESPN = {
    ("wnba", "Connecticut Sun"),  # absent from ESPN's 2026 WNBA team list
}


@pytest.mark.parametrize("league,name,source", _names())
def test_table_name_resolves_to_one_espn_team(league, name, source):
    if (league, name) in NOT_IN_ESPN:
        pytest.skip("not in saved ESPN list")
    hits = _resolve(name, _teams(league))
    assert len(hits) == 1, f"{source}: {name!r} -> {hits}"


# Odds API / canonical spellings against real scoreboards (find_game works per event, so
# the opponent pins the game even where a nickname alone is shared by many colleges).
# (league, day, home, away, ESPN event name)
REAL_DAYS = [
    (
        "NBA",
        "2026-11-10",
        "Phoenix Suns",
        "Los Angeles Clippers",
        "LA Clippers at Phoenix Suns",
    ),
    (
        "NHL",
        "2026-11-12",
        "Utah Hockey Club",
        "St Louis Blues",
        "St. Louis Blues at Utah Mammoth",
    ),
    (
        "NHL",
        "2026-11-12",
        "Boston Bruins",
        "Montréal Canadiens",
        "Montreal Canadiens at Boston Bruins",
    ),
    (
        "NCAAF",
        "2026-11-05",
        "Southern Mississippi Golden Eagles",
        "James Madison Dukes",
        "James Madison Dukes at Southern Miss Golden Eagles",
    ),
    (
        "NCAAF",
        "2026-11-07",
        "Connecticut Huskies",
        "North Carolina Tar Heels",
        "North Carolina Tar Heels at UConn Huskies",
    ),
    (
        "NCAAB",
        "2026-11-09",
        "Connecticut Huskies",
        "Wagner Seahawks",
        "Wagner Seahawks at UConn Huskies",
    ),
    (
        "NCAAB",
        "2026-11-10",
        "Mississippi Rebels",
        "Southeastern Louisiana Lions",
        "SE Louisiana Lions at Ole Miss Rebels",
    ),
    (
        "MLB",
        "2026-09-01",
        "Texas Rangers",
        "Oakland Athletics",
        "Athletics Athletics at Texas Rangers",
    ),
]


@pytest.mark.parametrize("league,day,home,away,event", REAL_DAYS)
def test_real_scoreboard_resolves_odds_api_names(
    monkeypatch, league, day, home, away, event
):
    stamp = day.replace("-", "")
    board = json.loads((FIX / f"{league.lower()}_scoreboard_{stamp}.json").read_text())
    ids = {e["name"]: e["id"] for e in board["events"]}
    college = json.loads((FIX / "college_teams.json").read_text())

    def fake(url, params=None):
        if url.endswith("/teams"):
            teams = college[league]
            return {"sports": [{"leagues": [{"teams": [{"team": t} for t in teams]}]}]}
        return board

    er.clear_cache()
    monkeypatch.setattr(er, "_get_json", fake)
    got = er.find_game(league, home, away, date.fromisoformat(day), exact_day=True)
    assert got is not None and got.event_id == ids[event]
