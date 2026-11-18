"""Side rules (plan.md "Side and projection rules") + ``consensus_price.best_fields`` for the
projection writers, so every writer picks the side and the on-side test the same way."""

from __future__ import annotations

import logging
from typing import Optional

from app.services import consensus_price


def _none_if_equal(projection: float, line: float) -> Optional[str]:
    return None if projection == line else ("o" if projection > line else "u")


def line_fields(
    db, *, event_id, market: str, projection, line, player=None, now=None
) -> dict:
    """best_* for a total or a prop: over if projection > line, under if <, else none."""
    side = None
    if projection is not None and line is not None:
        side = _none_if_equal(projection, line)
    p = projection
    return consensus_price.best_fields(
        db,
        event_id=event_id,
        market=market,
        side=side,
        side_name={"o": "over", "u": "under"}.get(side),
        on_side=(lambda l: p > l) if side == "o" else (lambda l: p < l),
        player=player,
        now=now,
    )


def spread_fields(db, *, event_id, margin, spread_home, now=None) -> dict:
    """best_* for the spread: home if margin + h > 0, away if < 0. Quote lines are the
    HOME point."""
    side = None
    if margin is not None and spread_home is not None:
        side = _none_if_equal(margin + spread_home, 0)
    m = margin
    return consensus_price.best_fields(
        db,
        event_id=event_id,
        market="spreads",
        side=side,
        side_name={"o": "home", "u": "away"}.get(side),
        on_side=(lambda h: m + h > 0) if side == "o" else (lambda h: m + h < 0),
        now=now,
    )


def moneyline_fields(db, *, event_id, margin, spread_home, now=None) -> dict:
    """ml_best_*: home if margin > the market margin (-spread_home), away if <."""
    side = None
    if margin is not None and spread_home is not None:
        side = _none_if_equal(margin, -spread_home)
    return consensus_price.best_fields(
        db,
        event_id=event_id,
        market="h2h",
        side=side,
        side_name={"o": "home", "u": "away"}.get(side),
        prefix="ml_best_",
        with_line=False,
        now=now,
    )


# The three books the NFL yards props stored lines from before the books were widened:
# the legacy ou_line / odds / best_*_book columns still read only these (matched by
# bookmaker key, not title), so stored lines and published yards do not change.
LEGACY_NFL_PROP_BOOKS = frozenset({"fanduel", "draftkings", "betmgm"})


def nfl_event_id(db, game_date, *team_names) -> Optional[str]:
    """Odds API event id of the NFL game on ``game_date`` involving any of the teams."""
    from app.models.predictions_models import NFLGameLines as G

    if game_date is None:
        return None
    day = game_date.date() if hasattr(game_date, "date") else game_date
    wanted = {t for t in team_names if t}
    for g in db.query(G).filter(G.game_date == day).all():
        if g.home_team_name in wanted or g.away_team_name in wanted:
            return g.odds_api_event_id
    return None


def nfl_prop_fields(db, row, *, market, projection, line, player) -> dict:
    """best_* for an NFL yards prop row (needs game_date, team_name, opponent_team_name).
    A failed event lookup is no consensus, never a failed write."""
    try:
        event_id = nfl_event_id(
            db, row.game_date, row.team_name, row.opponent_team_name
        )
    except Exception:
        logging.getLogger(__name__).exception("nfl_event_id failed for %s", player)
        event_id = None
    return line_fields(
        db,
        event_id=event_id,
        market=market,
        projection=projection,
        line=line,
        player=player,
    )
