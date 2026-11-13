import asyncio
from datetime import date, datetime, timedelta, timezone

from app.models.predictions_models import (
    WNBAGameLines,
    WNBAPointsProjections,
    WNBAPRAProjections,
    WNBASpreadProjections,
    WNBAThreePtMadeProjections,
    WNBATotalsProjections,
)
from app.services.auto_pick.candidate import slate_window_for_date
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.providers.spread_provider import SpreadCandidateProvider
from app.services.auto_pick.sources.wnba_player_prop_source import WNBAPlayerPropSource
from app.services.auto_pick.sources.wnba_spread_source import WNBASpreadSource
from app.services.auto_pick.sources.wnba_totals_source import WNBATotalsSource

DAY = date(2026, 7, 10)
OTHER = DAY + timedelta(days=1)
RANGE = slate_window_for_date(DAY)
TIP = datetime(2026, 7, 10, 23, 0)  # naive UTC
HOME, AWAY = "Las Vegas Aces", "Seattle Storm"
CREATED = datetime(2026, 7, 10, 14, 0)


def run(coro):
    return asyncio.run(coro)


async def _ret(v):
    return v


def _src(rows):
    return type("S", (), {"get_todays_projections": lambda s, dr: _ret(rows)})()


def _gl(db, d=DAY, **kw):
    vals = dict(
        game_date=d,
        home_team_name=HOME,
        away_team_name=AWAY,
        odds_api_event_id="wevt-1",
        game_time=TIP,
        # update_game_lines writes the current line next to its price.
        spread_home=-3.5,
        spread_away=3.5,
        total=165.5,
        spread_home_odds=-110,
        spread_away_odds=-105,
        over_odds=-115,
        under_odds=-105,
    )
    vals.update(kw)
    db.add(WNBAGameLines(**vals))


def test_totals_over(sqlite_db):
    _gl(sqlite_db)
    sqlite_db.add(
        WNBATotalsProjections(
            game_date=DAY,
            home_team_name=HOME,
            away_team_name=AWAY,
            projected_total=168.5,
            market_total=165.5,
            recommendation="OVER",
            created_at=CREATED,
        )
    )
    r = run(WNBATotalsSource(sqlite_db).get_todays_projections(RANGE))
    assert len(r) == 1
    assert r[0]["side"] == "over" and r[0]["line_odds"] == -115
    assert r[0]["commence_time"] == TIP and r[0]["event_id"] == "wevt-1"
    assert r[0]["generated_at"] == CREATED and r[0]["game_date"] == DAY


def test_totals_skips_no_play_missing_price_other_day(sqlite_db):
    _gl(sqlite_db, under_odds=None)
    for rec, d in (("NO_PLAY", DAY), ("UNDER", DAY), ("OVER", OTHER)):
        sqlite_db.add(
            WNBATotalsProjections(
                game_date=d,
                home_team_name=HOME,
                away_team_name=AWAY,
                projected_total=168.5,
                market_total=165.5,
                recommendation=rec,
            )
        )
    # NO_PLAY and UNDER (price NULL) skipped; OVER row is on another day.
    assert run(WNBATotalsSource(sqlite_db).get_todays_projections(RANGE)) == []


def test_spread_home_with_aware_game_time_and_provider(sqlite_db):
    _gl(sqlite_db, game_time=TIP.replace(tzinfo=timezone.utc))
    sqlite_db.add(
        WNBASpreadProjections(
            game_date=DAY,
            home_team_name=HOME,
            away_team_name=AWAY,
            projected_margin=4.5,
            home_win_prob=0.62,
            market_spread_home=-3.5,
            recommendation="HOME",
            created_at=CREATED,
        )
    )
    r = run(WNBASpreadSource(sqlite_db).get_todays_projections(RANGE))
    assert r[0]["side"] == "home" and r[0]["spread_odds"] == -110
    assert r[0]["commence_time"] == TIP
    c = run(SpreadCandidateProvider(_src(r)).get_candidates(RANGE))[0]
    assert c.projection_metadata["side"] == "home"
    assert c.game_date == DAY and c.commence_time == TIP


def test_spread_skips_without_game_line_or_recommendation(sqlite_db):
    _gl(sqlite_db)
    sqlite_db.add(
        WNBASpreadProjections(
            game_date=DAY,
            home_team_name=HOME,
            away_team_name=AWAY,
            projected_margin=0.5,
            home_win_prob=0.5,
            market_spread_home=-3.5,
            recommendation="NO_PLAY",
        )
    )
    sqlite_db.add(
        WNBASpreadProjections(
            game_date=DAY,
            home_team_name="A",
            away_team_name="B",
            projected_margin=9,
            home_win_prob=0.7,
            market_spread_home=-3.5,
            recommendation="HOME",
        )
    )
    assert run(WNBASpreadSource(sqlite_db).get_todays_projections(RANGE)) == []


def _prop(model, attr, pid, **kw):
    vals = dict(
        date=DAY,
        player_id=pid,
        player_name=f"P{pid}",
        opponent_team_name=HOME,  # player is on the road team
        market_line=20.5,
        fanduel_price=-120,
        recommendation="OVER",
        confidence_score=80.0,
        created_at=CREATED,
    )
    vals.update(kw)
    return model(**{attr: 22.5, **vals})


def test_props_stats_teams_and_skips(sqlite_db):
    _gl(sqlite_db)
    sqlite_db.add_all(
        [
            _prop(WNBAPointsProjections, "projected_points", 1),
            _prop(
                WNBAThreePtMadeProjections,
                "projected_three_pt_made",
                2,
                recommendation="UNDER",
            ),
            _prop(WNBAPRAProjections, "projected_pra", 3),
            _prop(WNBAPointsProjections, "projected_points", 4, market_line=None),
            _prop(WNBAPointsProjections, "projected_points", 8, fanduel_price=None),
            _prop(
                WNBAPointsProjections, "projected_points", 5, recommendation="NO_PLAY"
            ),
            _prop(
                WNBAPointsProjections,
                "projected_points",
                6,
                opponent_team_name="Nowhere",
            ),
            _prop(WNBAPointsProjections, "projected_points", 7, date=OTHER),
        ]
    )
    r = run(WNBAPlayerPropSource(sqlite_db).get_todays_projections(RANGE))
    by = {x["player"]: x for x in r}
    assert set(by) == {"P1", "P2", "P3"}
    assert by["P1"]["stat"] == "points" and by["P1"]["side"] == "over"
    assert by["P2"]["stat"] == "threes" and by["P2"]["side"] == "under"
    assert by["P3"]["stat"] == "pra"
    p = by["P1"]
    assert p["odds"] == -120 and p["odds_assumed"] is False
    assert (p["home_team_name"], p["away_team_name"]) == (HOME, AWAY)
    assert p["team"] == AWAY and p["opponent"] == HOME
    assert p["commence_time"] == TIP and p["game_date"] == DAY
    assert p["generated_at"] == CREATED and p["event_id"] == "wevt-1"
    c = run(PlayerPropCandidateProvider(_src([p])).get_candidates(RANGE))[0]
    assert c.projection_metadata["side"] == "over"
    assert c.game_date == DAY and c.commence_time == TIP
    assert c.home_team == HOME and c.away_team == AWAY
