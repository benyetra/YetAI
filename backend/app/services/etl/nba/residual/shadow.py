"""Daily shadow writer: residual-model predictions for today's lined NBA props.

Writes only ``pred_nba_prop_shadow``. It never touches a projection row, the pick
side, or anything auto-pick reads, and never raises into the pipeline.
"""

from __future__ import annotations

import logging
import os
import pickle  # nosec B403 - artifacts from our own private S3 bucket / local dir
from datetime import datetime

import pandas as pd

from app.models.predictions_models import (
    NBAPropShadow,
    PlayerInjuryStatus,
    TodayActivePlayers,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nba._stale_rows import active_players_not_started
from app.services.etl.nba.residual import dataset
from app.services.ml.model_store import S3Object

logger = logging.getLogger(__name__)

STATS = ("rebounds", "assists")
FEATURE_LOOKBACK_DAYS = 300  # season-to-date features need the whole season
_S3: dict[str, S3Object] = {}


def _enabled() -> bool:
    return os.getenv("NBA_RESIDUAL_SHADOW_ENABLED", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def load_model(stat: str):
    """Pickled ResidualModel from NBA_RESIDUAL_MODEL_DIR, else S3; None if absent."""
    name = f"residual_{stat}.pkl"
    local = os.getenv("NBA_RESIDUAL_MODEL_DIR")
    if local:
        path = os.path.join(local, name)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return pickle.load(f)  # nosec B301
    if stat not in _S3:
        _S3[stat] = S3Object(f"nba/ml_models/{name}", pickle.loads)  # nosec B301
    return _S3[stat].get()


def _num(v):
    return None if v is None or pd.isna(v) else float(v)


def _int(v):
    return None if v is None or pd.isna(v) else int(round(float(v)))


def _features_json(row: pd.Series, columns) -> dict:
    return {c: (None if pd.isna(row[c]) else float(row[c])) for c in columns}


def _run_stat(
    db, stat, today, model, inputs, active, players, out_ids, n_started
) -> dict:
    counts = {"written": 0, "updated": 0, "skipped_started": 0, "no_line": 0}
    rows = dataset.serve_rows(inputs, stat, today, active, out_ids)
    lined = rows[rows["line"].notna() & (rows["line"] > 0)]
    counts["no_line"] = len(rows) - len(lined)
    counts["skipped_started"] = n_started
    if lined.empty:
        return counts
    pred, p_over = model.predict(lined)
    names = {p.player_id: p.player_name for p in players}
    existing = {
        r.player_id: r
        for r in db.query(NBAPropShadow).filter(
            NBAPropShadow.date == today, NBAPropShadow.stat == stat
        )
    }
    now = datetime.utcnow()
    version = (model.version or f"resid-{stat}")[:64]
    for (_, r), pr, po in zip(lined.iterrows(), pred, p_over):
        vals = dict(
            player_name=(names.get(int(r.player_id)) or "")[:100] or None,
            line=float(r.line),
            line_source=(str(r.line_source)[:64] if pd.notna(r.line_source) else None),
            over_price=_int(r.over_price),
            under_price=_int(r.under_price),
            best_over_price=_int(r.best_over_price),
            best_under_price=_int(r.best_under_price),
            pred_residual=float(pr),
            p_over=float(po),
            model_version=version,
            features=_features_json(r, model.features),
            updated_at=now,
        )
        row = existing.get(int(r.player_id))
        if row is None:
            db.add(
                NBAPropShadow(
                    date=today,
                    player_id=int(r.player_id),
                    stat=stat,
                    created_at=now,
                    **vals,
                )
            )
            counts["written"] += 1
        else:
            for k, v in vals.items():
                setattr(row, k, v)
            counts["updated"] += 1
    db.commit()
    return counts


def run(today=None, *, db=None, now: datetime | None = None) -> dict:
    """Write today's shadow rows. Returns per-stat counts; never raises."""
    if not _enabled():
        return {"status": "disabled"}
    own = db is None
    result: dict = {"status": "ok"}
    try:
        if own:
            from app.core.database import SessionLocal

            db = SessionLocal()
        today = today or now_eastern().date()
        players = active_players_not_started(db, today, now=now)
        n_started = db.query(TodayActivePlayers).filter(
            TodayActivePlayers.game_date == today
        ).count() - len(players)
        active = pd.DataFrame(
            [
                dict(
                    player_id=p.player_id,
                    team_id=p.team_id,
                    opponent_team_id=p.opponent_team_id,
                    is_home_game=p.is_home_game,
                )
                for p in players
            ],
            columns=["player_id", "team_id", "opponent_team_id", "is_home_game"],
        )
        out_ids = [
            r[0]
            for r in db.query(PlayerInjuryStatus.player_id).filter(
                PlayerInjuryStatus.status.in_(["out", "ir", "doubtful"])
            )
        ]
        inputs = None
        for stat in STATS:
            try:
                model = load_model(stat)
                if model is None:
                    result[stat] = {"status": "no_model"}
                    continue
                if inputs is None:
                    start = pd.Timestamp(today) - pd.Timedelta(
                        days=FEATURE_LOOKBACK_DAYS
                    )
                    inputs = dataset.load_inputs(db.connection(), start, today)
                result[stat] = _run_stat(
                    db, stat, today, model, inputs, active, players, out_ids, n_started
                )
            except Exception as e:  # one stat's failure must not stop the other
                logger.exception("residual shadow %s failed", stat)
                db.rollback()
                result[stat] = {"status": "error", "error": f"{type(e).__name__}: {e}"}
                result["status"] = "error"
    except Exception as e:
        logger.exception("residual shadow failed")
        result = {"status": "error", "error": f"{type(e).__name__}: {e}"}
    finally:
        if own and db is not None:
            db.close()
    return result
