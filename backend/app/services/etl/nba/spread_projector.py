"""NBA spread / win-probability projector.

Primary: XGBoost margin model when S3 artifact is present (player-availability features).
Fallback: Elo + pace overlay (ported from WNBA).
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Iterable, List, Optional, Tuple

from app.core.database import SessionLocal
from app.models.predictions_models import (
    NBAGameLines,
    NBASpreadActuals,
    NBASpreadProjections,
    TeamDefenseStats,
    TeamOffenseStats,
)
from app.services.etl import _spread_model as _sm
from app.services.etl._game_start import not_started
from app.services.etl._spread_model import (
    NBA_CONFIG,
    load_elos_from_actuals,
    spread_recommendation,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nba._season import season_opener
from app.services.etl.nba._spread_features import build_game_features
from app.services.etl.nba._spread_ml_predict import (
    get_model_version,
    model_available,
    predict_margin,
)
from app.services.etl.nba.market_anchor import anchored, fit_anchor
from app.services.etl.nba.totals_baseline import recommend
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.ml_model_version import s3_object_version_date

logger = logging.getLogger(__name__)

INITIAL_ELO = NBA_CONFIG.initial_elo
HOME_COURT_ADVANTAGE = NBA_CONFIG.home_court_advantage

# Stamped on every row; the call record counts only rows of this version
# (column is String(20)). Published margin = market + k * (model - market),
# fitted walk-forward (market_anchor.fit_anchor); chosen in
# scripts/nba_game_model_replay.py: the raw model lost to the line.
SPREAD_MODEL_VERSION = "spread-anchor-v1"
SPREAD_ANCHOR_WINDOW = 400
SPREAD_ANCHOR_K_PRIOR = 400
SPREAD_ANCHOR_A_PRIOR = None


def _graded(db, *columns):
    """Projection rows joined to their final margin."""
    P, A = NBASpreadProjections, NBASpreadActuals
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
    P = NBASpreadProjections
    rows = (
        _graded(db, P.projected_margin, P.market_spread_home, P.factors)
        .filter(P.game_date < before, P.market_spread_home.isnot(None))
        .order_by(P.game_date.asc(), P.id.asc())
        .all()
    )
    out = []
    for margin, spread, factors, actual in rows:
        if isinstance(factors, str):
            try:
                factors = json.loads(factors)
            except ValueError:
                factors = None
        model = (
            (factors or {}).get("model_margin") if isinstance(factors, dict) else None
        )
        out.append((margin if model is None else model, -spread, actual))
    return out


def spread_pick_record(rows: Iterable, min_edge: float) -> Tuple[int, int]:
    """(hits, picks) of the side the published margin takes against the line.

    rows: projected_margin, market_spread_home, actual_margin. Rows with a
    missing value, |edge| < min_edge, or a push are skipped."""
    hits = picks = 0
    for r in rows:
        if (
            r.projected_margin is None
            or r.market_spread_home is None
            or r.actual_margin is None
        ):
            continue
        edge = r.projected_margin + r.market_spread_home
        cover = r.actual_margin + r.market_spread_home
        if abs(edge) < min_edge or cover == 0:
            continue
        picks += 1
        hits += (edge > 0) == (cover > 0)
    return hits, picks


def version_pick_record(db, start: date, end_exclusive: date) -> Tuple[int, int]:
    """spread_pick_record over this model version's graded rows in [start, end)."""
    P = NBASpreadProjections
    rows = (
        _graded(db, P.projected_margin, P.market_spread_home)
        .filter(
            P.model_version == SPREAD_MODEL_VERSION,
            P.game_date >= start,
            P.game_date < end_exclusive,
        )
        .all()
    )
    return spread_pick_record(rows, NBA_CONFIG.edge_threshold)


def _load_elos(db) -> dict[str, float]:
    actuals = (
        db.query(NBASpreadActuals).order_by(NBASpreadActuals.game_date.asc()).all()
    )
    return load_elos_from_actuals(actuals, cfg=NBA_CONFIG)


def run() -> dict:
    today = now_eastern().date()
    end = today + timedelta(days=1)
    use_ml = model_available()
    ml_version = None
    if use_ml:
        # Same fallback as the props: manifest/metadata tag, else the S3 object's date.
        ml_version = get_model_version()
        if not ml_version:
            day = s3_object_version_date("nba/ml_models/xgb_spread.pkl")
            ml_version = f"xgb-{day}" if day else "ml-unversioned"

    db = SessionLocal()
    upsert_rows: list[dict] = []
    try:
        elos = _load_elos(db)
        offense_by_name = {o.team_name: o for o in db.query(TeamOffenseStats).all()}
        defense_by_name = {d.team_name: d for d in db.query(TeamDefenseStats).all()}

        anchor = fit_anchor(
            spread_anchor_history(db, today),
            window=SPREAD_ANCHOR_WINDOW,
            k_prior=SPREAD_ANCHOR_K_PRIOR,
            a_prior=SPREAD_ANCHOR_A_PRIOR,
        )
        record = version_pick_record(db, season_opener(today), today)

        games = (
            db.query(NBAGameLines)
            .filter(NBAGameLines.game_date >= today, NBAGameLines.game_date <= end)
            .all()
        )

        for g in not_started(games, lambda g: (g.game_time, g.game_date)):
            home_elo = elos.get(g.home_team_name, INITIAL_ELO)
            away_elo = elos.get(g.away_team_name, INITIAL_ELO)
            base_margin = _sm.expected_margin(home_elo, away_elo, cfg=NBA_CONFIG)

            home_off = offense_by_name.get(g.home_team_name)
            home_def = defense_by_name.get(g.home_team_name)
            away_off = offense_by_name.get(g.away_team_name)
            away_def = defense_by_name.get(g.away_team_name)
            pace_adj = _sm.pace_overlay_adjustment(
                home_off.points_per_game if home_off else None,
                home_def.points_allowed_per_game if home_def else None,
                away_off.points_per_game if away_off else None,
                away_def.points_allowed_per_game if away_def else None,
                cfg=NBA_CONFIG,
            )

            elo_pace_margin = base_margin + pace_adj
            projection_method = "elo_pace"
            model_margin = elo_pace_margin

            if use_ml:
                feats = build_game_features(
                    db,
                    game_date=g.game_date,
                    home_team_name=g.home_team_name,
                    away_team_name=g.away_team_name,
                    home_team_id=g.home_team_id,
                    away_team_id=g.away_team_id,
                    market_spread_home=g.spread_home,
                    market_total=g.total,
                    spread_actuals_model=NBASpreadActuals,
                )
                if feats is not None:
                    ml_margin = predict_margin(feats)
                    if ml_margin is not None:
                        model_margin = ml_margin
                        projection_method = "ml"

            market_margin = None if g.spread_home is None else -g.spread_home
            projected_margin = anchored(model_margin, market_margin, anchor)
            home_win_prob = _sm.margin_to_win_prob(projected_margin, cfg=NBA_CONFIG)
            edge, _ = spread_recommendation(
                projected_margin, g.spread_home, cfg=NBA_CONFIG
            )
            recommendation, confidence, note = recommend(
                edge,
                record,
                min_edge=NBA_CONFIG.edge_threshold,
                sides=("HOME", "AWAY"),
            )

            upsert_rows.append(
                {
                    "game_date": g.game_date,
                    "home_team_id": g.home_team_id,
                    "away_team_id": g.away_team_id,
                    "home_team_name": g.home_team_name,
                    "away_team_name": g.away_team_name,
                    "projected_margin": projected_margin,
                    "home_win_prob": home_win_prob,
                    "home_elo": home_elo,
                    "away_elo": away_elo,
                    "home_court_advantage": HOME_COURT_ADVANTAGE,
                    "pace_adjustment": pace_adj,
                    "market_spread_home": g.spread_home,
                    "edge": edge,
                    "recommendation": recommendation,
                    "confidence_score": confidence,
                    "factors": {
                        "elo_diff": home_elo - away_elo,
                        "pace_adj": pace_adj,
                        "elo_pace_margin": elo_pace_margin,
                        "method": projection_method,
                        "model_margin": model_margin,
                        "market_margin": market_margin,
                        "market_win_prob": (
                            None
                            if market_margin is None
                            else _sm.margin_to_win_prob(market_margin, cfg=NBA_CONFIG)
                        ),
                        "anchor": anchor._asdict(),
                        "ml_version": ml_version if projection_method == "ml" else None,
                        "pick_record": list(record),
                        "recommendation_note": note,
                    },
                    "model_version": SPREAD_MODEL_VERSION,
                    "created_at": datetime.utcnow(),
                }
            )
        upsert_many(
            db,
            NBASpreadProjections,
            upsert_rows,
            conflict_keys=["game_date", "home_team_name", "away_team_name"],
        )
        db.commit()
        return {
            "status": "ok",
            "games": len(upsert_rows),
            "projection_method": "ml" if use_ml else "elo_pace",
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
