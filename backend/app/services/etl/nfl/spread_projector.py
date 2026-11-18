"""NFL spread / win-probability projector (Elo + PPG overlay), anchored to the line.

Same scheme as the NBA (PR #181): the raw model margin is kept in
factors["model_margin"] and the published margin is
market + a + k * (model - market), with k and a fitted walk-forward on graded
NFL games (market_anchor.fit_anchor). A model with no measured information
publishes the line. Win probability comes from the published margin, and a
call is shown only once this version's own graded record clears breakeven.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import List, Tuple

from app.core.database import SessionLocal
from app.models.predictions_models import (
    NFLGameLines,
    NFLSpreadActuals,
    NFLSpreadProjections,
    NFLTeamElo,
    QBPredictions,
)
from app.services.etl import _spread_model as _sm
from app.services.etl._consensus_attach import moneyline_fields, spread_fields
from app.services.etl._game_start import not_started
from app.services.etl._spread_model import (
    NFL_CONFIG,
    load_elos_from_actuals,
    season_id_for_date,
    spread_recommendation,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nba.market_anchor import NO_ANCHOR, Anchor, anchored, fit_anchor
from app.services.etl.nba.spread_projector import spread_pick_record
from app.services.etl.nba.totals_baseline import recommend
from app.services.etl.nfl._team_ppg import compute_team_ppg_stats, team_ppg_for
from app.services.etl.nfl.nfl_common import (
    EARLIEST_KICKOFF_ET,
    get_current_nfl_week,
    get_nfl_season,
)
from app.services.etl.nfl.qb_spread_adjustment import (
    qb_out_map_from_rows,
    qb_out_margin_adjustment,
)
from app.services.etl.nfl.update_game_lines import GAME_LINES_HORIZON_DAYS
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)

INITIAL_ELO = NFL_CONFIG.initial_elo
HOME_COURT_ADVANTAGE = NFL_CONFIG.home_court_advantage

# Stamped on every row (column is String(20)); the call record counts only
# rows of this version.
SPREAD_MODEL_VERSION = "nfl-spread-anchor-v1"
# NOT tuned on data (no offline NFL data): conservative priors. An NFL season is
# ~272 games, so a 150-game window covers most of one; k_prior 200 keeps k near 0
# until the model shows a slope. No constant (a_prior None), as in the NBA.
SPREAD_ANCHOR_WINDOW = 150
SPREAD_ANCHOR_K_PRIOR = 200
SPREAD_ANCHOR_A_PRIOR = None


def _factor(factors, key):
    if isinstance(factors, str):
        try:
            factors = json.loads(factors)
        except ValueError:
            return None
    return factors.get(key) if isinstance(factors, dict) else None


def _graded(db, *columns):
    """Projection rows joined to their final margin."""
    P, A = NFLSpreadProjections, NFLSpreadActuals
    return db.query(*columns, A.actual_margin).join(
        A,
        (A.game_date == P.game_date)
        & (A.home_team_name == P.home_team_name)
        & (A.away_team_name == P.away_team_name),
    )


def spread_anchor_history(db, before: date) -> List[Tuple[float, float, float]]:
    """(model margin, market margin, actual margin) of graded games before
    ``before``, oldest first. Older rows stored the raw model in
    projected_margin; newer ones keep it in factors["model_margin"]."""
    P = NFLSpreadProjections
    rows = (
        _graded(db, P.projected_margin, P.market_spread_home, P.factors)
        .filter(P.game_date < before, P.market_spread_home.isnot(None))
        .order_by(P.game_date.asc(), P.home_team_name.asc(), P.away_team_name.asc())
        .all()
    )
    out = []
    for margin, spread, factors, actual in rows:
        model = _factor(factors, "model_margin")
        out.append((margin if model is None else model, -spread, actual))
    return out


def season_opener(today: date) -> date:
    """First day (1 Aug) of the NFL season ``today`` belongs to."""
    return date(
        season_id_for_date(today, cfg=NFL_CONFIG), NFL_CONFIG.season_start_month, 1
    )


def version_pick_record(db, start: date, end_exclusive: date) -> Tuple[int, int]:
    """spread_pick_record over this version's graded rows in [start, end)."""
    P = NFLSpreadProjections
    rows = (
        _graded(db, P.projected_margin, P.market_spread_home)
        .filter(
            P.model_version == SPREAD_MODEL_VERSION,
            P.game_date >= start,
            P.game_date < end_exclusive,
        )
        .all()
    )
    return spread_pick_record(rows, NFL_CONFIG.edge_threshold)


def projection_end_date(today: date) -> date:
    """Inclusive end of the game-board window; matches ``GAME_LINES_HORIZON_DAYS``."""
    return today + timedelta(days=GAME_LINES_HORIZON_DAYS)


def apply_qb_out_for_game(
    game_date: date | datetime,
    loaded_week: int,
    season: int,
    qb_out_by_team: dict[str, bool],
    *,
    home_team_name: str,
    away_team_name: str,
) -> tuple[bool, bool]:
    """Return home/away QB-out flags only when the game is in ``loaded_week``."""
    game_day = game_date.date() if isinstance(game_date, datetime) else game_date
    if get_current_nfl_week(season, today=game_day) != loaded_week:
        return False, False
    return (
        qb_out_by_team.get(home_team_name, False),
        qb_out_by_team.get(away_team_name, False),
    )


def unstarted_games(games: list, *, now: datetime | None = None) -> list:
    """Drop games whose kickoff has passed: their row and line stay as users saw them.

    ``game_time`` is naive UTC (written from the Odds API commence_time). A game
    with no ``game_time`` counts as started from the earliest NFL kickoff on its
    own ET game date, not only from the next day.
    """
    return not_started(
        games,
        lambda g: (g.game_time, g.game_date),
        now=now,
        day_start=EARLIEST_KICKOFF_ET,
    )


def _load_qb_out_by_team(
    db, *, season: int | None = None, week: int | None = None
) -> dict[str, bool]:
    """Map team_name → starter QB is out, from current-week ``pred_qb_predictions``."""
    season = season if season is not None else get_nfl_season()
    week = week if week is not None else get_current_nfl_week(season)
    rows = (
        db.query(QBPredictions)
        .filter(QBPredictions.season == season, QBPredictions.week == week)
        .all()
    )
    return qb_out_map_from_rows(rows)


def _load_elos(db) -> dict[str, float]:
    stored = db.query(NFLTeamElo).all()
    if stored:
        return {row.team_name: float(row.elo) for row in stored}

    actuals = (
        db.query(NFLSpreadActuals).order_by(NFLSpreadActuals.game_date.asc()).all()
    )
    if actuals:
        return load_elos_from_actuals(actuals, cfg=NFL_CONFIG)
    return {}


def _project_spread_row(
    *,
    home_team_name: str,
    away_team_name: str,
    spread_home: float | None,
    elos: dict[str, float],
    ppg_stats: dict[str, tuple[float, float]],
    home_qb_out: bool = False,
    away_qb_out: bool = False,
    anchor: Anchor = NO_ANCHOR,
    record: Tuple[int, int] = (0, 0),
) -> dict:
    home_elo = elos.get(home_team_name, INITIAL_ELO)
    away_elo = elos.get(away_team_name, INITIAL_ELO)
    base_margin = _sm.expected_margin(home_elo, away_elo, cfg=NFL_CONFIG)

    home_off, home_def = team_ppg_for(home_team_name, ppg_stats)
    away_off, away_def = team_ppg_for(away_team_name, ppg_stats)
    pace_adj = _sm.pace_overlay_adjustment(
        home_off, home_def, away_off, away_def, cfg=NFL_CONFIG
    )

    qb_out_adj = qb_out_margin_adjustment(
        home_qb_out=home_qb_out, away_qb_out=away_qb_out
    )
    elo_pace_margin = base_margin + pace_adj
    model_margin = elo_pace_margin + qb_out_adj
    market_margin = None if spread_home is None else -spread_home
    projected_margin = anchored(model_margin, market_margin, anchor)
    home_win_prob = _sm.margin_to_win_prob(projected_margin, cfg=NFL_CONFIG)
    edge, _ = spread_recommendation(projected_margin, spread_home, cfg=NFL_CONFIG)
    recommendation, confidence, note = recommend(
        edge, record, min_edge=NFL_CONFIG.edge_threshold, sides=("HOME", "AWAY")
    )

    return {
        "projected_margin": projected_margin,
        "home_win_prob": home_win_prob,
        "home_elo": home_elo,
        "away_elo": away_elo,
        "home_court_advantage": HOME_COURT_ADVANTAGE,
        "pace_adjustment": pace_adj,
        "market_spread_home": spread_home,
        "edge": edge,
        "recommendation": recommendation,
        "confidence_score": confidence,
        "factors": {
            "elo_diff": home_elo - away_elo,
            "pace_adj": pace_adj,
            "elo_pace_margin": elo_pace_margin,
            "qb_out_adj": qb_out_adj,
            "method": "elo_pace",
            "model_margin": model_margin,
            "market_margin": market_margin,
            "market_win_prob": (
                None
                if market_margin is None
                else _sm.margin_to_win_prob(market_margin, cfg=NFL_CONFIG)
            ),
            "anchor": anchor._asdict(),
            "pick_record": list(record),
            "recommendation_note": note,
        },
    }


def run() -> dict:
    today = now_eastern().date()
    end = projection_end_date(today)

    db = SessionLocal()
    upsert_rows: list[dict] = []
    try:
        elos = _load_elos(db)
        # Full actuals history still drives Elo; PPG is scoped to current-season
        # form (with early-season prior-year fallback) so multi-year seed data
        # does not drown mid-season pace.
        actuals = (
            db.query(NFLSpreadActuals).order_by(NFLSpreadActuals.game_date.asc()).all()
        )
        season = get_nfl_season()
        ppg_stats = compute_team_ppg_stats(actuals, season=season)
        loaded_week = get_current_nfl_week(season, today=today)
        qb_out_by_team = _load_qb_out_by_team(db, season=season, week=loaded_week)

        anchor = fit_anchor(
            spread_anchor_history(db, today),
            window=SPREAD_ANCHOR_WINDOW,
            k_prior=SPREAD_ANCHOR_K_PRIOR,
            a_prior=SPREAD_ANCHOR_A_PRIOR,
        )
        record = version_pick_record(db, season_opener(today), today)

        games = (
            db.query(NFLGameLines)
            .filter(NFLGameLines.game_date >= today, NFLGameLines.game_date <= end)
            .all()
        )
        games = unstarted_games(games)

        for g in games:
            home_qb_out, away_qb_out = apply_qb_out_for_game(
                g.game_date,
                loaded_week,
                season,
                qb_out_by_team,
                home_team_name=g.home_team_name,
                away_team_name=g.away_team_name,
            )
            projection = _project_spread_row(
                home_team_name=g.home_team_name,
                away_team_name=g.away_team_name,
                spread_home=g.spread_home,
                elos=elos,
                ppg_stats=ppg_stats,
                home_qb_out=home_qb_out,
                away_qb_out=away_qb_out,
                anchor=anchor,
                record=record,
            )
            upsert_rows.append(
                {
                    "game_date": g.game_date,
                    "home_team_id": g.home_team_id,
                    "away_team_id": g.away_team_id,
                    "home_team_name": g.home_team_name,
                    "away_team_name": g.away_team_name,
                    "created_at": datetime.utcnow(),
                    "model_version": SPREAD_MODEL_VERSION,
                    **projection,
                    # best book / same-line consensus price (None when no consensus)
                    **spread_fields(
                        db,
                        event_id=g.odds_api_event_id,
                        margin=projection["projected_margin"],
                        spread_home=g.spread_home,
                    ),
                    **moneyline_fields(
                        db,
                        event_id=g.odds_api_event_id,
                        margin=projection["projected_margin"],
                        spread_home=g.spread_home,
                    ),
                }
            )

        upsert_many(
            db,
            NFLSpreadProjections,
            upsert_rows,
            conflict_keys=["game_date", "home_team_name", "away_team_name"],
        )
        db.commit()
        return {
            "status": "ok",
            "games": len(upsert_rows),
            "projection_method": "elo_pace",
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
