"""Auto-pick sources read the market-anchored NBA rows (NBA-2/7/8)."""

from app.models.predictions_models import (
    NBAGameLines,
    NBASpreadProjections,
    NBATotalsProjections,
)
from app.services.auto_pick.sources.nba_moneyline_source import NBAMoneylineSource
from tests.auto_pick.test_sources_nba import (
    AWAY,
    DAY,
    HOME,
    RANGE,
    _gl,
    _spread,
    _spread_rows,
    _total_rows,
    run,
)

ANCHOR = {"anchor": {"k": 0.05, "a": 0.0, "n": 200}}


def _margin(db, margin, factors):
    _spread(db, rec="HOME", factors=factors)
    db.query(NBASpreadProjections).update({"projected_margin": margin})


def _total(db, factors, edge=0.3):
    # anchored to 225.5, so projected = 225.8 and the stored edge is small
    db.add(
        NBATotalsProjections(
            game_date=DAY,
            home_team_name=HOME,
            away_team_name=AWAY,
            projected_total=225.5 + edge,
            market_total=225.5,
            edge=edge,
            recommendation="OVER",
            factors=factors,
        )
    )


def test_anchored_total_with_moved_line_makes_no_phantom_edge(sqlite_db):
    _gl(sqlite_db, total=228.5)  # +3 move; old rule: 225.8 - 228.5 -> UNDER 2.7
    _total(sqlite_db, ANCHOR)
    assert _total_rows(sqlite_db) == []


def test_anchored_total_reanchors_projection_on_pass(sqlite_db):
    _gl(sqlite_db, total=228.5)
    _total(sqlite_db, ANCHOR, edge=5.0)  # projected 230.5
    (r,) = _total_rows(sqlite_db)  # 230.5 + .95*3 = 233.35 vs 228.5 -> edge 4.85
    assert abs(r["projected_total"] - 233.35) < 1e-9
    assert abs(r["edge"] - 4.85) < 1e-9


def test_unanchored_total_keeps_old_moved_line_behaviour(sqlite_db):
    _gl(sqlite_db, total=222.5)  # projected 230.5 vs 222.5 -> 8.0
    _total(sqlite_db, None, edge=5.0)
    (r,) = _total_rows(sqlite_db)
    assert r["projected_total"] == 230.5 and abs(r["edge"] - 8.0) < 1e-9


def test_anchored_spread_with_moved_line_makes_no_phantom_edge(sqlite_db):
    _gl(sqlite_db, spread_home=-9.5)  # row anchored on -6.5; margin 6.8 -> HOME
    _margin(sqlite_db, 6.8, ANCHOR)
    # re-anchored margin 6.8 - .95*(-3) = 9.65; edge 0.15 < threshold
    assert _spread_rows(sqlite_db) == []


def test_unanchored_spread_keeps_old_moved_line_behaviour(sqlite_db):
    _gl(sqlite_db, spread_home=-9.5)
    _margin(sqlite_db, 6.8, None)
    # old rule: 6.8 - 9.5 = -2.7 -> HOME side edge negative -> dropped
    assert _spread_rows(sqlite_db) == []
    sqlite_db.query(NBASpreadProjections).delete()
    _margin(sqlite_db, 12.0, None)
    (r,) = _spread_rows(sqlite_db)
    assert r["projected_margin"] == 12.0


def _ml(db, hwp, market_p):
    _gl(db)  # no-vig home ~0.644
    f = None if market_p is None else {"market_win_prob": market_p}
    _spread(db, rec="NO_PLAY", hwp=hwp, factors=f)


def _ml_rows(db):
    return run(NBAMoneylineSource(db).get_todays_projections(RANGE))


def test_moneyline_needs_model_part_above_floor(sqlite_db):
    _ml(sqlite_db, 0.50, 0.49)  # edge vs ML -0.14 but model part only +0.01
    assert _ml_rows(sqlite_db) == []


def test_moneyline_dropped_without_market_win_prob(sqlite_db):
    _ml(sqlite_db, 0.50, None)
    assert _ml_rows(sqlite_db) == []


def test_moneyline_dropped_when_model_part_disagrees(sqlite_db):
    _ml(sqlite_db, 0.70, 0.60)  # edge vs ML +0.056 (home), model part +0.10: agrees
    assert len(_ml_rows(sqlite_db)) == 1
    sqlite_db.query(NBASpreadProjections).delete()
    _ml(sqlite_db, 0.70, 0.80)  # edge +0.056 home, model part -0.10: disagrees
    assert _ml_rows(sqlite_db) == []


def test_moneyline_keeps_candidate_with_model_edge(sqlite_db):
    _ml(sqlite_db, 0.50, 0.60)  # away on both
    (r,) = _ml_rows(sqlite_db)
    assert r["side"] == "away" and abs(r["model_edge"] - (-0.10)) < 1e-9


def test_moneyline_reanchors_win_prob_when_the_spread_moves(sqlite_db):
    # Projected on -6.5 with k=0.3: stored model part ~+0.03, a candidate. The live
    # line moved to -9.5, toward the model, so on that line the model adds ~0.005.
    from app.services.etl._spread_model import NBA_CONFIG, margin_to_win_prob

    k, old, new, model = 0.3, -6.5, -9.5, 10.0
    margin = -old + k * (model + old)
    _gl(sqlite_db, spread_home=new)
    _spread(
        sqlite_db,
        rec="NO_PLAY",
        hwp=margin_to_win_prob(margin, cfg=NBA_CONFIG),
        factors={
            "anchor": {"k": k, "a": 0.0, "n": 200},
            "market_win_prob": margin_to_win_prob(-old, cfg=NBA_CONFIG),
        },
    )
    sqlite_db.query(NBASpreadProjections).update(
        {"projected_margin": margin, "market_spread_home": old}
    )
    assert _ml_rows(sqlite_db) == []
    # Same row on an unmoved line is a candidate (the stale numbers were the issue).
    sqlite_db.query(NBAGameLines).update({"spread_home": old})
    assert len(_ml_rows(sqlite_db)) == 1


def test_moneyline_moved_line_without_anchor_is_dropped(sqlite_db):
    _gl(sqlite_db, spread_home=-4.5)
    _spread(sqlite_db, rec="NO_PLAY", hwp=0.9, factors={"market_win_prob": 0.6})
    assert _ml_rows(sqlite_db) == []
