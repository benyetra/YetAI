"""Offline tests for espn_results: `_get_json` is patched to serve trimmed real ESPN payloads."""

import copy
import json
from datetime import date, datetime
from pathlib import Path

import pytest

from app.services import espn_results as er

FIX = Path(__file__).parent / "fixtures" / "espn"


def _load(name):
    return json.loads((FIX / name).read_text())


# league -> (scoreboard file, game date, home, away, home score, away score, summary file)
GAMES = {
    "NBA": (
        "nba_scoreboard_20260111.json",
        date(2026, 1, 11),
        "Toronto Raptors",
        "Philadelphia 76ers",
        116,
        115,
        "nba_summary_401810405.json",
    ),
    "WNBA": (
        "wnba_scoreboard_20250810.json",
        date(2025, 8, 10),
        "New York Liberty",
        "Minnesota Lynx",
        71,
        83,
        "wnba_summary_401736310.json",
    ),
    "NFL": (
        "nfl_scoreboard_20251102.json",
        date(2025, 11, 2),
        "New York Giants",
        "San Francisco 49ers",
        24,
        34,
        "nfl_summary_401772767.json",
    ),
    "NHL": (
        "nhl_scoreboard_20260115.json",
        date(2026, 1, 15),
        "Buffalo Sabres",
        "Montreal Canadiens",
        5,
        3,
        "nhl_summary_401803091.json",
    ),
    "MLB": (
        "mlb_scoreboard_20250815.json",
        date(2025, 8, 15),
        "Chicago Cubs",
        "Pittsburgh Pirates",
        2,
        3,
        "mlb_summary_401696741.json",
    ),
    "NCAAF": (
        "ncaaf_scoreboard_20251101.json",
        date(2025, 11, 1),
        "Ohio State Buckeyes",
        "Penn State Nittany Lions",
        38,
        14,
        None,
    ),
    "NCAAB": (
        "ncaab_scoreboard_20260110.json",
        date(2026, 1, 10),
        "TCU Horned Frogs",
        "Arizona Wildcats",
        73,
        86,
        None,
    ),
    "EPL": (
        "epl_scoreboard_20251101.json",
        date(2025, 11, 1),
        "Brighton & Hove Albion",
        "Leeds United",
        3,
        0,
        None,
    ),
    "MLS": (
        "mls_scoreboard_20251101.json",
        date(2025, 11, 1),
        "Chicago Fire FC",
        "Philadelphia Union",
        0,
        3,
        None,
    ),
}


@pytest.fixture
def espn(monkeypatch):
    """Serve fixtures; `served` lists (url tail, params) for assertions. Unknown dates -> no events."""
    boards = {}  # (slug, yyyymmdd) -> payload
    summaries = {}  # event id -> payload
    for league, (sb, day, *_rest, summ) in GAMES.items():
        slug = er.LEAGUES[league][1]
        boards[(slug, day.strftime("%Y%m%d"))] = _load(sb)
        if summ:
            summaries[summ.split("_")[-1].removesuffix(".json")] = _load(summ)
    served = []

    def fake(url, params=None):
        served.append((url, params))
        params = params or {}
        if url.endswith("/summary"):
            return summaries[params["event"]]
        slug = url.split("/")[-2]
        if url.endswith("/teams"):  # college loose-match guard
            league = {"college-football": "NCAAF", "mens-college-basketball": "NCAAB"}[
                slug
            ]
            teams = json.loads((FIX / "college_teams.json").read_text())[league]
            return {"sports": [{"leagues": [{"teams": [{"team": t} for t in teams]}]}]}
        return boards.get((slug, params["dates"]), {"events": []})

    er.clear_cache()
    monkeypatch.setattr(er, "_get_json", fake)
    fake.boards, fake.summaries, fake.served = boards, summaries, served
    return fake


@pytest.mark.parametrize("league", GAMES)
def test_find_game_final_and_swap(espn, league):
    _, day, home, away, hs, as_, _ = GAMES[league]
    g = er.find_game(league, home, away, day)
    assert (g.state, g.home_score, g.away_score) == ("final", hs, as_)
    swapped = er.find_game(league, away, home, day)  # caller has home/away reversed
    assert (swapped.home_score, swapped.away_score) == (as_, hs)
    assert swapped.event_id == g.event_id


def test_college_and_soccer_params(espn):
    er.find_game("NCAAF", "Ohio State", "Penn State", date(2025, 11, 1))
    er.find_game("NCAAB", "TCU", "Arizona", date(2026, 1, 10))
    er.find_game("EPL", "Brighton", "Leeds", date(2025, 11, 1))
    by_slug = {u.split("/")[-2]: p for u, p in espn.served if p.get("dates")}
    groups = {
        p["groups"]
        for u, p in espn.served
        if "college-football" in u and p.get("dates")
    }
    assert groups == {"80", "81"}  # FBS + FCS
    assert by_slug["college-football"]["limit"] == "300"
    assert by_slug["mens-college-basketball"]["groups"] == "50"
    assert "eng.1" in by_slug


@pytest.mark.parametrize(
    "league,home,away",
    [
        ("NBA", "Toronto", "Philadelphia 76ers"),
        ("NBA", "Raptors", "76ers"),
        ("NBA", "TOR", "PHI"),
        ("NFL", "NY Giants", "San Francisco 49ers"),
        ("NFL", "Giants", "49ers"),
        ("NFL", "NYG", "SF"),
        ("MLB", "Cubs", "PIT"),
        ("EPL", "Brighton", "Leeds"),
        ("EPL", "Brighton and Hove Albion", "Leeds United"),
        ("NCAAB", "TCU", "ARIZ"),
    ],
)
def test_name_variants(espn, league, home, away):
    day = GAMES[league][1]
    g = er.find_game(league, home, away, day)
    assert g is not None and g.state == "final"


def test_no_match(espn):
    assert (
        er.find_game("NBA", "Boston Celtics", "Miami Heat", date(2026, 1, 11)) is None
    )
    assert er.find_game("XFL", "a", "b", date(2026, 1, 11)) is None


def test_neighbouring_day_fallback(espn):
    # NHL game starts 2026-01-16 00:00Z; callers may pass either slate date.
    for d in (date(2026, 1, 14), date(2026, 1, 16)):
        g = er.find_game("NHL", "Buffalo Sabres", "Montreal Canadiens", d)
        assert g and g.home_score == 5
    assert (
        er.find_game("NHL", "Buffalo Sabres", "Montreal Canadiens", date(2026, 1, 20))
        is None
    )


def test_doubleheader_picks_closest_start(espn):
    board = copy.deepcopy(espn.boards[("mlb", "20250815")])
    game2 = copy.deepcopy(board["events"][0])
    game2["id"] = "999"
    game2["date"] = "2025-08-15T23:20Z"
    for c in game2["competitions"][0]["competitors"]:
        c["score"] = "9"
    board["events"].append(game2)
    espn.boards[("mlb", "20250815")] = board
    args = ("MLB", "Chicago Cubs", "Pittsburgh Pirates", date(2025, 8, 15))
    assert (
        er.find_game(*args, commence_time=datetime(2025, 8, 15, 23, 10)).event_id
        == "999"
    )
    assert (
        er.find_game(*args, commence_time=datetime(2025, 8, 15, 18, 0)).event_id
        == "401696741"
    )
    assert er.find_game(*args) is None  # no commence_time: never guess a game
    assert [g.event_id for g in er.find_games(*args)] == ["401696741", "999"]


def test_postponed_real_event(espn):
    espn.boards[("mlb", "20250425")] = _load("mlb_postponed_scoreboard_20250425.json")
    g = er.find_game("MLB", "Detroit Tigers", "Baltimore Orioles", date(2025, 4, 25))
    assert g.state == "postponed"
    assert (
        er.find_game(
            "MLB", "Cleveland Guardians", "Boston Red Sox", date(2025, 4, 25)
        ).state
        == "postponed"
    )


@pytest.mark.parametrize(
    "name,completed,state,expected",
    [
        ("STATUS_FINAL", True, "post", "final"),
        ("STATUS_FINAL_OT", True, "post", "final"),
        ("STATUS_FULL_TIME", True, "post", "final"),
        ("STATUS_FINAL_PEN", True, "post", "final"),
        ("STATUS_POSTPONED", False, "post", "postponed"),
        ("STATUS_CANCELED", True, "post", "cancelled"),
        ("STATUS_ABANDONED", False, "post", "cancelled"),
        ("STATUS_FORFEIT", True, "post", "cancelled"),
        ("STATUS_IN_PROGRESS", False, "in", "in_progress"),
        ("STATUS_SCHEDULED", False, "pre", "scheduled"),
    ],
)
def test_state_mapping(name, completed, state, expected):
    assert er._state({"name": name, "completed": completed, "state": state}) == expected


def test_cancelled_via_find_game(espn):
    # ESPN has no cancelled event in the fixtures; edit a real one (see test_state_mapping for the names).
    board = copy.deepcopy(espn.boards[("nba", "20260111")])
    board["events"][0]["competitions"][0]["status"]["type"].update(
        name="STATUS_CANCELED", completed=False
    )
    espn.boards[("nba", "20260111")] = board
    assert (
        er.find_game(
            "NBA", "Toronto Raptors", "Philadelphia 76ers", date(2026, 1, 11)
        ).state
        == "cancelled"
    )


# (league, player, stat) -> value, all read off the real box scores in the fixtures
STAT_CASES = [
    ("NBA", "Kelly Oubre Jr.", "points", 13),
    ("NBA", "Kelly Oubre Jr.", "rebounds", 5),
    ("NBA", "Kelly Oubre Jr.", "assists", 0),
    ("NBA", "Kelly Oubre Jr.", "steals", 4),
    ("NBA", "Kelly Oubre Jr.", "blocks", 3),
    ("NBA", "Kelly Oubre Jr.", "threes", 1),
    ("NBA", "Kelly Oubre Jr.", "pra", 18),
    ("WNBA", "Alanna Smith", "points", 8),
    ("WNBA", "Alanna Smith", "rebounds", 9),
    ("WNBA", "Alanna Smith", "assists", 7),
    ("WNBA", "Alanna Smith", "steals", 4),
    ("WNBA", "Alanna Smith", "blocks", 3),
    ("WNBA", "Alanna Smith", "threes", 2),
    ("WNBA", "Alanna Smith", "pra", 24),
    ("NFL", "Mac Jones", "passing_yards", 235),
    ("NFL", "Christian McCaffrey", "rushing_yards", 106),
    ("NFL", "Christian McCaffrey", "receiving_yards", 67),
    ("NFL", "Mac Jones", "receiving_yards", 0),  # listed in passing/rushing only
    ("NHL", "Jacob Fowler", "saves", 22),
    ("NHL", "Sammy Blais", "shots_on_goal", 2),
    ("MLB", "Braxton Ashcraft", "strikeouts", 4),
    ("MLB", "Pete Crow-Armstrong", "hits", 3),
    ("MLB", "Jack Suwinski", "home_runs", 1),
    ("MLB", "Ronny Simon", "hits", 0),
    # admin-offered markets (values read off the box-score labels: TO, G, A, BS, RBI, IP)
    ("NBA", "Kelly Oubre Jr.", "turnovers", 3),
    ("NBA", "Kelly Oubre Jr.", "pr", 18),
    ("NBA", "Kelly Oubre Jr.", "pa", 13),
    ("NBA", "Kelly Oubre Jr.", "ra", 5),
    ("NBA", "Kelly Oubre Jr.", "blocks_steals", 7),
    ("WNBA", "Alanna Smith", "turnovers", 0),
    ("WNBA", "Alanna Smith", "pr", 17),
    ("WNBA", "Alanna Smith", "pa", 15),
    ("WNBA", "Alanna Smith", "ra", 16),
    ("WNBA", "Alanna Smith", "blocks_steals", 7),
    ("NFL", "Mac Jones", "passing_tds", 2),
    ("NFL", "Mac Jones", "pass_completions", 19),
    ("NFL", "Christian McCaffrey", "receptions", 5),
    ("NHL", "Tage Thompson", "goals", 3),
    ("NHL", "Tage Thompson", "assists", 2),
    ("NHL", "Tage Thompson", "points", 5),
    ("NHL", "Noah Dobson", "blocked_shots", 4),
    ("MLB", "Jack Suwinski", "rbis", 1),
    ("MLB", "Ronny Simon", "batter_strikeouts", 1),
    ("MLB", "Braxton Ashcraft", "pitcher_outs", 15),
    ("MLB", "Isaac Mattson", "pitcher_outs", 5),  # IP "1.2" = 5 outs
]
EVENT = {
    lg: g[6].split("_")[-1].removesuffix(".json") for lg, g in GAMES.items() if g[6]
}


def test_stat_cases_cover_every_prop_stat():
    # anytime_td has its own real-game cases: test_yetai_yesno_totalbases.py
    assert {(lg, st) for lg, _, st, _ in STAT_CASES} >= {
        (lg, st) for lg, s in er.PROP_STATS.items() for st in s if st != "anytime_td"
    }


@pytest.mark.parametrize("league,player,stat,expected", STAT_CASES)
def test_player_stat_ok(espn, league, player, stat, expected):
    r = er.player_stat(league, EVENT[league], player, stat)
    assert (r.status, r.value) == ("ok", expected)


def test_dnp_and_not_found(espn):
    ev = EVENT["NBA"]
    assert er.player_stat("NBA", ev, "Paul George", "points").status == "did_not_play"
    assert er.player_stat("NBA", ev, "Nobody Atall", "points").status == "not_found"
    assert (
        er.player_stat("NBA", ev, "Kelly Oubre", "touchdowns").status == "not_found"
    )  # unknown stat
    assert (
        er.player_stat("NBA", ev, "Kelly Oubre", "passing_yards").status == "not_found"
    )  # wrong league
    assert (
        er.player_stat("NHL", EVENT["NHL"], "Jacob Fowler", "shots_on_goal").status
        == "stat_unavailable"
    )  # goalie, no skater stats
    assert (
        er.player_stat("MLB", EVENT["MLB"], "Ronny Simon", "strikeouts").status
        == "stat_unavailable"
    )  # batter, not pitcher
    assert er.player_stat("EPL", "740686", "Anyone", "points").status == "not_found"


def test_zero_minutes_is_dnp(espn):
    summ = espn.summaries[EVENT["NBA"]]
    grp = summ["boxscore"]["players"][0]["statistics"][0]
    ath = next(
        a for a in grp["athletes"] if a["athlete"]["displayName"] == "Andre Drummond"
    )
    ath["stats"][grp["keys"].index("minutes")] = "0"
    assert (
        er.player_stat("NBA", EVENT["NBA"], "Andre Drummond", "points").status
        == "did_not_play"
    )


@pytest.mark.parametrize(
    "query",
    [
        "kelly oubre",
        "KELLY OUBRE JR",
        "Kelly Oubre Jr.",
        "Kélly Oubré III",
        "kelly  oubre, jr.",
    ],
)
def test_player_name_matching(espn, query):
    assert er.player_stat("NBA", EVENT["NBA"], query, "points").value == 13


def test_player_name_hyphen_and_period(espn):
    assert er.player_stat("MLB", EVENT["MLB"], "Pete Crow Armstrong", "hits").value == 3
    assert er.player_stat("MLB", EVENT["MLB"], "Isiah Kiner-Falefa", "hits").value == 1


def test_cache_and_http_errors(monkeypatch):
    er.clear_cache()
    calls = []

    class Resp:
        def __init__(self, code):
            self.code = code

        def raise_for_status(self):
            if self.code >= 400:
                raise er.requests.HTTPError("boom")

        def json(self):
            return {"ok": 1}

    codes = iter([200, 500])
    monkeypatch.setattr(
        er.requests,
        "get",
        lambda url, params=None, timeout=None: (
            calls.append(timeout),
            Resp(next(codes)),
        )[1],
    )
    assert er._get_json("u", {"a": 1, "b": 2}) == {"ok": 1}
    assert er._get_json("u", {"b": 2, "a": 1}) == {
        "ok": 1
    }  # cached regardless of param order
    assert calls == [10]
    with pytest.raises(er.requests.HTTPError):
        er._get_json("other")
    er.clear_cache()


# --- review fixes: both teams must match; exact before loose ---------------

REAL_BOARDS = {
    ("college-football", "20250913"): "ncaaf_scoreboard_20250913.json",
    ("college-football", "20251122"): "ncaaf_scoreboard_20251122.json",
    ("mens-college-basketball", "20251103"): "ncaab_scoreboard_20251103.json",
    ("mens-college-basketball", "20251119"): "ncaab_scoreboard_20251119.json",
    ("mens-college-basketball", "20251205"): "ncaab_scoreboard_20251205.json",
    ("nba", "20251031"): "nba_scoreboard_20251031.json",
    ("nfl", "20251109"): "nfl_scoreboard_20251109.json",
    ("nhl", "20251108"): "nhl_scoreboard_20251108.json",
    ("mlb", "20250516"): "mlb_scoreboard_20250516.json",
    ("mlb", "20250705"): "mlb_scoreboard_20250705.json",
    ("uefa.champions", "20250219"): "ucl_scoreboard_20250219.json",
}


@pytest.fixture
def real(espn):
    for key, name in REAL_BOARDS.items():
        espn.boards[key] = _load(name)
    espn.summaries["732195"] = _load("ucl_summary_732195.json")
    return espn


def _short(league, home, away, day, **kw):
    g = er.find_game(league, home, away, day, **kw)
    if g is None:
        return None
    for (_, d), name in REAL_BOARDS.items():
        for ev in _load(name)["events"]:
            if ev["id"] == g.event_id:
                return ev["shortName"]
    return g.event_id


# Real nickname collisions: the old matcher returned the first event listed.
@pytest.mark.parametrize(
    "league,home,away,day,want",
    [
        (
            "NCAAF",
            "Florida International Panthers",
            "Florida Atlantic Owls",
            date(2025, 9, 13),
            "FAU @ FIU",
        ),
        (
            "NCAAF",
            "Rice Owls",
            "Prairie View A&M Panthers",
            date(2025, 9, 13),
            "PV @ RICE",
        ),
        (
            "NCAAF",
            "Fresno State Bulldogs",
            "Utah State Aggies",
            date(2025, 11, 22),
            "USU @ FRES",
        ),
        (
            "NCAAF",
            "Texas A&M Aggies",
            "Samford Bulldogs",
            date(2025, 11, 22),
            "SAM @ TA&M",
        ),
        (
            "NCAAB",
            "Clemson Tigers",
            "New Hampshire Wildcats",
            date(2025, 11, 3),
            "UNH @ CLEM",
        ),
        (
            "NCAAB",
            "Auburn Tigers",
            "Bethune-Cookman Wildcats",
            date(2025, 11, 3),
            "BCU @ AUB",
        ),
        (
            "NCAAB",
            "Tennessee State Tigers",
            "Fisk Bulldogs",
            date(2025, 11, 3),
            "FISK @ TNST",
        ),
        (
            "NCAAB",
            "Gonzaga Bulldogs",
            "Texas Southern Tigers",
            date(2025, 11, 3),
            "TXSO @ GONZ",
        ),
        (
            "NCAAB",
            "East Texas A&M Lions",
            "Dallas Christian Crusaders",
            date(2025, 11, 19),
            "DCC @ ETAM",
        ),
        (
            "NCAAB",
            "SE Louisiana Lions",
            "William Carey Crusaders",
            date(2025, 11, 19),
            "WILC @ SELA",
        ),
        (
            "NCAAB",
            "Bethune-Cookman Wildcats",
            "South Carolina State Bulldogs",
            date(2025, 12, 5),
            "SCST @ BCU",
        ),
        (
            "NCAAB",
            "Kentucky Wildcats",
            "Gonzaga Bulldogs",
            date(2025, 12, 5),
            "GONZ VS UK",
        ),
    ],
)
def test_real_nickname_collisions_resolve_to_the_right_game(
    real, league, home, away, day, want
):
    assert _short(league, home, away, day) == want


def test_one_team_matching_is_never_enough(real):
    # FIU played that day, but not against Rice: no game.
    assert (
        er.find_game(
            "NCAAF", "Florida International Panthers", "Rice Owls", date(2025, 9, 13)
        )
        is None
    )
    # nickname-only inputs that fit two games are ambiguous
    assert er.find_game("NCAAF", "Panthers", "Owls", date(2025, 9, 13)) is None
    assert er.find_game("NCAAB", "Tigers", "Wildcats", date(2025, 11, 3)) is None


@pytest.mark.parametrize(
    "league,home,away,day,want",
    [
        ("NBA", "LA Clippers", "New Orleans Pelicans", date(2025, 10, 31), "NO @ LAC"),
        (
            "NBA",
            "Memphis Grizzlies",
            "Los Angeles Lakers",
            date(2025, 10, 31),
            "LAL @ MEM",
        ),
        ("NBA", "Clippers", "Pelicans", date(2025, 10, 31), "NO @ LAC"),
        ("NBA", "Los Angeles", "Memphis", date(2025, 10, 31), "LAL @ MEM"),
        ("NFL", "Chicago Bears", "New York Giants", date(2025, 11, 9), "NYG @ CHI"),
        ("NFL", "New York Jets", "Cleveland Browns", date(2025, 11, 9), "CLE @ NYJ"),
        ("NFL", "New York", "Cleveland", date(2025, 11, 9), "CLE @ NYJ"),
        ("NFL", "NY Giants", "Chicago", date(2025, 11, 9), "NYG @ CHI"),
        (
            "NHL",
            "New York Rangers",
            "New York Islanders",
            date(2025, 11, 8),
            "NYI @ NYR",
        ),
        ("NHL", "Rangers", "Islanders", date(2025, 11, 8), "NYI @ NYR"),
        ("MLB", "Chicago Cubs", "Chicago White Sox", date(2025, 5, 16), "CHW @ CHC"),
        ("MLB", "Chicago Cubs", "St. Louis Cardinals", date(2025, 7, 5), "STL @ CHC"),
        ("MLB", "Colorado Rockies", "Chicago White Sox", date(2025, 7, 5), "CHW @ COL"),
    ],
)
def test_same_city_pairs(real, league, home, away, day, want):
    assert _short(league, home, away, day) == want


def test_place_name_only_needs_a_disambiguating_opponent(real):
    # NYI @ NYR: both are "New York"; CHW @ CHC: both are "Chicago".
    assert er.find_game("NHL", "New York", "New York", date(2025, 11, 8)) is None
    assert er.find_game("MLB", "Chicago", "Chicago", date(2025, 5, 16)) is None
    # Lakers and Clippers both play: "Los Angeles" alone + LA opponent-free is ambiguous
    assert er.find_game("NBA", "Los Angeles", "LA", date(2025, 10, 31)) is None


def test_commence_time_must_be_within_12_hours(real):
    args = ("NFL", "Chicago Bears", "New York Giants", date(2025, 11, 9))
    assert er.find_game(*args, commence_time=datetime(2025, 11, 9, 18, 0))
    assert er.find_game(*args, commence_time=datetime(2025, 11, 10, 18, 0)) is None


def test_slate_day_then_previous_then_next(espn):
    nhl = espn.boards.pop(("nhl", "20260115"))
    espn.boards[("nhl", "20260114")] = nhl
    espn.boards[("nhl", "20260116")] = copy.deepcopy(nhl)
    espn.boards[("nhl", "20260116")]["events"][0]["id"] = "next-day"
    g = er.find_game("NHL", "Buffalo Sabres", "Montreal Canadiens", date(2026, 1, 15))
    assert g.event_id != "next-day"  # previous day wins over next day
    days = [p["dates"] for u, p in espn.served if "hockey" in u]
    assert days[:2] == ["20260115", "20260114"]


def test_soccer_after_extra_time_uses_regulation_score(real):
    # UCL 2025-02-19 PSV 3-1 Juventus a.e.t.; real linescores 0-0, 2-1, 1-0, 0-0 -> 2-1 at 90'
    g = er.find_game("UCL", "PSV Eindhoven", "Juventus", date(2025, 2, 19))
    assert (g.state, g.home_score, g.away_score) == ("final", 2, 1)
    assert "regulation" in g.detail
    swapped = er.find_game("UCL", "Juventus", "PSV Eindhoven", date(2025, 2, 19))
    assert (swapped.home_score, swapped.away_score) == (1, 2)
    # an ordinary full-time result is untouched and needs no summary call
    assert (
        er.find_game(
            "UCL", "Real Madrid", "Manchester City", date(2025, 2, 19)
        ).home_score
        == 3
    )


def test_soccer_extra_time_without_linescores_has_no_score(real):
    real.summaries["732195"] = {"header": {"competitions": [{"competitors": []}]}}
    g = er.find_game("UCL", "PSV Eindhoven", "Juventus", date(2025, 2, 19))
    assert g.home_score is None and g.away_score is None


@pytest.mark.parametrize(
    "raw,want",
    [
        ("-3", -3.0),
        ("3-5", 3.0),
        ("12", 12.0),
        ("-3.0", -3.0),
        ("--", None),
        ("", None),
    ],
)
def test_num_parses_signed_values(raw, want):
    assert er._num(raw) == want


def test_negative_rushing_yards_real_kittle(espn):
    # event 401772767: George Kittle 1 carry for -3 yards
    r = er.player_stat("NFL", EVENT["NFL"], "George Kittle", "rushing_yards")
    assert (r.status, r.value) == ("ok", -3.0)


def _add_namesake(espn, display, athlete_id, points):
    summ = espn.summaries[EVENT["NBA"]]
    grp = summ["boxscore"]["players"][1]["statistics"][0]
    src = next(a for a in grp["athletes"] if a.get("stats"))
    clone = copy.deepcopy(src)
    clone["athlete"].update(displayName=display, id=athlete_id)
    clone["stats"][grp["keys"].index("points")] = str(points)
    grp["athletes"].append(clone)


def test_suffix_namesakes_need_the_exact_name(espn):
    # Box score edited to hold "Michael Carter" and "Michael Carter II" (different players).
    _add_namesake(espn, "Michael Carter", "m1", 7)
    _add_namesake(espn, "Michael Carter II", "m2", 21)
    nba = lambda p: er.player_stat("NBA", EVENT["NBA"], p, "points")  # noqa: E731
    assert nba("Michael Carter").value == 7
    assert nba("Michael Carter II").value == 21
    assert nba("Michael Carter Jr.").status == "not_found"  # ambiguous: never guess


def test_single_player_still_matches_without_suffix(espn):
    assert er.player_stat("NBA", EVENT["NBA"], "Kelly Oubre", "points").value == 13


def test_renamed_franchise_matches_by_location_and_opponent():
    def team(loc, nick):
        return {"location": loc, "name": nick, "displayName": f"{loc} {nick}"}

    utah, blues = team("Utah", "Mammoth"), team("St. Louis", "Blues")
    assert not er._team_matches("Utah Hockey Club", utah)
    assert er._team_matches("Utah Hockey Club", utah, loose=True)
    assert not er._team_matches("Utah Hockey Club", blues, loose=True)
