import asyncio

from app.models.predictions_models import PointsProjections
from app.services.auto_pick.providers.player_prop_provider import (
    PlayerPropCandidateProvider,
)
from app.services.auto_pick.sources.player_prop_source import PlayerPropSource
from tests.auto_pick.test_sources_nba import AWAY, DAY, RANGE, _gl


def _cands(db):
    p = PlayerPropCandidateProvider(PlayerPropSource(db))
    return {
        c.projection_metadata["player"]: c for c in asyncio.run(p.get_candidates(RANGE))
    }


def test_best_quote_replaces_fanduel_and_falls_back(sqlite_db):
    _gl(sqlite_db)
    common = dict(date=DAY, opponent_team_name=AWAY, projected_points=29.0)
    sqlite_db.add_all(
        [
            PointsProjections(
                player_id=1,
                player_name="Has Best",
                fanduel_line=26.5,
                fanduel_over_under="o",
                fanduel_price=-125,
                best_book="draftkings",
                best_line=25.5,
                best_price=-105,
                **common,
            ),
            PointsProjections(
                player_id=2,
                player_name="Fanduel Only",
                fanduel_line=27.5,
                fanduel_over_under="o",
                fanduel_price=-115,
                **common,
            ),
            PointsProjections(  # neither price -> skipped
                player_id=3,
                player_name="No Price",
                fanduel_line=27.5,
                fanduel_over_under="o",
                **common,
            ),
        ]
    )
    sqlite_db.commit()
    c = _cands(sqlite_db)
    assert set(c) == {"Has Best", "Fanduel Only"}
    best = c["Has Best"]
    assert (best.market_line, best.market_odds) == (25.5, -105)
    assert best.projection_metadata["book"] == "draftkings"
    assert best.selection == "Has Best OVER 25.5 points"
    fd = c["Fanduel Only"]
    assert (fd.market_line, fd.market_odds) == (27.5, -115)
    assert fd.projection_metadata["book"] == "fanduel"
