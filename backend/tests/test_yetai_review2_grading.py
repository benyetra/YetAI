"""Round-2 review fixes for the grader, built on real ESPN payloads (see fixtures/espn)."""

import copy
import json
from datetime import date, datetime

import pytest

from app.services import espn_results as er
from app.services import yetai_grading as yg
from tests.test_espn_results import EVENT, GAMES, _load, espn  # noqa: F401
from tests.test_yetai_grading import bet, meta, row

# --- P1-2: every admin prop string vs real box scores -------------------------

# (league, admin pick text after "<player> over <line> ", player, value read off the box score)
ADMIN_PROPS = [
    ("NBA", "Points", "Kelly Oubre Jr.", 13),
    ("NBA", "Rebounds", "Kelly Oubre Jr.", 5),
    ("NBA", "Assists", "Kelly Oubre Jr.", 0),
    ("NBA", "3-Pointers Made", "Kelly Oubre Jr.", 1),
    ("NBA", "blocks", "Kelly Oubre Jr.", 3),
    ("NBA", "steals", "Kelly Oubre Jr.", 4),
    ("NBA", "turnovers", "Kelly Oubre Jr.", 3),
    ("NBA", "points rebounds assists", "Kelly Oubre Jr.", 18),
    ("NBA", "points rebounds", "Kelly Oubre Jr.", 18),
    ("NBA", "points assists", "Kelly Oubre Jr.", 13),
    ("NBA", "rebounds assists", "Kelly Oubre Jr.", 5),
    ("NBA", "blocks steals", "Kelly Oubre Jr.", 7),
    ("NFL", "Passing TDs", "Mac Jones", 2),
    ("NFL", "Passing Yards", "Mac Jones", 235),
    ("NFL", "pass completions", "Mac Jones", 19),
    ("NFL", "Rushing Yards", "Christian McCaffrey", 106),
    ("NFL", "Receptions", "Christian McCaffrey", 5),
    ("NFL", "Receiving Yards", "Christian McCaffrey", 67),
    ("NHL", "Points", "Tage Thompson", 5),
    ("NHL", "Assists", "Tage Thompson", 2),
    ("NHL", "Goals", "Tage Thompson", 3),
    ("NHL", "Shots on Goal", "Sammy Blais", 2),
    ("NHL", "goalie saves", "Jacob Fowler", 22),
    ("NHL", "blocked shots", "Noah Dobson", 4),
    ("MLB", "batter home runs", "Jack Suwinski", 1),
    ("MLB", "Home Runs", "Jack Suwinski", 1),
    ("MLB", "batter hits", "Pete Crow-Armstrong", 3),
    ("MLB", "Hits", "Pete Crow-Armstrong", 3),
    ("MLB", "batter rbis", "Jack Suwinski", 1),
    ("MLB", "Pitcher Strikeouts", "Braxton Ashcraft", 4),
    ("MLB", "pitcher outs", "Braxton Ashcraft", 15),
]
# Strings the admin UI can produce that no results source has a stat for (anytime td and
# batter total bases now grade: tests/test_yetai_yesno_totalbases.py): void with the reason named.
ADMIN_VOID = [
    ("NBA", "double double", "Unsupported: NBA player_prop double_double"),
]


def _admin(league, text, player, line, side="over"):
    _, day, home, away, *_ = GAMES[league]
    return row(
        league,
        "player_prop",
        f"{player} {side} {line} {text}",
        home,
        away,
        None,
        created_at=datetime(day.year, day.month, day.day, 12),
    )


@pytest.mark.parametrize("league,text,player,value", ADMIN_PROPS)
def test_admin_prop_strings_grade_from_the_box_score(espn, league, text, player, value):
    # "over -0.5" is not a pick anyone can write, so a zero stat skips the over case
    over = yg.grade_pick(_admin(league, text, player, max(value - 0.5, 0.5)))
    if value == 0:
        over = type(over)("won", "n/a")
    under = yg.grade_pick(_admin(league, text, player, value + 0.5, "under"))
    push = yg.grade_pick(_admin(league, text, player, value))
    assert (over.kind, under.kind, push.kind) == ("won", "won", "pushed"), over


@pytest.mark.parametrize("league,text,reason", ADMIN_VOID)
def test_admin_prop_strings_without_an_espn_stat_void_with_a_reason(
    espn, league, text, reason
):
    out = yg.grade_pick(_admin(league, text, "Mac Jones", 1.5))
    assert out.kind == "ungradeable" and out.result.startswith(reason), out


def test_every_prop_stat_is_gradeable_by_can_grade():
    for league, stats in er.PROP_STATS.items():
        assert all(yg.can_grade(league, "player_prop", s) for s in stats)
    assert yg.can_grade("MLB", "player_prop", "total_bases")  # MLB Stats API
    assert not yg.can_grade("MLB", "player_prop", "double_double")


# --- P1-1: a real Clippers game under the canonical name ------------------------


def test_clippers_canonical_name_grades_the_real_game(espn):
    espn.boards[("nba", "20261110")] = _load("nba_scoreboard_20261110.json")
    g = {
        "market": "moneyline",
        "league": "NBA",
        "game_date": "2026-11-10",
        "home_team": "Phoenix Suns",
        "away_team": "Los Angeles Clippers",
        "side": "away",
        "line": None,
    }
    out = yg.grade_pick(bet("NBA", "moneyline", g))
    assert out.kind == "lost" and "133" in out.result  # Suns 133, Clippers 110
    free = row(
        "NBA",
        "moneyline",
        "Los Angeles Clippers",
        "Phoenix Suns",
        "Los Angeles Clippers",
        datetime(2026, 11, 11, 2, 0),
    )
    assert yg.grade_pick(free).kind == "lost"


# --- P1-3: the real 2026-05-23 Cardinals @ Reds doubleheader ---------------------

G1_START, G2_START = datetime(2026, 5, 23, 17, 10), datetime(2026, 5, 23, 23, 15)


def _reds(espn, market="moneyline", side="home", line=None, selection="x", **kw):
    espn.boards[("mlb", "20260523")] = _load(
        "mlb_scoreboard_20260523_doubleheader.json"
    )
    g = {
        "market": market,
        "league": "MLB",
        "game_date": "2026-05-23",
        "home_team": "Cincinnati Reds",
        "away_team": "St. Louis Cardinals",
        "side": side,
        "line": line,
    }
    return bet("MLB", market, g, selection=selection, **kw)


def test_doubleheader_with_commence_time_uses_the_nearest_start(espn):
    assert yg.grade_pick(_reds(espn, commence_time=G1_START)).kind == "lost"  # 1-8
    assert yg.grade_pick(_reds(espn, commence_time=G2_START)).kind == "won"  # 7-6


def test_doubleheader_without_commence_time_never_guesses(espn):
    out = yg.grade_pick(_reds(espn))
    assert out.kind == "not_ready" and out.result.startswith("Doubleheader")
    assert out.result not in yg.WAITING  # so the settler voids it after the window


@pytest.mark.parametrize(
    "selection,want",
    [("Cincinnati Reds ML Game 2", "won"), ("Reds ML G1", "lost"), ("Reds G2", "won")],
)
def test_doubleheader_game_number_hint(espn, selection, want):
    assert yg.grade_pick(_reds(espn, selection=selection)).kind == want


def test_doubleheader_game_number_in_metadata(espn):
    b = _reds(espn)
    b.prediction_factors["grading"]["game_number"] = 2
    assert yg.grade_pick(b).kind == "won"


def test_doubleheader_with_the_same_result_in_both_games_grades(espn):
    # totals 9 and 13: over 7.5 wins both games
    assert (
        yg.grade_pick(_reds(espn, "total", "over", 7.5)).kind == "won"
    ), "same outcome either game"
    assert yg.grade_pick(_reds(espn, "total", "over", 11.5)).kind == "not_ready"


# --- P1-5: a malformed ESPN payload is retried, bad pick data is not ---------------


def _nba_total():
    return bet("NBA", "total", meta("NBA", "total", "over", 200.5))


def test_malformed_scoreboard_event_is_error_not_ungradeable(espn):
    board = copy.deepcopy(espn.boards[("nba", "20260111")])
    board["events"].insert(0, copy.deepcopy(board["events"][0]))
    del board["events"][0]["competitions"][0]["competitors"][0]["team"]
    espn.boards[("nba", "20260111")] = board
    out = yg.grade_pick(_nba_total())
    assert out.kind == "error" and out.result.startswith("ESPN payload"), out


def test_malformed_box_score_is_error(espn):
    summ = espn.summaries[EVENT["NBA"]]
    del summ["boxscore"]["players"][0]["statistics"][0]["athletes"][0]["athlete"]
    g = meta(
        "NBA", "player_prop", "over", 12.5, player="Kelly Oubre Jr.", stat="points"
    )
    out = yg.grade_pick(bet("NBA", "player_prop", g))
    assert out.kind == "error" and out.result.startswith("ESPN payload"), out


def test_bad_pick_metadata_still_voids_at_once(espn):
    g = {**meta("NBA", "total", "over", 200.5), "home_team": 7}
    assert yg.grade_pick(bet("NBA", "total", g)).kind == "ungradeable"


# --- P2-1: quarter-ball soccer lines -------------------------------------------------


@pytest.mark.parametrize(
    "market,side,line,kind",
    [
        ("spread", "home", -0.25, "ungradeable"),
        ("spread", "home", -0.75, "ungradeable"),
        ("total", "over", 2.75, "ungradeable"),
        ("spread", "home", -0.5, "won"),  # Brighton 3-0 Leeds
        ("spread", "home", -1.0, "won"),
        ("total", "over", 2.5, "won"),
    ],
)
def test_soccer_quarter_lines_are_not_graded_as_whole_results(
    espn, market, side, line, kind
):
    out = yg.grade_pick(bet("EPL", market, meta("EPL", market, side, line)))
    assert out.kind == kind, out


# --- P2-3: a known slate date does not wander to a neighbouring day -------------------


def test_metadata_slate_date_is_exact_but_free_text_may_be_a_day_off(espn):
    g = meta("NBA", "total", "over", 200.5)
    g["game_date"] = "2026-01-10"  # the game is on the 11th
    assert yg.grade_pick(bet("NBA", "total", g)).kind == "not_ready"
    text = row(
        "NBA",
        "total",
        "Over 200.5",
        "Toronto Raptors",
        "Philadelphia 76ers",
        None,
        created_at=datetime(2026, 1, 10, 12),
    )
    assert yg.grade_pick(text).kind == "won"  # 116 + 115
