import asyncio
from datetime import date, datetime, timedelta, timezone

from app.models.predictions_models import (
    NBAGameLines,
    NBASpreadProjections,
    NBATotalsProjections,
    PointsProjections,
    PRAProjections,
    ThreePointProjections,
)
from app.services.auto_pick.candidate import slate_window_for_date
from app.services.auto_pick.providers.moneyline_provider import (
    MoneylineCandidateProvider,
)
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.providers.spread_provider import SpreadCandidateProvider
from app.services.auto_pick.providers.totals_provider import TotalsCandidateProvider
from app.services.auto_pick.sources.nba_moneyline_source import NBAMoneylineSource
from app.services.auto_pick.sources.nba_spread_source import NBASpreadSource
from app.services.auto_pick.sources.nba_totals_source import NBATotalsSource
from app.services.auto_pick.sources.player_prop_source import PlayerPropSource

DAY = date(2026, 1, 15)
OTHER = DAY + timedelta(days=1)
RANGE = slate_window_for_date(DAY)
# 7:30pm ET == 00:30 UTC next day, stored aware.
TIP_AWARE = datetime(2026, 1, 16, 0, 30, tzinfo=timezone.utc)
TIP_NAIVE = datetime(2026, 1, 16, 0, 30)
HOME, AWAY = "Boston Celtics", "Los Angeles Lakers"


def run(coro):
    return asyncio.run(coro)


def _gl(db, d=DAY, **kw):
    vals = dict(
        game_date=d,
        home_team_name=HOME,
        away_team_name=AWAY,
        odds_api_event_id="evt-1",
        game_time=TIP_AWARE,
        # update_game_lines writes the current line next to its price.
        spread_home=-6.5,
        spread_away=6.5,
        total=225.5,
        spread_home_odds=-112,
        spread_away_odds=-108,
        over_odds=-115,
        under_odds=-105,
        moneyline_home=-200,
        moneyline_away=170,
    )
    vals.update(kw)
    db.add(NBAGameLines(**vals))


def _spread(db, rec="AWAY", d=DAY, **kw):
    db.add(
        NBASpreadProjections(
            game_date=d,
            home_team_name=HOME,
            away_team_name=AWAY,
            projected_margin=2.0,
            home_win_prob=kw.pop("hwp", 0.6),
            market_spread_home=-6.5,
            edge=-4.5,
            recommendation=rec,
            created_at=datetime(2026, 1, 15, 15, 0),
            **kw,
        )
    )


def test_spread_side_odds_time_and_provider(sqlite_db):
    _gl(sqlite_db)
    _spread(sqlite_db)
    rows = run(NBASpreadSource(sqlite_db).get_todays_projections(RANGE))
    assert len(rows) == 1
    r = rows[0]
    assert r["side"] == "away" and r["spread_odds"] == -108
    assert r["event_id"] == "evt-1" and r["commence_time"] == TIP_NAIVE
    assert r["game_date"] == DAY and r["generated_at"] == datetime(2026, 1, 15, 15, 0)
    assert (r["home_team_name"], r["away_team_name"]) == (HOME, AWAY)

    src = type("S", (), {"get_todays_projections": lambda s, dr: _ret(rows)})()
    c = run(SpreadCandidateProvider(src).get_candidates(RANGE))[0]
    assert c.projection_metadata["side"] == "away"
    assert c.game_date == DAY and c.commence_time == TIP_NAIVE
    assert c.market_odds == -108


async def _ret(v):
    return v


def test_spread_skips(sqlite_db):
    _gl(sqlite_db)
    _spread(sqlite_db, rec="NO_PLAY")
    assert run(NBASpreadSource(sqlite_db).get_todays_projections(RANGE)) == []


def _total(db):
    db.add(
        NBATotalsProjections(
            game_date=DAY,
            home_team_name=HOME,
            away_team_name=AWAY,
            projected_total=231.0,
            market_total=225.5,
            edge=5.5,
            recommendation="OVER",
        )
    )


def _spread_rows(db):
    return run(NBASpreadSource(db).get_todays_projections(RANGE))


def _total_rows(db):
    return run(NBATotalsSource(db).get_todays_projections(RANGE))


def test_moved_line_toward_pick_drops_when_edge_falls_below_threshold(sqlite_db):
    # Projection: margin 2.0 vs -6.5 (AWAY, edge 4.5). Line now -3.5: edge 1.5 < 2.0.
    # Total: 231.0 vs 225.5 (OVER). Line now 228.0: edge 3.0 < MIN_EDGE 4.0.
    _gl(sqlite_db, spread_home=-3.5, total=228.0)
    _spread(sqlite_db)
    _total(sqlite_db)
    assert _spread_rows(sqlite_db) == []
    assert _total_rows(sqlite_db) == []


def test_moved_line_that_still_holds_publishes_current_line(sqlite_db):
    # Spread now -5.5 (AWAY edge 3.5 >= 2.0); total now 226.5 (OVER edge 4.5 >= 4.0).
    _gl(sqlite_db, spread_home=-5.5, total=226.5)
    _spread(sqlite_db)
    _total(sqlite_db)
    (s,) = _spread_rows(sqlite_db)
    assert s["market_spread_home"] == -5.5 and s["edge"] == -3.5
    assert s["spread_odds"] == -108  # current away price
    (c,) = run(
        SpreadCandidateProvider(NBASpreadSource(sqlite_db)).get_candidates(RANGE)
    )
    assert c.market_line == 5.5 and "5.5" in c.selection and "6.5" not in c.selection
    (t,) = _total_rows(sqlite_db)
    assert t["market_total"] == 226.5 and t["edge"] == 4.5
    (tc,) = run(
        TotalsCandidateProvider(NBATotalsSource(sqlite_db)).get_candidates(RANGE)
    )
    assert tc.market_line == 226.5 and "226.5" in tc.selection
    from app.services.auto_pick.orchestrator import grading_block

    assert grading_block(c)["line"] == 5.5 and grading_block(tc)["line"] == 226.5


def test_moved_line_that_flips_the_side_is_dropped(sqlite_db):
    # Line moved past the projection: margin 2.0 now favours HOME at +1.0; total 235 favours UNDER.
    _gl(sqlite_db, spread_home=1.0, total=235.0)
    _spread(sqlite_db)
    _total(sqlite_db)
    assert _spread_rows(sqlite_db) == []
    assert _total_rows(sqlite_db) == []


def test_spread_skips_missing_price_no_line_other_day(sqlite_db):
    _gl(sqlite_db, spread_away_odds=None)
    _spread(sqlite_db)  # AWAY, price missing
    _spread(sqlite_db, d=OTHER)  # other day, no game line
    assert run(NBASpreadSource(sqlite_db).get_todays_projections(RANGE)) == []
    assert run(NBASpreadSource(sqlite_db).get_todays_projections(RANGE)) == []


def test_totals_over_under_and_no_play(sqlite_db):
    _gl(sqlite_db)
    base = dict(
        game_date=DAY,
        home_team_name=HOME,
        away_team_name=AWAY,
        projected_total=231.0,
        market_total=225.5,
    )
    sqlite_db.add(NBATotalsProjections(recommendation="UNDER", **base))
    rows = run(NBATotalsSource(sqlite_db).get_todays_projections(RANGE))
    assert rows[0]["side"] == "under" and rows[0]["line_odds"] == -105
    c = run(
        TotalsCandidateProvider(
            type("S", (), {"get_todays_projections": lambda s, dr: _ret(rows)})()
        ).get_candidates(RANGE)
    )[0]
    assert c.commence_time == TIP_NAIVE and c.market_line == 225.5


def test_totals_no_play_skipped(sqlite_db):
    _gl(sqlite_db)
    sqlite_db.add(
        NBATotalsProjections(
            game_date=DAY,
            home_team_name=HOME,
            away_team_name=AWAY,
            projected_total=231.0,
            market_total=225.5,
            recommendation="NO_PLAY",
        )
    )
    assert run(NBATotalsSource(sqlite_db).get_todays_projections(RANGE)) == []


def test_moneyline_edge_side(sqlite_db):
    _gl(sqlite_db)  # no-vig home ~0.644
    _spread(
        sqlite_db, rec="NO_PLAY", hwp=0.5, factors={"market_win_prob": 0.644}
    )  # away: 0.5 > 0.356 -> away
    rows = run(NBAMoneylineSource(sqlite_db).get_todays_projections(RANGE))
    assert len(rows) == 1
    r = rows[0]
    assert r["side"] == "away"
    assert (r["moneyline_home"], r["moneyline_away"]) == (-200, 170)
    c = run(
        MoneylineCandidateProvider(
            type("S", (), {"get_todays_projections": lambda s, dr: _ret(rows)})()
        ).get_candidates(RANGE)
    )[0]
    assert c.market_odds == 170 and c.our_projection == 0.5
    assert c.game_date == DAY and c.commence_time == TIP_NAIVE


def test_moneyline_skips_no_edge_missing_price(sqlite_db):
    _gl(sqlite_db)
    _spread(sqlite_db, rec="NO_PLAY", hwp=0.5)
    sqlite_db.query(NBAGameLines).update({"moneyline_away": None})
    assert run(NBAMoneylineSource(sqlite_db).get_todays_projections(RANGE)) == []


def test_moneyline_home_edge(sqlite_db):
    _gl(sqlite_db)
    _spread(sqlite_db, rec="NO_PLAY", hwp=0.8, factors={"market_win_prob": 0.644})
    rows = run(NBAMoneylineSource(sqlite_db).get_todays_projections(RANGE))
    assert rows[0]["side"] == "home"


def test_props_points_threes_pra_teams_and_skips(sqlite_db):
    _gl(sqlite_db)
    common = dict(date=DAY, player_id=1, player_name="Jayson Tatum")
    sqlite_db.add_all(
        [
            # Tatum plays for HOME, opponent is the away team.
            PointsProjections(
                opponent_team_name=AWAY,
                projected_points=29.0,
                fanduel_line=26.5,
                fanduel_over_under="o",
                fanduel_price=-125,
                **common,
            ),
            ThreePointProjections(
                opponent_team_name=AWAY,
                projected_three_pt_made=2.0,
                fanduel_line=3.5,
                fanduel_over_under="u",
                fanduel_price=110,
                **common,
            ),
            PRAProjections(
                opponent_team_name=AWAY,
                projected_points=29.0,
                projected_rebounds=8.0,
                projected_assists=5.0,
                projected_pra=42.0,
                fanduel_line=39.5,
                fanduel_over_under="o",
                fanduel_price=-115,
                **common,
            ),
            # no flag -> skipped
            PointsProjections(
                date=DAY,
                player_id=2,
                player_name="X",
                opponent_team_name=AWAY,
                projected_points=20.0,
                fanduel_line=18.5,
            ),
            # line and flag but no price (row from before the column) -> skipped
            PointsProjections(
                date=DAY,
                player_id=6,
                player_name="V",
                opponent_team_name=AWAY,
                projected_points=20.0,
                fanduel_line=18.5,
                fanduel_over_under="o",
            ),
            # no line -> skipped
            PointsProjections(
                date=DAY,
                player_id=3,
                player_name="Y",
                opponent_team_name=AWAY,
                projected_points=20.0,
            ),
            # game not found -> skipped
            PointsProjections(
                date=DAY,
                player_id=4,
                player_name="Z",
                opponent_team_name="Nowhere Nobodies",
                projected_points=20.0,
                fanduel_line=18.5,
                fanduel_over_under="o",
                fanduel_price=-110,
            ),
            # other day -> skipped
            PointsProjections(
                date=OTHER,
                player_id=5,
                player_name="W",
                opponent_team_name=AWAY,
                projected_points=20.0,
                fanduel_line=18.5,
                fanduel_over_under="o",
                fanduel_price=-110,
            ),
        ]
    )
    rows = run(PlayerPropSource(sqlite_db).get_todays_projections(RANGE))
    by = {r["stat"]: r for r in rows}
    assert set(by) == {"points", "threes", "pra"}
    p = by["points"]
    assert p["side"] == "over" and p["line"] == 26.5 and p["odds"] == -125
    assert p["odds_assumed"] is False and p["generated_at"] is None
    assert (p["home_team_name"], p["away_team_name"]) == (HOME, AWAY)
    assert p["team"] == HOME and p["opponent"] == AWAY
    assert p["event_id"] == "evt-1" and p["commence_time"] == TIP_NAIVE
    assert p["game_date"] == DAY
    assert by["threes"]["side"] == "under" and by["pra"]["projection"] == 42.0
    assert by["threes"]["odds"] == 110 and by["pra"]["odds"] == -115

    c = run(
        PlayerPropCandidateProvider(
            type("S", (), {"get_todays_projections": lambda s, dr: _ret(rows)})()
        ).get_candidates(RANGE)
    )
    cp = next(x for x in c if x.projection_metadata["stat"] == "points")
    assert cp.projection_metadata["side"] == "over"
    assert cp.home_team == HOME and cp.away_team == AWAY
    assert cp.game_date == DAY and cp.commence_time == TIP_NAIVE


def test_props_price_feeds_the_odds_gate_and_missing_column_degrades(sqlite_db):
    from datetime import datetime as dt

    from app.services.auto_pick.selector import ScoredCandidate, hard_gate_reason
    from app.services.auto_pick.confidence_score import ConfidenceScore

    _gl(sqlite_db)
    sqlite_db.add(
        PointsProjections(
            date=DAY,
            player_id=1,
            player_name="Jayson Tatum",
            opponent_team_name=AWAY,
            projected_points=29.0,
            fanduel_line=26.5,
            fanduel_over_under="o",
            fanduel_price=-450,
        )
    )
    rows = run(PlayerPropSource(sqlite_db).get_todays_projections(RANGE))
    cand = run(
        PlayerPropCandidateProvider(
            type("S", (), {"get_todays_projections": lambda s, dr: _ret(rows)})()
        ).get_candidates(RANGE)
    )[0]
    assert cand.market_odds == -450
    sc = ScoredCandidate(
        candidate=cand, score=ConfidenceScore(total=70, breakdown={}, reasoning="")
    )
    assert hard_gate_reason(sc, dt(2020, 1, 1), -300, 400) == "odds_out_of_bounds"

    # DB without the fanduel_price column (migration not run): SELECT fails,
    # the source logs and returns no rows instead of raising.
    sqlite_db.execute(
        __import__("sqlalchemy").text("DROP TABLE pred_points_projections")
    )
    sqlite_db.execute(
        __import__("sqlalchemy").text(
            "CREATE TABLE pred_points_projections (id INTEGER PRIMARY KEY, date DATE)"
        )
    )
    assert run(PlayerPropSource(sqlite_db).get_todays_projections(RANGE)) == []
