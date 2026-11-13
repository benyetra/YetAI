"""Offline tests for yetai_grading: ESPN fixtures via the `espn` fixture from test_espn_results."""

import copy
from datetime import date, datetime

import pytest

from app.models.database_models import BetType, YetAIBet
from app.services import espn_results as er
from app.services import yetai_grading as yg
from tests.test_espn_results import EVENT, GAMES, STAT_CASES, _load, espn  # noqa: F401

GAME_MARKETS = ("moneyline", "spread", "total")
REQUIRED_GAME = {"NBA", "NFL", "NHL", "MLB", "WNBA", "NCAAF", "NCAAB", "EPL", "MLS"}
REQUIRED_PROPS = {
    ("NBA", s) for s in ("points", "rebounds", "assists", "steals", "threes", "pra")
} | {
    ("NFL", "passing_yards"),
    ("NFL", "receiving_yards"),
    ("NHL", "saves"),
    ("MLB", "strikeouts"),
    ("MLB", "hits"),
    ("WNBA", "points"),
}
BET_TYPES = {
    "moneyline": BetType.MONEYLINE,
    "spread": BetType.SPREAD,
    "total": BetType.TOTAL,
    "player_prop": BetType.PROP,
    "prop": BetType.PROP,
    "parlay": BetType.PARLAY,
}


def bet(league, market, grading=None, **kw):
    """Unsaved YetAIBet; `grading` is the contract metadata (None -> text fallback)."""
    kw.setdefault("selection", "x")
    return YetAIBet(
        title="t",
        bet_type=BET_TYPES[market],
        odds=-110,
        confidence=70,
        sport=league,
        prediction_factors={"grading": grading} if grading else {},
        **kw,
    )


def meta(league, market, side, line=None, **extra):
    _, day, home, away, *_ = GAMES[league]
    return {
        "market": market,
        "league": league,
        "game_date": day.isoformat(),
        "home_team": home,
        "away_team": away,
        "side": side,
        "line": line,
        **extra,
    }


def game_cases(league):
    _, _, _, _, hs, aws, _ = GAMES[league]
    margin, total = hs - aws, hs + aws
    cases = [
        ("moneyline", "home", None, "won" if margin > 0 else "lost"),
        ("moneyline", "away", None, "lost" if margin > 0 else "won"),
        ("spread", "home", -margin, "pushed"),
        ("spread", "home", -margin + 0.5, "won"),
        ("spread", "home", -margin - 0.5, "lost"),
        ("total", "over", total, "pushed"),
        ("total", "over", total - 0.5, "won"),
        ("total", "over", total + 0.5, "lost"),
        ("total", "under", total + 0.5, "won"),
        ("total", "under", total - 0.5, "lost"),
    ]
    return [(league, *c) for c in cases]


GAME_CASES = [c for lg in GAMES for c in game_cases(lg)]
PROP_CASES = []
for _lg, _player, _stat, _val in STAT_CASES:
    for _side, _line, _exp in (
        ("over", _val, "pushed"),
        ("over", _val - 0.5, "won"),
        ("over", _val + 0.5, "lost"),
        ("under", _val + 0.5, "won"),
    ):
        PROP_CASES.append((_lg, _player, _stat, _side, _line, _exp))


@pytest.mark.parametrize("league,market,side,line,expected", GAME_CASES)
def test_guarantee_game_markets(espn, league, market, side, line, expected):
    assert yg.can_grade(league, market)
    out = yg.grade_pick(bet(league, market, meta(league, market, side, line)))
    assert out.kind == expected, out
    assert out.result


@pytest.mark.parametrize("league,player,stat,side,line,expected", PROP_CASES)
def test_guarantee_props(espn, league, player, stat, side, line, expected):
    assert yg.can_grade(league, "player_prop", stat)
    g = meta(league, "player_prop", side, line, player=player, stat=stat)
    out = yg.grade_pick(bet(league, "player_prop", g))
    assert out.kind == expected, out


def test_every_supported_combination_is_covered_by_the_table():
    tested_games = {c[0] for c in GAME_CASES}
    tested_props = {(c[0], c[2]) for c in PROP_CASES}
    # Everything espn_results supports must be graded above, none silently skipped.
    assert tested_games >= {lg for lg in er.LEAGUES if lg in GAMES}
    assert tested_props == {(lg, s) for lg, ss in er.PROP_STATS.items() for s in ss}
    # Acceptance criterion 1 minimum set.
    assert tested_games >= REQUIRED_GAME
    assert tested_props >= REQUIRED_PROPS
    assert all(yg.can_grade(lg, m) for lg in REQUIRED_GAME for m in GAME_MARKETS)


def test_unsupported_combinations(espn):
    assert yg.normalize_league("Tennis") is None
    cases = [
        ("Tennis", "moneyline", None, "Unsupported: Tennis moneyline"),
        ("NBA", "player_prop", "dunks", "Unsupported: NBA player_prop dunks"),
        ("NHL", "player_prop", "power_play_points", "Unsupported: NHL player_prop"),
        ("MLB", "player_prop", "total_bases", "Unsupported: MLB player_prop"),
        ("NCAAB", "player_prop", "points", "Unsupported: NCAAB player_prop"),
    ]
    for league, market, stat, reason in cases:
        assert not yg.can_grade(league, market, stat)
        g = {
            **meta("NBA", market, "over", 1.5, player="X", stat=stat),
            "league": league,
        }
        out = yg.grade_pick(bet(league, market, g))
        assert out.kind == "ungradeable" and out.result.startswith(reason), out
    assert not yg.can_grade("NBA", "parlay")
    assert yg.grade_pick(bet("NBA", "spread", selection="gibberish")).kind == (
        "ungradeable"
    )


def test_normalize_league():
    cases = {
        "NBA": "NBA",
        "nba": "NBA",
        "basketball_nba": "NBA",
        "americanfootball_ncaaf": "NCAAF",
        "icehockey_nhl": "NHL",
        "baseball_mlb": "MLB",
        "basketball_wnba": "WNBA",
        "americanfootball_nfl": "NFL",
        "basketball_ncaab": "NCAAB",
        "soccer_epl": "EPL",
        "soccer_usa_mls": "MLS",
        "soccer_uefa_champs_league": "UCL",
        "NCAA Football": "NCAAF",
        "NCAA Basketball": "NCAAB",
        "Soccer": "SOCCER",
        "Tennis": None,
        "tennis_atp": None,
        None: None,
    }
    for raw, want in cases.items():
        assert yg.normalize_league(raw) == want, raw
    assert yg.can_grade("basketball_nba", "total")
    assert yg.can_grade("Soccer", "moneyline") and not yg.can_grade(
        "Soccer", "player_prop", "points"
    )
    assert yg.can_grade("NCAA Football", "spread")


def _nba(selection_market="spread", **grading):
    return bet("NBA", selection_market, meta("NBA", selection_market, **grading))


def test_postponed_dnp_not_found_scheduled(espn):
    espn.boards[("mlb", "20250425")] = _load("mlb_postponed_scoreboard_20250425.json")
    g = {
        "market": "total",
        "league": "MLB",
        "game_date": "2025-04-25",
        "home_team": "Detroit Tigers",
        "away_team": "Baltimore Orioles",
        "side": "over",
        "line": 8.5,
    }
    assert yg.grade_pick(bet("MLB", "total", g)) == yg.Outcome("void", "Postponed")

    ev = EVENT["NBA"]
    del ev
    prop = lambda p: bet(  # noqa: E731
        "NBA",
        "player_prop",
        meta("NBA", "player_prop", "over", 5.5, player=p, stat="points"),
    )
    assert yg.grade_pick(prop("Paul George")) == yg.Outcome("void", "DNP: Paul George")
    out = yg.grade_pick(prop("Nobody Atall"))
    assert out.kind == "not_ready" and "Nobody Atall" in out.result

    board = copy.deepcopy(espn.boards[("nba", "20260111")])
    board["events"][0]["competitions"][0]["status"]["type"].update(
        name="STATUS_SCHEDULED", completed=False, state="pre"
    )
    espn.boards[("nba", "20260111")] = board
    assert yg.grade_pick(_nba(side="home", line=-1.5)) == yg.Outcome(
        "not_ready", "scheduled"
    )
    board["events"][0]["competitions"][0]["status"]["type"].update(
        name="STATUS_CANCELED", completed=True
    )
    assert yg.grade_pick(_nba(side="home", line=-1.5)) == yg.Outcome(
        "void", "Cancelled"
    )


def test_game_not_found_and_espn_error(espn, monkeypatch):
    g = meta("NBA", "total", "over", 200.5)
    g["game_date"] = "2026-03-01"
    assert yg.grade_pick(bet("NBA", "total", g)) == yg.Outcome(
        "not_ready", "Game not found"
    )

    def boom(*a, **k):
        raise er.requests.ConnectionError("down")

    monkeypatch.setattr(er, "_get_json", boom)
    out = yg.grade_pick(_nba("total", side="over", line=200.5))
    assert out.kind == "error" and out.result.startswith("ESPN error: ")


def test_swapped_home_away_still_grades(espn):
    # Our row has home/away reversed vs ESPN (TOR 116 - PHI 115); picks the real home team.
    _, day, home, away, *_ = GAMES["NBA"]
    g = {**meta("NBA", "spread", "home", -0.5), "home_team": away, "away_team": home}
    out = yg.grade_pick(bet("NBA", "spread", g))  # "home" here is PHI: 115 - 0.5 < 116
    assert out.kind == "lost", out
    g["side"] = "away"
    assert yg.grade_pick(
        bet("NBA", "moneyline", {**g, "market": "moneyline"})
    ).kind == ("won")


def test_soccer_draw_is_loss_and_overtime_counts(espn):
    board = copy.deepcopy(espn.boards[("eng.1", "20251101")])
    for c in board["events"][0]["competitions"][0]["competitors"]:
        c["score"] = "1"
    espn.boards[("eng.1", "20251101")] = board
    ml = meta("EPL", "moneyline", "home")
    assert yg.grade_pick(bet("EPL", "moneyline", ml)).kind == "lost"
    assert yg.grade_pick(bet("EPL", "moneyline", {**ml, "side": "away"})).kind == "lost"
    assert yg.grade_pick(
        bet("EPL", "total", meta("EPL", "total", "under", 2))
    ).kind == ("pushed")
    # generic admin "Soccer" label searches every soccer league (MLS game here)
    out = yg.grade_pick(
        bet(
            "Soccer",
            "moneyline",
            {**meta("MLS", "moneyline", "away"), "league": "Soccer"},
        )
    )
    assert out.kind == "won"

    # Non-soccer tie (e.g. NFL regulation tie) is a push; OT winners count as listed.
    board = copy.deepcopy(espn.boards[("nfl", "20251102")])
    comp = board["events"][0]["competitions"][0]
    comp["status"]["type"]["detail"] = "Final/OT"
    espn.boards[("nfl", "20251102")] = board
    assert (
        yg.grade_pick(bet("NFL", "moneyline", meta("NFL", "moneyline", "away"))).kind
        == "won"
    )
    for c in comp["competitors"]:
        c["score"] = "20"
    assert (
        yg.grade_pick(bet("NFL", "moneyline", meta("NFL", "moneyline", "away"))).kind
        == "pushed"
    )


@pytest.mark.parametrize(
    "text,want",
    [
        ("Philadelphia 76ers -3.5", -3.5),
        ("San Francisco 49ers +2.5", 2.5),
        ("Over 221.5 (76ers @ Celtics)", 221.5),
        ("Under 44 (49ers vs Rams)", 44),
        ("76ers ML", None),
        ("Lakers PK", 0.0),
        ("Celtics pick'em", 0.0),
        ("Boston Celtics -4.5 (-110)", -4.5),
        ("o220.5", 220.5),
        ("U 6", 6),
        ("Over 6.5", 6.5),
        ("Lakers +1", 1.0),
        ("", None),
    ],
)
def test_parse_line(text, want):
    assert yg.parse_line(text) == want


def row(sport, bet_type, selection, home, away, day=None, **kw):
    return bet(
        sport,
        bet_type,
        selection=selection,
        home_team=home,
        away_team=away,
        commence_time=day,
        **kw,
    )


def test_grading_spec_sides_and_lines():
    r = row(
        "NBA",
        "spread",
        "Philadelphia 76ers -3.5",
        "Toronto Raptors",
        "Philadelphia 76ers",
        datetime(2026, 1, 11, 18),
    )
    s = yg.grading_spec(r)
    assert (s["side"], s["line"], s["market"], s["league"]) == (
        "away",
        -3.5,
        "spread",
        "NBA",
    )
    assert s["game_date"] == "2026-01-11"
    r = row(
        "NFL",
        "spread",
        "San Francisco 49ers +2.5",
        "New York Giants",
        "San Francisco 49ers",
        datetime(2025, 11, 2, 18),
    )
    assert (yg.grading_spec(r)["side"], yg.grading_spec(r)["line"]) == ("away", 2.5)
    r = row(
        "NBA",
        "total",
        "Under 44 (49ers vs Rams)",
        "Los Angeles Rams",
        "San Francisco 49ers",
        datetime(2025, 11, 2, 18),
    )
    assert (yg.grading_spec(r)["side"], yg.grading_spec(r)["line"]) == ("under", 44)
    r = row(
        "NBA",
        "spread",
        "Portland Trail Blazers +4 (Lakers -4)",
        "Los Angeles Lakers",
        "Portland Trail Blazers",
        datetime(2026, 1, 1, 18),
    )
    assert yg.grading_spec(r)["side"] == "away"
    r = row(
        "MLB",
        "moneyline",
        "Red Sox",
        "Boston Red Sox",
        "Chicago White Sox",
        datetime(2026, 5, 1, 18),
    )
    assert yg.grading_spec(r)["side"] == "home"
    assert (
        yg.grading_spec(
            row(
                "NBA",
                "moneyline",
                "Heat",
                "Boston Celtics",
                "Miami Heat",
                datetime(2026, 1, 1),
            )
        )["side"]
        == "away"
    )
    assert (
        yg.grading_spec(
            row(
                "NBA",
                "moneyline",
                "Nuggets",
                "Boston Celtics",
                "Miami Heat",
                datetime(2026, 1, 1),
            )
        )
        is None
    )
    assert (
        yg.grading_spec(row("NBA", "parlay", "x", "a", "b", datetime(2026, 1, 1)))
        is None
    )


def test_76ers_spread_graded_from_fixture(espn):
    # TOR 116 - PHI 115: 76ers -3.5 loses; 76ers +1.5 wins; 76ers +1 pushes.
    d = datetime(2026, 1, 11, 18)
    for sel, want in (
        ("Philadelphia 76ers -3.5", "lost"),
        ("76ers +1.5", "won"),
        ("76ers +1", "pushed"),
    ):
        r = row("NBA", "spread", sel, "Toronto Raptors", "Philadelphia 76ers", d)
        assert yg.grade_pick(r).kind == want, sel


def test_game_day_for():
    base = {"home_team": "a", "away_team": "b"}
    r = row(
        "NBA", "spread", "a -1", "a", "b", datetime(2026, 1, 12, 2, 30)
    )  # 9:30pm ET Jan 11
    assert yg.game_day_for(r) == date(2026, 1, 11)
    r = bet(
        "NBA",
        "spread",
        meta("NBA", "spread", "home", -1),
        commence_time=datetime(2026, 2, 1),
    )
    assert yg.game_day_for(r) == date(2026, 1, 11)  # metadata wins
    r = bet("NBA", "spread", selection="a -1")
    r.prediction_factors = {"event_id": "nba_2026-03-04_x"}
    assert yg.game_day_for(r) == date(2026, 3, 4)
    r.prediction_factors = {}
    r.created_at = datetime(2026, 3, 5, 12)
    assert yg.game_day_for(r) == date(2026, 3, 5)
    assert yg.game_day_for(bet("NBA", "spread")) is None
    del base


def test_metadata_fills_teams_from_row():
    g = meta("NBA", "total", "over", 200.5)
    g.pop("home_team"), g.pop("away_team")
    r = bet(
        "NBA", "total", g, home_team="Toronto Raptors", away_team="Philadelphia 76ers"
    )
    s = yg.grading_spec(r)
    assert (
        s["home_team"] == "Toronto Raptors" and s["away_team"] == "Philadelphia 76ers"
    )


def test_fallback_admin_rows_settle(espn):
    # TOR 116 PHI 115 (NBA), SF 34 @ NYG 24 (NFL), PIT 3 @ CHC 2 (MLB), NHL MTL 3 @ BUF 5.
    cases = [
        (
            row(
                "NBA",
                "spread",
                "Toronto Raptors -4.5",
                "Toronto Raptors",
                "Philadelphia 76ers",
                datetime(2026, 1, 11, 18),
            ),
            "lost",
        ),
        (
            row(
                "NBA",
                "spread",
                "Boston Celtics -4.5",
                "Boston Celtics",
                "Toronto Raptors",
                datetime(2026, 1, 11, 18),
            ),
            "not_ready",
        ),
        (
            row(
                "NHL",
                "total",
                "Over 6.5",
                "Buffalo Sabres",
                "Montreal Canadiens",
                datetime(2026, 1, 16, 0, 30),
            ),
            "won",
        ),
        (
            row(
                "NFL",
                "moneyline",
                "San Francisco 49ers",
                "New York Giants",
                "San Francisco 49ers",
                datetime(2025, 11, 2, 18),
            ),
            "won",
        ),
        (
            row(
                "NFL",
                "moneyline",
                "Kansas City Chiefs",
                "New York Giants",
                "Kansas City Chiefs",
                datetime(2025, 11, 2, 18),
            ),
            "not_ready",
        ),
        (
            row(
                "NBA",
                "prop",
                "Kelly Oubre Jr. OVER 12.5 points",
                "Toronto Raptors",
                "Philadelphia 76ers",
                datetime(2026, 1, 11, 18),
            ),
            "won",
        ),
        (
            row(
                "NBA",
                "prop",
                "Over 14.5 Points - Kelly Oubre Jr.",
                "Toronto Raptors",
                "Philadelphia 76ers",
                datetime(2026, 1, 11, 18),
            ),
            "lost",
        ),
        (
            row(
                "NBA",
                "prop",
                "Kelly Oubre Jr. over 17.5 pts+reb+ast (-115)",
                "Toronto Raptors",
                "Philadelphia 76ers",
                datetime(2026, 1, 11, 18),
            ),
            "won",
        ),
        (
            row(
                "basketball_nba",
                "total",
                "Under 231.5",
                "Toronto Raptors",
                "Philadelphia 76ers",
                datetime(2026, 1, 11, 18),
            ),
            "won",
        ),
        (
            row(
                "NBA",
                "prop",
                "Kelly Oubre Jr. over 1.5 dunks",
                "Toronto Raptors",
                "Philadelphia 76ers",
                datetime(2026, 1, 11, 18),
            ),
            "ungradeable",
        ),
        (
            row("Tennis", "moneyline", "Sinner", "A", "B", datetime(2026, 1, 11, 18)),
            "ungradeable",
        ),
    ]
    got = [yg.grade_pick(r).kind for r, _ in cases]
    assert got == [w for _, w in cases]
    # Boston/Kansas City rows are well-formed picks on games that aren't in the fixtures.


def test_pick_side_matches_location_and_nickname():
    from app.services.yetai_grading import _pick_side

    assert (
        _pick_side("Ohio State -7.5", "Ohio State Buckeyes", "Penn State Nittany Lions")
        == "home"
    )
    assert _pick_side("Brighton ML", "Brighton & Hove Albion", "Leeds United") == "home"
    assert (
        _pick_side("Los Angeles Lakers -3", "Los Angeles Lakers", "LA Clippers")
        == "home"
    )
    assert _pick_side("Clippers +3", "Los Angeles Lakers", "LA Clippers") == "away"
    assert (
        _pick_side("Philadelphia 76ers -3.5", "Toronto Raptors", "Philadelphia 76ers")
        == "away"
    )


# --- review fixes: free text odds, PK, partial markets ----------------------


@pytest.mark.parametrize(
    "text,want",
    [
        ("Lakers -3.5 -110", -3.5),
        ("Lakers +3.5 +100", 3.5),
        ("Lakers -3.5 (-110)", -3.5),
        ("Lakers PK -110", 0.0),
        ("Lakers pick em", 0.0),
        ("Lakers pick'em +105", 0.0),
        ("Lakers -110", None),  # only odds: no spread line
        ("Lakers -150.5", None),  # |spread| must be under 100
        ("Philadelphia 76ers +1.5 -105", 1.5),
        ("Over 220.5 -110", 220.5),
    ],
)
def test_parse_line_ignores_trailing_odds(text, want):
    assert yg.parse_line(text) == want


NBA_DAY = datetime(2026, 1, 11, 18)


@pytest.mark.parametrize(
    "market,selection",
    [
        ("spread", "Toronto Raptors -3.5 1H"),
        ("spread", "Toronto Raptors -1.5 First Half"),
        ("spread", "Raptors 2H +1.5"),
        ("spread", "Raptors 1Q -0.5"),
        ("total", "Over 55.5 1st Quarter"),
        ("total", "Raptors Team Total Over 110.5"),
        ("total", "Toronto Raptors TT Over 110.5"),
        ("spread", "Raptors Alt Spread -10.5"),
        ("moneyline", "Raptors F5 ML"),
        ("total", "Under 4.5 First 5 Innings"),
    ],
)
def test_partial_game_and_team_total_markets_are_ungradeable(espn, market, selection):
    out = yg.grade_pick(row_(market, selection))
    assert out.kind == "ungradeable" and out.result.startswith("Unsupported market")


def row_(market, selection):
    return bet(
        "NBA",
        market,
        selection=selection,
        home_team="Toronto Raptors",
        away_team="Philadelphia 76ers",
        commence_time=NBA_DAY,
    )


def test_free_text_with_odds_grades_on_the_line(espn):
    # TOR 116 - PHI 115
    assert yg.grade_pick(row_("spread", "Toronto Raptors -3.5 -110")).kind == "lost"
    assert yg.grade_pick(row_("spread", "Philadelphia 76ers +3.5 +100")).kind == "won"
    assert yg.grade_pick(row_("spread", "Toronto Raptors PK -110")).kind == "won"
    assert yg.grade_pick(row_("spread", "Toronto Raptors -110")).kind == "ungradeable"


# --- review fixes: soccer regulation and draws ------------------------------


def _ucl(espn, side, market="moneyline", line=None, selection="x", grading=True):
    from tests.test_espn_results import REAL_BOARDS

    espn.boards[("uefa.champions", "20250219")] = _load(
        REAL_BOARDS[("uefa.champions", "20250219")]
    )
    espn.summaries["732195"] = _load("ucl_summary_732195.json")
    g = {
        "market": market,
        "league": "UCL",
        "game_date": "2025-02-19",
        "home_team": "PSV Eindhoven",
        "away_team": "Juventus",
        "side": side,
        "line": line,
    }
    return bet(
        "UCL",
        market,
        g if grading else None,
        selection=selection,
        home_team="PSV Eindhoven",
        away_team="Juventus",
        commence_time=datetime(2025, 2, 19, 20, 0),
    )


def test_soccer_extra_time_graded_on_90_minutes(espn):
    # PSV 3-1 a.e.t., 2-1 after 90'
    assert yg.grade_pick(_ucl(espn, "home")).result == "Won: PSV Eindhoven ML (2-1)"
    assert yg.grade_pick(_ucl(espn, "over", "total", 3.5)).kind == "lost"  # 3, not 4
    assert yg.grade_pick(_ucl(espn, "home", "spread", -1.5)).kind == "lost"  # 2-1


def test_soccer_extra_time_without_regulation_score_voids(espn):
    b = _ucl(espn, "home")
    espn.summaries["732195"] = {"header": {"competitions": [{"competitors": []}]}}
    out = yg.grade_pick(b)
    assert out.kind == "void" and out.result.startswith("No regulation score")


def test_draw_pick_grades(espn):
    board = copy.deepcopy(espn.boards[("eng.1", "20251101")])
    for c in board["events"][0]["competitions"][0]["competitors"]:
        c["score"] = "1"
    espn.boards[("eng.1", "20251101")] = board
    draw = meta("EPL", "moneyline", "draw")
    assert yg.grade_pick(bet("EPL", "moneyline", draw)) == yg.Outcome(
        "won", "Won: Draw (1-1)"
    )
    text = bet(
        "EPL",
        "moneyline",
        selection="Draw",
        home_team="Brighton & Hove Albion",
        away_team="Leeds United",
        commence_time=datetime(2025, 11, 1, 15),
    )
    assert yg.grade_pick(text).kind == "won"
    espn.boards[("eng.1", "20251101")] = _load("epl_scoreboard_20251101.json")  # 3-0
    assert yg.grade_pick(bet("EPL", "moneyline", draw)).kind == "lost"
    # after extra time the draw pick is judged on 90 minutes too
    assert yg.grade_pick(_ucl(espn, "draw")).kind == "lost"  # 2-1 at 90'
    nba = meta("NBA", "moneyline", "draw")
    assert yg.grade_pick(bet("NBA", "moneyline", nba)).kind == "ungradeable"


# --- review fixes: error vs ungradeable --------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        er.requests.Timeout("t"),
        er.requests.HTTPError("429 Too Many Requests"),
        er.requests.HTTPError("503"),
        __import__("json").JSONDecodeError("x", "doc", 0),
    ],
)
def test_transport_failures_are_errors(espn, monkeypatch, exc):
    def boom(*a, **k):
        raise exc

    monkeypatch.setattr(er, "_get_json", boom)
    assert yg.grade_pick(_nba("total", side="over", line=200.5)).kind == "error"


@pytest.mark.parametrize(
    "patch_",
    [
        {"line": "abc"},
        {"line": [1]},
        {"game_date": "2026-13-45"},
        {"home_team": 7},
        {"side": "sideways"},
    ],
)
def test_bad_metadata_is_ungradeable_not_retried(espn, patch_):
    g = {**meta("NBA", "total", "over", 200.5), **patch_}
    assert yg.grade_pick(bet("NBA", "total", g)).kind == "ungradeable"


def test_string_line_that_parses_still_grades(espn):
    g = meta("NBA", "total", "over", "200.5")
    assert yg.grade_pick(bet("NBA", "total", g)).kind == "won"


@pytest.mark.parametrize(
    "league,player,stat",
    [("NHL", "Jacob Fowler", "goals"), ("MLB", "Ronny Simon", "strikeouts")],
)
def test_wrong_role_stat_voids_at_once_with_an_accurate_reason(
    espn, league, player, stat
):
    """A goalie's goals / a batter's strikeouts: final box score, no such stat. No 3-day wait."""
    g = meta(league, "player_prop", "over", 0.5, player=player, stat=stat)
    out = yg.grade_pick(bet(league, "player_prop", g))
    assert out.kind == "ungradeable"
    assert out.result == f"Stat not recorded for {player}: {stat}"
