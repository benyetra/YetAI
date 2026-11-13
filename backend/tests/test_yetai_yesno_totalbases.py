"""Anytime TD (NFL/NCAAF) and MLB batter total bases, graded from trimmed real payloads.

ESPN: tests/fixtures/espn/*_td_*.json. MLB Stats API: tests/fixtures/mlb_statsapi/ (box scores
trimmed to the batting lines; total bases checked by hand, see the comments).
"""

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from app.services import espn_results as er
from app.services import mlb_results
from app.services import yetai_grading as yg
from tests.test_yetai_grading import bet, row

FIX = Path(__file__).parent / "fixtures"


def _load(rel):
    return json.loads((FIX / rel).read_text())


BOARDS = {
    ("nfl", "20251102"): _load("espn/nfl_td_scoreboard_20251102.json"),
    ("nfl", "20251116"): _load("espn/nfl_td_scoreboard_20251116.json"),
    ("college-football", "20251101"): _load("espn/ncaaf_td_scoreboard_20251101.json"),
    ("mlb", "20250815"): _load("espn/mlb_scoreboard_20250815.json"),
    ("mlb", "20260523"): _load("espn/mlb_scoreboard_20260523_doubleheader.json"),
}
SUMMARIES = {
    i: _load(f"espn/nfl_td_summary_{i}.json")
    for i in ("401772764", "401772765", "401772774")
}
SUMMARIES["401752887"] = _load("espn/ncaaf_td_summary_401752887.json")
SCHEDULES = {
    d: _load(f"mlb_statsapi/schedule_{d}.json") for d in ("20250815", "20260523")
}
ROSTERS = {t: _load(f"espn/nfl_td_roster_401772765_{t}.json") for t in ("3", "4")}
ATHLETES = _load("espn/nfl_td_athletes.json")
REVIEW = _load("espn/td_review_events.json")  # real games from the round-4 review
for _id, _r in REVIEW.items():
    BOARDS[(_r["slug"], _r["day"])] = {"events": [_r["event"]]}
    SUMMARIES[_id] = _r["summary"]
BOXES = {}
DH = _load("mlb_statsapi/dh_review.json")  # 4 real 2026 traditional doubleheaders
for _d, _r in DH.items():
    BOARDS[("mlb", _d.replace("-", ""))] = {"events": _r["espn"]}
    SCHEDULES[_d.replace("-", "")] = {"dates": [{"games": _r["schedule"]}]}
    BOXES.update(_r["boxes"])
BOXES.update(
    {
        i: _load(f"mlb_statsapi/boxscore_{i}.json")
        for i in ("776737", "824518", "824516")
    }
)


@pytest.fixture(autouse=True)
def served(monkeypatch):
    def fake(url, params=None):
        params = params or {}
        if "statsapi.mlb.com" in url:
            if url.endswith("/schedule"):
                return SCHEDULES[params["date"].replace("-", "")]
            return BOXES[url.split("/")[-2]]
        if "core.api.espn.com" in url:
            if url.endswith("/roster"):
                assert "/events/401772765/" in url
                return ROSTERS[url.split("/")[-2]]
            return ATHLETES[url]
        if url.endswith("/summary"):
            return SUMMARIES[params["event"]]
        return BOARDS.get((url.split("/")[-2], params["dates"]), {"events": []})

    er.clear_cache()
    monkeypatch.setattr(er, "_get_json", fake)


# --- anytime TD ---------------------------------------------------------------------

CHI_CIN = ("2025-11-02", "Cincinnati Bengals", "Chicago Bears")
LAC_TEN = ("2025-11-02", "Tennessee Titans", "Los Angeles Chargers")
CIN_PIT = ("2025-11-16", "Pittsburgh Steelers", "Cincinnati Bengals")
IND_MD = ("2025-11-01", "Maryland Terrapins", "Indiana Hoosiers")


def _td(league, game, player, side="yes"):
    day, home, away = game
    g = {
        "market": "player_prop",
        "league": league,
        "game_date": day,
        "home_team": home,
        "away_team": away,
        "side": side,
        "line": None,
        "player": player,
        "stat": "anytime_td",
    }
    return yg.grade_pick(bet(league, "player_prop", g))


# (league, game, player, TDs counted: read off the box score and scoringPlays by hand)
TD_CASES = [
    ("NFL", CHI_CIN, "Brittain Brown", 1),  # rushing TD
    ("NFL", LAC_TEN, "Quentin Johnston", 1),  # receiving TD
    ("NFL", CIN_PIT, "Kenny Gainwell", 2),  # two receiving TDs
    ("NFL", CHI_CIN, "Charlie Jones", 1),  # kickoff return TD
    ("NFL", LAC_TEN, "Chimere Dike", 1),  # punt return TD
    ("NFL", LAC_TEN, "Cody Barton", 1),  # interception return: not counted twice
    ("NFL", CIN_PIT, "James Pierre", 1),  # fumble return TD
    ("NFL", LAC_TEN, "Justin Herbert", 1),  # 2 passing TDs do not count, 1 rush does
    ("NFL", CHI_CIN, "Joe Flacco", 0),  # 4 passing TDs only
    ("NFL", CHI_CIN, "Chase Brown", 0),  # active, carries, no TD
    ("NCAAF", IND_MD, "Fernando Mendoza", 1),  # 1 pass TD thrown, 1 rushing TD
    ("NCAAF", IND_MD, "Devan Boykin", 1),  # fumble return TD
    ("NCAAF", IND_MD, "Omar Cooper Jr.", 1),
    ("NCAAF", IND_MD, "Malik Washington", 0),  # passing TD only
]


@pytest.mark.parametrize("league,game,player,n", TD_CASES)
def test_anytime_td_counts_every_sportsbook_touchdown(league, game, player, n):
    yes, no = _td(league, game, player), _td(league, game, player, "no")
    assert (yes.kind, no.kind) == (("won", "lost") if n else ("lost", "won")), yes
    assert f"({n} TD)" in yes.result


# Bears @ Bengals roster (ESPN core API): `valid` and not `didNotPlay` = dressed.
def test_anytime_td_active_player_with_no_touches_is_lost_not_void():
    for player in (
        "Drew Sample",
        "Durham Smythe",
    ):  # TEs on the gameday squad, no stat line
        yes, no = _td("NFL", CHI_CIN, player), _td("NFL", CHI_CIN, player, "no")
        assert (yes.kind, no.kind) == ("lost", "won"), yes
        assert "(0 TD)" in yes.result


def test_anytime_td_game_day_inactive_is_void():
    for player in ("Joe Burrow", "Trey Hendrickson"):  # valid false / didNotPlay true
        out = _td("NFL", CHI_CIN, player)
        assert (out.kind, out.result) == ("void", f"DNP: {player}"), out
        assert _td("NFL", CHI_CIN, player, "no").kind == "void"


def test_anytime_td_player_on_neither_roster_is_not_graded_lost():
    out = _td(
        "NFL", CHI_CIN, "Malik Muhammad II"
    )  # a scratch ESPN does not list at all
    assert (
        out.kind == "not_ready" and "not in box score" in out.result
    )  # voided by settler
    assert _td("NFL", CHI_CIN, "Nobody Atall").kind == "not_ready"


def test_anytime_td_roster_transport_error_is_retried(monkeypatch):
    import requests

    real = er._get_json

    def boom(url, params=None):
        if "core.api" in url:
            raise requests.ConnectionError("down")
        return real(url, params)

    monkeypatch.setattr(er, "_get_json", boom)
    assert _td("NFL", CHI_CIN, "Drew Sample").kind == "error"
    assert (
        _td("NFL", CHI_CIN, "Brittain Brown").kind == "won"
    )  # box score: no roster call


def test_anytime_td_ncaaf_absent_player_stays_not_ready():
    # ESPN's college roster `valid` flag is false for players who have box-score lines
    out = _td("NCAAF", IND_MD, "Nobody Atall")
    assert out.kind == "not_ready"


def test_anytime_td_side_defaults_to_yes_and_line_is_ignored():
    day, home, away = CHI_CIN
    g = {
        "market": "player_prop",
        "league": "NFL",
        "game_date": day,
        "home_team": home,
        "away_team": away,
        "line": 0.5,
        "player": "Brittain Brown",
        "stat": "anytime_td",
    }
    assert yg.grade_pick(bet("NFL", "player_prop", g)).kind == "won"


@pytest.mark.parametrize(
    "text,player,side",
    [
        ("Brittain Brown Anytime TD", "Brittain Brown", "yes"),
        ("Brittain Brown anytime touchdown Yes", "Brittain Brown", "yes"),
        ("Brittain Brown - Anytime TD - No", "Brittain Brown", "no"),
        ("No Brittain Brown anytime td", "Brittain Brown", "no"),
        ("Brittain Brown to score a touchdown", "Brittain Brown", "yes"),
        ("Brittain Brown ATD (anytime)", "Brittain Brown", "yes"),
        ("Anytime TD Scorer: Brittain Brown", "Brittain Brown", "yes"),
    ],
)
def test_anytime_td_admin_free_text(text, player, side):
    spec = yg._parse_anytime_td(text)
    assert (spec["player"], spec["side"], spec["stat"]) == (player, side, "anytime_td")
    r = row(
        "NFL", "player_prop", text, CHI_CIN[1], CHI_CIN[2], datetime(2025, 11, 2, 18)
    )
    assert yg.grade_pick(r).kind == ("lost" if side == "no" else "won")


def test_anytime_td_gate_and_neighbouring_markets():
    assert yg.can_grade("NFL", "player_prop", "anytime_td")
    assert yg.can_grade("NCAAF", "player_prop", "anytime_td")
    assert yg.can_grade("College Football", "player_prop", "anytime_td")
    assert not yg.can_grade("NBA", "player_prop", "anytime_td")
    assert yg.unsupported_market("Player Anytime TD") is None
    assert yg.unsupported_market("Player anytime goal scorer") == "anytime"
    assert yg.unsupported_market("Player 1st half anytime TD") == "1st half"
    r = row(
        "MLB",
        "player_prop",
        "Brittain Brown anytime TD",
        "A",
        "B",
        datetime(2025, 11, 2),
    )
    assert yg.grade_pick(r).kind == "ungradeable"


# --- MLB total bases ------------------------------------------------------------------

CUBS = ("2025-08-15", "Chicago Cubs", "Pittsburgh Pirates")
REDS = ("2026-05-23", "Cincinnati Reds", "St. Louis Cardinals")
G1, G2 = datetime(2026, 5, 23, 17, 10), datetime(2026, 5, 23, 23, 15)


def _tb(game, player, side, line, commence_time=None, selection="x"):
    day, home, away = game
    g = {
        "market": "player_prop",
        "league": "MLB",
        "game_date": day,
        "home_team": home,
        "away_team": away,
        "side": side,
        "line": line,
        "player": player,
        "stat": "total_bases",
    }
    return yg.grade_pick(
        bet("MLB", "player_prop", g, commence_time=commence_time, selection=selection)
    )


# TB = singles + 2*2B + 3*3B + 4*HR, by hand from hits/2B/3B/HR in the box score
@pytest.mark.parametrize(
    "game,player,tb",
    [
        (CUBS, "Pete Crow-Armstrong", 4),  # 3 H, one 2B: 1 + 2 + 1
        (CUBS, "Jack Suwinski", 4),  # 1 H, a HR
        (CUBS, "Seiya Suzuki", 2),  # 1 H, a 2B
        (CUBS, "Ian Happ", 0),  # 0-for-3
    ],
)
def test_total_bases_over_under_and_push(game, player, tb):
    assert _tb(game, player, "over", tb - 0.5).kind == "won"
    assert _tb(game, player, "under", tb + 0.5).kind == "won"
    assert _tb(game, player, "over", float(tb)).kind == "pushed"
    assert _tb(game, player, "over", tb + 0.5).kind == "lost"
    assert "total bases" in _tb(game, player, "under", tb + 0.5).result


def test_total_bases_player_who_did_not_play_is_void():
    out = _tb(CUBS, "Willi Castro", "over", 0.5)  # bench, no plate appearance
    assert (out.kind, out.result) == ("void", "DNP: Willi Castro")
    assert _tb(CUBS, "Cade Horton", "over", 0.5).kind == "void"  # pitcher, did not bat


def test_total_bases_player_not_in_the_box_score_is_retried():
    out = _tb(CUBS, "Nobody Atall", "over", 0.5)
    assert out.kind == "not_ready" and "not in box score" in out.result


def test_total_bases_doubleheader():
    # Jordan Walker: game 1 1 H + HR = 4; game 2 3 H (2B, HR, 1B) = 7
    assert _tb(REDS, "Jordan Walker", "over", 5.5, G1).kind == "lost"
    assert _tb(REDS, "Jordan Walker", "over", 5.5, G2).kind == "won"
    out = _tb(REDS, "Jordan Walker", "over", 5.5)
    assert out.kind == "not_ready" and out.result.startswith("Doubleheader")
    assert (
        _tb(REDS, "Jordan Walker", "over", 5.5, selection="Walker O5.5 TB G2").kind
        == "won"
    )
    assert _tb(REDS, "Jordan Walker", "over", 3.5).kind == "won"  # both games clear it
    # Ivan Herrera: game 1 two hits incl. a triple = 4
    assert _tb(REDS, "Iván Herrera", "over", 3.5, G1).kind == "won"


def test_total_bases_admin_free_text_and_gate():
    assert yg.can_grade("MLB", "player_prop", "total_bases")
    assert not yg.can_grade("NFL", "player_prop", "total_bases")
    r = row(
        "MLB",
        "player_prop",
        "Pete Crow-Armstrong over 3.5 batter total bases",
        CUBS[1],
        CUBS[2],
        datetime(2025, 8, 15, 18, 20),
    )
    assert yg.grade_pick(r).kind == "won"
    r.selection = "Pete Crow-Armstrong over 4.5 total bases"
    assert yg.grade_pick(r).kind == "lost"


def test_total_bases_transport_error_is_retried(monkeypatch):
    import requests

    real = er._get_json

    def boom(url, params=None):
        if "statsapi" in url:
            raise requests.ConnectionError("down")
        return real(url, params)

    monkeypatch.setattr(er, "_get_json", boom)
    out = _tb(CUBS, "Pete Crow-Armstrong", "over", 0.5)
    assert out.kind == "error"


def test_total_bases_unknown_game_in_schedule_is_retried(monkeypatch):
    monkeypatch.setitem(SCHEDULES, "20250815", {"dates": []})
    assert _tb(CUBS, "Pete Crow-Armstrong", "over", 0.5).kind == "not_ready"


def test_total_bases_malformed_schedule_is_error_not_ungradeable(monkeypatch):
    monkeypatch.setitem(SCHEDULES, "20250815", {"oops": 1})
    assert _tb(CUBS, "Pete Crow-Armstrong", "over", 0.5).kind == "error"


def test_find_game_pk_matches_teams_and_start():
    day = date(2025, 8, 15)
    game = er.find_games("MLB", CUBS[1], CUBS[2], day)[0]
    assert mlb_results.find_game_pk(game, day) == 776737


# --- round 4: scoring plays are the cross-check ------------------------------------------


def _rgame(event_id):
    r = REVIEW[event_id]
    c = {
        x["homeAway"]: x["team"]["displayName"]
        for x in r["event"]["competitions"][0]["competitors"]
    }
    d = r["day"]
    return f"{d[:4]}-{d[4:6]}-{d[6:]}", c["home"], c["away"]


# TDs ESPN leaves out of the box-score TD columns (all real; text of the scoring play quoted)
MISSED_TD_CASES = [
    (
        "NFL",
        "401772903",
        "Woody Marks",
        1,
    ),  # "...Aborted Snap ... Woody Marks 1 Yd Fumble Recovery"
    (
        "NFL",
        "401772818",
        "Marshawn Kneeland",
        1,
    ),  # "Blocked Punt Recovery in End Zone", no stat line
    ("NFL", "401873024", "James Mitchell", 1),  # "0 Yd Fumble Recovery"
    ("NCAAF", "401871076", "Aidan Singleton", 1),  # "0 Yd Fumble Return"
    (
        "NCAAF",
        "401871096",
        "Xayvion Turner-Bradshaw",
        1,
    ),  # "100 Yd Return of Blocked Field Goal"
    # counted correctly before, still must be
    ("NFL", "401772903", "Nico Collins", 2),  # receiving TDs
    ("NFL", "401772818", "Trey McBride", 1),
    ("NCAAF", "401871096", "Brandon Crutchfield", 1),  # interception return
    ("NFL", "401772847", "Marcus Jones", 1),  # return TD: not shown as 2
]


@pytest.mark.parametrize("league,event,player,n", MISSED_TD_CASES)
def test_td_scorer_is_never_graded_lost(league, event, player, n):
    yes = _td(league, _rgame(event), player)
    no = _td(league, _rgame(event), player, "no")
    assert (yes.kind, no.kind) == ("won", "lost"), (yes, no)
    assert f"({n} TD)" in yes.result


def test_passer_and_fumbler_are_not_scorers():
    # Stroud threw 3 TDs and fumbled the aborted snap Marks recovered for the score
    g = _rgame("401772903")
    assert (
        _td("NFL", g, "C.J. Stroud").kind,
        _td("NFL", g, "C.J. Stroud", "no").kind,
    ) == (
        "lost",
        "won",
    )
    assert (
        _td("NCAAF", _rgame("401871076"), "Rodney Tisdale Jr.").kind == "won"
    )  # rush TD;
    # his two-point pass in the parentheses of another play is not a touchdown


def test_non_scorer_in_a_game_with_a_nameless_box_scorer_still_grades():
    # Kneeland has no box-score line, but his play names him in full: others are not him
    g = _rgame("401772818")
    assert (
        _td("NFL", g, "Dak Prescott").kind,
        _td("NFL", g, "Dak Prescott", "no").kind,
    ) == (
        "lost",
        "won",
    )


def test_unnamed_touchdown_scorer_is_void_not_a_guess(monkeypatch):
    # synthetic edit of the real Kneeland game: the play credits an abbreviated name that no
    # box-score athlete matches, so any zero-TD player could be the scorer
    summ = json.loads(json.dumps(SUMMARIES["401772818"]))
    for p in summ["scoringPlays"]:
        p["text"] = p["text"].replace("Marshawn Kneeland Blocked", "Z. Qwerty Blocked")
    monkeypatch.setitem(SUMMARIES, "401772818", summ)
    out = _td("NFL", _rgame("401772818"), "Dak Prescott")
    assert out.kind == "ungradeable" and "not identifiable" in out.result
    assert (
        _td("NFL", _rgame("401772818"), "Trey McBride").kind == "won"
    )  # box score says so


def test_scoring_play_text_rules():
    plays = espn_plays = er._td_plays(
        {
            "scoringPlays": [
                {
                    "type": {"text": "Passing Touchdown"},
                    "text": "A B 10 Yd pass from C D (E F Kick)",
                },
                {"type": {"text": "Two Point Pass"}, "text": "G H 2 Yd pass from C D"},
                {
                    "type": {"text": "Kickoff Return Touchdown"},
                    "text": "I J 40 Yd lateral to K L 30 Yd Return",
                },
            ]
        }
    )  # synthetic: ESPN's lateral wording is not in the saved games
    assert len(plays) == 2
    assert er._scorer_is(plays[0], "a b") and not er._scorer_is(plays[0], "c d")
    assert er._scorer_is(plays[1], "k l") and not er._scorer_is(plays[1], "i j")


def test_ambiguous_names_void_with_a_reason():
    out = _td("NFL", _rgame("401772839"), "Byron Young")  # one on each team
    assert (out.kind, out.result) == (
        "ungradeable",
        "Ambiguous player name: Byron Young",
    )


# --- round 4: the side before parentheses are stripped; junk text ---------------------------

ADMIN_TD_TEXT = [
    ("Charlie Jones anytime touchdown (No)", "Charlie Jones", "no"),
    ("Charlie Jones anytime touchdown (Yes)", "Charlie Jones", "yes"),
    ("Charlie Jones Anytime TD Scorer (No) +120", "Charlie Jones", "no"),
    ("Charlie Jones - Anytime TD - No", "Charlie Jones", "no"),
    ("Charlie Jones Anytime TD: No", "Charlie Jones", "no"),
    ("Charlie Jones Anytime TD No -110", "Charlie Jones", "no"),
    ("Charlie Jones Anytime TD +150", "Charlie Jones", "yes"),
    ("Charlie Jones Anytime TD (-120)", "Charlie Jones", "yes"),
    ("Charlie Jones Anytime TD Yes", "Charlie Jones", "yes"),
    ("No Charlie Jones Anytime TD", "Charlie Jones", "no"),
]


@pytest.mark.parametrize("text,player,side", ADMIN_TD_TEXT)
def test_admin_anytime_td_side_and_player(text, player, side):
    spec = yg._parse_anytime_td(text)
    assert (spec["player"], spec["side"]) == (player, side)


@pytest.mark.parametrize(
    "text,kind",
    [
        (
            "Charlie Jones anytime touchdown (No)",
            "lost",
        ),  # he scored: the NO pick loses
        ("Charlie Jones anytime touchdown (Yes)", "won"),
        ("Charlie Jones Anytime TD Scorer (No) +120", "lost"),
    ],
)
def test_no_in_parentheses_grades_as_no(text, kind):
    r = row(
        "NFL", "player_prop", text, CHI_CIN[1], CHI_CIN[2], datetime(2025, 11, 2, 18)
    )
    assert yg.grade_pick(r).kind == kind


@pytest.mark.parametrize(
    "text",
    [
        "Charlie Jones 2+ touchdowns Anytime TD",
        "Charlie Jones 2+ Anytime TD",
        "Charlie Jones first TD scorer anytime TD",
        "Charlie Jones Anytime TD & Kittle Anytime TD",
        "Charlie Jones / George Kittle Anytime TD",
        "Charlie Jones Anytime TD (Yes) No",
        "Charlie Jones Anytime TD Scorer 1H",
    ],
)
def test_anytime_td_text_with_more_in_it_is_ungradeable_at_once(text):
    r = row(
        "NFL", "player_prop", text, CHI_CIN[1], CHI_CIN[2], datetime(2025, 11, 2, 18)
    )
    out = yg.grade_pick(r)
    assert out.kind == "ungradeable", out


# --- round 4: MLB doubleheaders by order, the game's own date --------------------------------


@pytest.mark.parametrize("day", sorted(DH))
def test_traditional_doubleheader_game_two_maps_by_order(day):
    r = DH[day]
    tb1, tb2 = r["tb"]
    # ESPN shows game 2 at its real start, the MLB schedule a placeholder 5 minutes after game 1
    assert r["mlb_starts"][1] != r["espn_starts"][1]
    g = (day, r["home"], r["away"])
    t1, t2 = (datetime.strptime(x, "%Y-%m-%dT%H:%MZ") for x in r["espn_starts"])
    line = min(tb1, tb2) + 0.5  # the two games grade differently on this line
    for start, tb in ((t1, tb1), (t2, tb2)):
        kind = "won" if tb > line else "lost"
        assert _tb(g, r["player"], "over", line, start).kind == kind, (day, tb)
        assert _tb(g, r["player"], "under", tb + 0.5, start).kind == "won"
    # nothing ties the pick to a game: never guess
    out = _tb(g, r["player"], "over", line)
    assert out.kind == "not_ready" and out.result.startswith("Doubleheader"), out
    # "Game 2" in the pick text does
    g2 = _tb(g, r["player"], "over", line, selection="x over G2")
    assert g2.kind == ("won" if tb2 > line else "lost")


def test_total_bases_uses_the_games_date_not_the_picks():
    # free text created the day after the game (a guessed date): ESPN finds the game on the
    # 15th, the MLB schedule must then be asked for the 15th as well
    r = row(
        "MLB",
        "player_prop",
        "Pete Crow-Armstrong over 3.5 total bases",
        CUBS[1],
        CUBS[2],
        None,
        created_at=datetime(2025, 8, 16, 12),
    )
    assert yg.grade_pick(r).kind == "won"
