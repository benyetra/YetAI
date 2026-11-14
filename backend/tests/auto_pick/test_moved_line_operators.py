"""moved_line_edge plays exactly when the league's projector would, at and around the threshold."""

import pytest

from app.services.auto_pick.candidate import moved_line_edge
from app.services.auto_pick.sources._basketball import (
    _spread_threshold,
    _totals_threshold,
)
from app.services.etl._spread_model import (
    NBA_CONFIG,
    NFL_CONFIG,
    WNBA_CONFIG,
    spread_recommendation,
)
from app.services.etl.nba.totals_baseline import recommend as nba_recommend
from app.services.etl.nfl.totals_projector import _totals_recommendation

SIDES = {"HOME": "home", "AWAY": "away", "OVER": "over", "UNDER": "under"}


def _wnba_totals(projected, line):  # inline in etl/wnba/totals_projector.py: edge > 2
    edge = projected - line
    return "OVER" if edge > 2 else "UNDER" if edge < -2 else "NO_PLAY"


@pytest.mark.parametrize("delta", [-0.5, 0.0, 0.5])
@pytest.mark.parametrize("sign", [1, -1])
def test_spread_matches_projector(delta, sign):
    for cfg, league in ((NBA_CONFIG, "NBA"), (WNBA_CONFIG, "WNBA"), (NFL_CONFIG, None)):
        thr = cfg.edge_threshold if league is None else _spread_threshold(league)
        assert thr == cfg.edge_threshold
        margin, spread_home = 10.0, -10.0 + sign * (
            thr + delta
        )  # edge = sign*(thr+delta)
        _, rec = spread_recommendation(margin, spread_home, cfg=cfg)
        for side in ("home", "away"):
            got = moved_line_edge("spread", side, margin, spread_home, thr)
            assert (got is not None) == (SIDES.get(rec) == side), (cfg, side, delta)


@pytest.mark.parametrize("delta", [-0.5, 0.0, 0.5])
@pytest.mark.parametrize("sign", [1, -1])
def test_totals_match_projectors(delta, sign):
    proj = 220.0
    cases = {
        # a proven record: the threshold, not the record gate, decides
        "NBA": (lambda l: nba_recommend(proj - l, (70, 100))[0], False),
        "WNBA": (lambda l: _wnba_totals(proj, l), True),
        "NFL": (lambda l: _totals_recommendation(proj, l)[1], False),
    }
    for league, (rec_fn, strict) in cases.items():
        thr = _totals_threshold("NBA" if league == "NBA" else "WNBA")
        if league == "NFL":
            thr = 3.0
        line = proj - sign * (thr + delta)
        rec = rec_fn(line)
        for side in ("over", "under"):
            got = moved_line_edge("total", side, proj, line, thr, strict=strict)
            assert (got is not None) == (SIDES.get(rec) == side), (league, side, delta)
