"""NFL game totals (O/U) projections: PPG blend anchored to the line.

Same scheme as the NBA totals (PR #181): the raw PPG-blend total is kept in
factors["model_total"] and the published total is
market + a + k * (model - market), fitted walk-forward on graded NFL games.
Team scores are split from the published total and the published margin.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from types import SimpleNamespace
from typing import List, Tuple

from app.core.database import SessionLocal
from app.models.predictions_models import (
    NFLGameLines,
    NFLSpreadActuals,
    NFLTotalsProjections,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nba.market_anchor import NO_ANCHOR, Anchor, anchored, fit_anchor
from app.services.etl.nba.totals_baseline import pick_record, recommend
from app.services.etl.nfl._team_ppg import compute_team_ppg_stats, team_ppg_for
from app.services.etl.nfl.nfl_common import get_current_nfl_week, get_nfl_season
from app.services.etl.nfl.spread_projector import (
    _factor,
    _load_elos,
    _load_qb_out_by_team,
    _project_spread_row,
    apply_qb_out_for_game,
    projection_end_date,
    season_opener,
    spread_anchor_history,
    unstarted_games,
    version_pick_record as spread_version_pick_record,
    SPREAD_ANCHOR_A_PRIOR,
    SPREAD_ANCHOR_K_PRIOR,
    SPREAD_ANCHOR_WINDOW,
)
from app.services.etl.wnba._db_upsert import upsert_many

logger = logging.getLogger(__name__)

TOTALS_EDGE_THRESHOLD = 3.0

# Stamped on every row (column is String(20)); the call record counts only
# rows of this version.
TOTALS_MODEL_VERSION = "nfl-totals-anchor-v1"
# NOT tuned on data (no offline NFL data): same conservative shape as the NBA
# totals. ~272 games a season, so a 150-game window covers most of one; the
# priors act like 200 games of evidence for k = 0 and 100 for a = 0.
TOTALS_ANCHOR_WINDOW = 150
TOTALS_ANCHOR_K_PRIOR = 200
TOTALS_ANCHOR_A_PRIOR = 100


def _graded(db, *columns):
    """Totals projection rows joined to their final combined score."""
    P, A = NFLTotalsProjections, NFLSpreadActuals
    return db.query(*columns, A.home_score + A.away_score).join(
        A,
        (A.game_date == P.game_date)
        & (A.home_team_name == P.home_team_name)
        & (A.away_team_name == P.away_team_name),
    )


def totals_anchor_history(db, before: date) -> List[Tuple[float, float, float]]:
    """(model total, market total, actual total) of graded games before
    ``before``, oldest first. Older rows stored the raw model in
    projected_total; newer ones keep it in factors["model_total"]."""
    P = NFLTotalsProjections
    rows = (
        _graded(db, P.projected_total, P.market_total, P.factors)
        .filter(P.game_date < before, P.market_total.isnot(None))
        .order_by(P.game_date.asc(), P.home_team_name.asc(), P.away_team_name.asc())
        .all()
    )
    out = []
    for total, market, factors, actual in rows:
        model = _factor(factors, "model_total")
        out.append((total if model is None else model, market, actual))
    return out


def version_pick_record(db, start: date, end_exclusive: date) -> Tuple[int, int]:
    """pick_record over this version's graded rows in [start, end)."""
    P = NFLTotalsProjections
    rows = (
        _graded(db, P.projected_total, P.market_total)
        .filter(
            P.model_version == TOTALS_MODEL_VERSION,
            P.game_date >= start,
            P.game_date < end_exclusive,
        )
        .all()
    )
    return pick_record(
        [
            SimpleNamespace(projected_total=p, market_total=m, actual_total=a)
            for p, m, a in rows
        ],
        TOTALS_EDGE_THRESHOLD,
    )


def _project_matchup_score(off_ppg: float, opp_def_ppg: float) -> float:
    """Blend offensive and opposing defensive scoring rates."""
    return (off_ppg + opp_def_ppg) / 2.0


def _project_total_from_ppg(
    home_team_name: str,
    away_team_name: str,
    ppg_stats: dict[str, tuple[float, float]],
) -> tuple[float, float, float, float, float, float, float]:
    home_off, home_def = team_ppg_for(home_team_name, ppg_stats)
    away_off, away_def = team_ppg_for(away_team_name, ppg_stats)

    home_raw = _project_matchup_score(home_off, away_def)
    away_raw = _project_matchup_score(away_off, home_def)
    projected_total = home_raw + away_raw

    return (
        projected_total,
        home_raw,
        away_raw,
        home_off,
        away_off,
        home_def,
        away_def,
    )


def _align_scores(
    projected_margin: float, projected_total: float
) -> tuple[float, float]:
    """Split total into team scores consistent with home-perspective margin."""
    home_pts = (projected_total + projected_margin) / 2.0
    away_pts = (projected_total - projected_margin) / 2.0
    return home_pts, away_pts


def _totals_recommendation(
    projected_total: float,
    market_total: float | None,
    *,
    threshold: float = TOTALS_EDGE_THRESHOLD,
) -> tuple[float | None, str]:
    if market_total is None:
        return None, "NO_PLAY"
    edge = projected_total - market_total
    if edge >= threshold:
        return edge, "OVER"
    if market_total - projected_total >= threshold:
        return edge, "UNDER"
    return edge, "NO_PLAY"


def _project_totals_row(
    *,
    home_team_name: str,
    away_team_name: str,
    spread_home: float | None,
    market_total: float | None,
    elos: dict[str, float],
    ppg_stats: dict[str, tuple[float, float]],
    home_qb_out: bool = False,
    away_qb_out: bool = False,
    spread_anchor: Anchor = NO_ANCHOR,
    spread_record: Tuple[int, int] = (0, 0),
    anchor: Anchor = NO_ANCHOR,
    record: Tuple[int, int] = (0, 0),
) -> dict:
    spread = _project_spread_row(
        home_team_name=home_team_name,
        away_team_name=away_team_name,
        spread_home=spread_home,
        elos=elos,
        ppg_stats=ppg_stats,
        home_qb_out=home_qb_out,
        away_qb_out=away_qb_out,
        anchor=spread_anchor,
        record=spread_record,
    )
    # The published (anchored) margin, so the team scores agree with the spread.
    projected_margin = spread["projected_margin"]

    (
        projected_total,
        home_raw,
        away_raw,
        home_off,
        away_off,
        home_def,
        away_def,
    ) = _project_total_from_ppg(home_team_name, away_team_name, ppg_stats)

    model_total = projected_total
    projected_total = anchored(model_total, market_total, anchor)
    home_pts, away_pts = _align_scores(projected_margin, projected_total)
    edge, _ = _totals_recommendation(projected_total, market_total)
    recommendation, confidence, note = recommend(
        edge, record, min_edge=TOTALS_EDGE_THRESHOLD
    )

    return {
        "projected_total": projected_total,
        "home_projected_score": home_pts,
        "away_projected_score": away_pts,
        "base_projection": home_raw + away_raw,
        "home_offensive_rating": home_off,
        "away_offensive_rating": away_off,
        "home_defensive_rating": home_def,
        "away_defensive_rating": away_def,
        "market_total": market_total,
        "edge": edge,
        "recommendation": recommendation,
        "confidence_score": confidence,
        "factors": {
            "projected_margin": projected_margin,
            "home_raw": home_raw,
            "away_raw": away_raw,
            "method": "ppg_blend",
            "model_total": model_total,
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

        spread_anchor = fit_anchor(
            spread_anchor_history(db, today),
            window=SPREAD_ANCHOR_WINDOW,
            k_prior=SPREAD_ANCHOR_K_PRIOR,
            a_prior=SPREAD_ANCHOR_A_PRIOR,
        )
        spread_record = spread_version_pick_record(db, season_opener(today), today)
        anchor = fit_anchor(
            totals_anchor_history(db, today),
            window=TOTALS_ANCHOR_WINDOW,
            k_prior=TOTALS_ANCHOR_K_PRIOR,
            a_prior=TOTALS_ANCHOR_A_PRIOR,
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
            projection = _project_totals_row(
                home_team_name=g.home_team_name,
                away_team_name=g.away_team_name,
                spread_home=g.spread_home,
                market_total=g.total,
                elos=elos,
                ppg_stats=ppg_stats,
                home_qb_out=home_qb_out,
                away_qb_out=away_qb_out,
                spread_anchor=spread_anchor,
                spread_record=spread_record,
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
                    "model_version": TOTALS_MODEL_VERSION,
                    **projection,
                }
            )

        upsert_many(
            db,
            NFLTotalsProjections,
            upsert_rows,
            conflict_keys=["game_date", "home_team_name", "away_team_name"],
        )
        db.commit()
        return {"status": "ok", "games": len(upsert_rows)}
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
