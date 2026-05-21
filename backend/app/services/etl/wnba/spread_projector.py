"""WNBA spread / win-probability projector.

Elo-based prior with pace/efficiency overlay. NEW vs NBA — no equivalent in
app/services/etl/nba/. Spec: docs/superpowers/specs/2026-05-21-wnba-support-design.md
(Section 4b).

Pipeline:
1. Load each team's current Elo rating (computed from completed games this season).
2. For each upcoming game with a market line, compute expected margin from Elo +
   HCA, refine via pace/efficiency overlay using offense/defense ratings.
3. Project win probability from margin via a logistic curve.
4. Compute edge against market spread; recommend HOME / AWAY / NO_PLAY.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBAGameLines,
    WNBASpreadActuals,
    WNBASpreadProjections,
    WNBATeamDefenseStats,
    WNBATeamOffenseStats,
)
from app.services.etl.wnba._espn import now_eastern

logger = logging.getLogger(__name__)

# --- Tunable constants — flagged for empirical re-verification on first run ---
INITIAL_ELO = 1500.0
ELO_K = 20.0
SEASON_DECAY = 0.75
HOME_COURT_ADVANTAGE = 2.5
SPREAD_PER_ELO = 25.0           # 25 Elo points ≈ 1 expected margin point
WIN_PROB_LOGISTIC_SCALE = 7.0   # logistic scale parameter for margin → win prob
EDGE_THRESHOLD = 2.0


# ---- Elo math ----

def expected_score(rating_a: float, rating_b: float) -> float:
    """Probability that team A beats team B per Elo formula."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def update_elo(home_elo: float, away_elo: float, home_score: int, away_score: int) -> tuple[float, float]:
    """Return updated (home_elo, away_elo) after a completed game."""
    home_won = 1.0 if home_score > away_score else 0.0
    # Adjust for home court when computing expected score.
    expected_home = expected_score(
        home_elo + HOME_COURT_ADVANTAGE * SPREAD_PER_ELO, away_elo
    )
    delta = ELO_K * (home_won - expected_home)
    return home_elo + delta, away_elo - delta


def expected_margin(home_elo: float, away_elo: float) -> float:
    """Expected margin of victory (positive = home favored), incl. HCA."""
    elo_diff_margin = (home_elo - away_elo) / SPREAD_PER_ELO
    return elo_diff_margin + HOME_COURT_ADVANTAGE


def margin_to_win_prob(margin: float) -> float:
    """Logistic curve: 0 margin → 0.5, +7 → ~0.73, -7 → ~0.27."""
    return 1.0 / (1.0 + math.exp(-margin / WIN_PROB_LOGISTIC_SCALE))


# ---- Pace / efficiency overlay ----

def pace_overlay_adjustment(
    home_off: float | None,
    home_def: float | None,
    away_off: float | None,
    away_def: float | None,
) -> float:
    """Tiny tilt added to Elo margin: rating mismatches favor home.

    Each team's offensive vs opposing defensive rating produces a small margin
    nudge so totals and spread move consistently.
    """
    if None in (home_off, home_def, away_off, away_def):
        return 0.0
    home_advantage = (home_off - away_def) - (away_off - home_def)
    return home_advantage * 0.15  # damp the contribution heavily


def _load_elos(db) -> dict[str, float]:
    """Compute current Elo for every WNBA team by replaying completed games."""
    elos: dict[str, float] = {}
    actuals = (
        db.query(WNBASpreadActuals)
        .order_by(WNBASpreadActuals.game_date.asc())
        .all()
    )
    for game in actuals:
        h = elos.setdefault(game.home_team_name, INITIAL_ELO)
        a = elos.setdefault(game.away_team_name, INITIAL_ELO)
        new_h, new_a = update_elo(h, a, game.home_score, game.away_score)
        elos[game.home_team_name] = new_h
        elos[game.away_team_name] = new_a
    return elos


# ---- Orchestration ----

def run() -> dict:
    today = now_eastern().date()
    end = today + timedelta(days=1)

    db = SessionLocal()
    written = 0
    try:
        elos = _load_elos(db)

        offense_by_name = {o.team_name: o for o in db.query(WNBATeamOffenseStats).all()}
        defense_by_name = {d.team_name: d for d in db.query(WNBATeamDefenseStats).all()}

        games = (
            db.query(WNBAGameLines)
            .filter(WNBAGameLines.game_date >= today, WNBAGameLines.game_date <= end)
            .all()
        )

        for g in games:
            home_elo = elos.get(g.home_team_name, INITIAL_ELO)
            away_elo = elos.get(g.away_team_name, INITIAL_ELO)
            base_margin = expected_margin(home_elo, away_elo)

            home_off = offense_by_name.get(g.home_team_name)
            home_def = defense_by_name.get(g.home_team_name)
            away_off = offense_by_name.get(g.away_team_name)
            away_def = defense_by_name.get(g.away_team_name)
            pace_adj = pace_overlay_adjustment(
                home_off.points_per_game if home_off else None,
                home_def.points_allowed_per_game if home_def else None,
                away_off.points_per_game if away_off else None,
                away_def.points_allowed_per_game if away_def else None,
            )

            projected_margin = base_margin + pace_adj
            home_win_prob = margin_to_win_prob(projected_margin)

            edge = None
            recommendation = "NO_PLAY"
            if g.spread_home is not None:
                # market_spread_home is negative when home is favored;
                # projected_margin is positive when home is favored — so the
                # implied market margin = -market_spread_home.
                implied_market_margin = -g.spread_home
                edge = projected_margin - implied_market_margin
                if edge >= EDGE_THRESHOLD:
                    recommendation = "HOME"
                elif edge <= -EDGE_THRESHOLD:
                    recommendation = "AWAY"

            obj = WNBASpreadProjections(
                game_date=g.game_date,
                home_team_id=g.home_team_id,
                away_team_id=g.away_team_id,
                home_team_name=g.home_team_name,
                away_team_name=g.away_team_name,
                projected_margin=projected_margin,
                home_win_prob=home_win_prob,
                home_elo=home_elo,
                away_elo=away_elo,
                home_court_advantage=HOME_COURT_ADVANTAGE,
                pace_adjustment=pace_adj,
                market_spread_home=g.spread_home,
                edge=edge,
                recommendation=recommendation,
                confidence_score=min(1.0, abs(edge) / 6.0) if edge is not None else None,
                factors={"elo_diff": home_elo - away_elo, "pace_adj": pace_adj},
                created_at=datetime.utcnow(),
            )
            db.merge(obj)
            written += 1
        db.commit()
        return {"status": "ok", "games": written}
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
