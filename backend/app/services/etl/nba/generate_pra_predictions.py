"""PRA (points + rebounds + assists) combo projections from individual stat projections.

Port of YetiBets/scripts/nba/pra_predictions.py. Runs after points/rebounds/assists
tasks in the daily pipeline so pred_pra_projections is populated for the API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from app.core.database import SessionLocal
from app.models.predictions_models import (
    AssistsProjections,
    PlayerInjuryStatus,
    PointsProjections,
    PRAProjections,
    RecentGames,
    ReboundsProjections,
    TodayActivePlayers,
)
from app.services.etl.nba._espn import now_eastern
from app.services.etl.nba._fanduel_lines import get_event_id_for_game, get_fanduel_line

logger = logging.getLogger(__name__)

INJURY_SKIP_STATUSES = {"out", "ir", "doubtful"}
CORRELATION_ADJUSTMENT = 0.98


def _normalize_status(status_str: str | None) -> str:
    if not status_str:
        return "healthy"
    s = status_str.lower().strip()
    if s in INJURY_SKIP_STATUSES:
        return s
    return "healthy"


def _weighted_stat(recent_games: list, attr: str, min_games: int = 5) -> float | None:
    values = []
    for g in recent_games[:10]:
        val = getattr(g, attr, None)
        if val is not None and val >= 0:
            values.append(float(val))
    if len(values) < min_games:
        return None
    if len(values) >= 5:
        weights = [0.25, 0.20, 0.18, 0.15, 0.12, 0.05, 0.03, 0.01, 0.005, 0.005]
        weights = weights[: len(values)]
        weight_sum = sum(weights)
        weights = [w / weight_sum for w in weights]
        return sum(v * w for v, w in zip(values, weights))
    return sum(values) / len(values)


def _pra_floor_ceiling(
    recent_games: list, points: float, rebounds: float, assists: float
) -> tuple[float, float]:
    pra_proj = points + rebounds + assists
    pra_values = []
    for g in recent_games[:10]:
        pts = getattr(g, "points", 0) or 0
        reb = getattr(g, "rebounds", 0) or 0
        ast = getattr(g, "assists", 0) or 0
        if pts > 0 or reb > 0 or ast > 0:
            pra_values.append(pts + reb + ast)
    if len(pra_values) < 5:
        return pra_proj * 0.85, pra_proj * 1.15
    avg_pra = sum(pra_values) / len(pra_values)
    variance = sum((x - avg_pra) ** 2 for x in pra_values) / len(pra_values)
    std_dev = variance**0.5
    floor = max(5.0, pra_proj - 1.5 * std_dev)
    ceiling = pra_proj + 1.5 * std_dev
    return round(floor, 1), round(ceiling, 1)


def _get_component(
    db,
    model,
    field: str,
    player_id: int,
    game_date,
    recent_games: list,
    recent_attr: str,
) -> float | None:
    row = (
        db.query(model)
        .filter(model.player_id == player_id, model.date == game_date)
        .first()
    )
    if row:
        val = getattr(row, field, None)
        if val is not None:
            return float(val)
    return _weighted_stat(recent_games, recent_attr)


def _fanduel_pra_line(
    team_name: str, player_name: str, opponent_team_name: str, projection: float
) -> tuple[float | None, str | None]:
    event_id = get_event_id_for_game("basketball_nba", team_name, opponent_team_name)
    if not event_id:
        return None, None
    line, _price, flag = get_fanduel_line(
        "basketball_nba",
        event_id,
        player_name,
        "player_points_rebounds_assists",
        projection,
    )
    if line <= 0 or flag == "n":
        return None, None
    return line, flag


def run() -> dict:
    today = now_eastern().date()
    created = 0
    updated = 0
    skipped = 0
    errors = 0

    db = SessionLocal()
    try:
        db.query(PRAProjections).filter(PRAProjections.date == today).delete()
        db.commit()

        active = (
            db.query(TodayActivePlayers)
            .filter(TodayActivePlayers.game_date == today)
            .all()
        )
        if not active:
            logger.info("generate_pra_predictions: no active players for %s", today)
            return {
                "status": "ok",
                "date": today.isoformat(),
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "errors": 0,
            }

        cutoff = today - timedelta(days=30)
        db.query(PRAProjections).filter(PRAProjections.date < cutoff).delete()
        db.commit()

        for player in active:
            try:
                injury = (
                    db.query(PlayerInjuryStatus)
                    .filter(PlayerInjuryStatus.player_id == player.player_id)
                    .first()
                )
                if injury and (injury.status or "").lower() in INJURY_SKIP_STATUSES:
                    skipped += 1
                    continue

                recent = (
                    db.query(RecentGames)
                    .filter(RecentGames.player_id == player.player_id)
                    .order_by(RecentGames.game_date.desc())
                    .limit(30)
                    .all()
                )
                if not recent:
                    skipped += 1
                    continue

                games_with_data = [
                    g
                    for g in recent
                    if g.points is not None
                    and g.rebounds is not None
                    and g.assists is not None
                ]
                if len(games_with_data) < 5:
                    skipped += 1
                    continue

                recent_minutes = [
                    g.minutes for g in recent[:5] if g.minutes and g.minutes > 0
                ]
                avg_minutes = (
                    sum(recent_minutes) / len(recent_minutes) if recent_minutes else 0
                )
                if avg_minutes < 15:
                    skipped += 1
                    continue

                points = _get_component(
                    db,
                    PointsProjections,
                    "projected_points",
                    player.player_id,
                    today,
                    recent,
                    "points",
                )
                rebounds = _get_component(
                    db,
                    ReboundsProjections,
                    "projected_rebounds",
                    player.player_id,
                    today,
                    recent,
                    "rebounds",
                )
                assists = _get_component(
                    db,
                    AssistsProjections,
                    "projected_assists",
                    player.player_id,
                    today,
                    recent,
                    "assists",
                )
                if points is None or rebounds is None or assists is None:
                    skipped += 1
                    continue

                base_pra = points + rebounds + assists
                projected_pra = max(10.0, min(base_pra * CORRELATION_ADJUSTMENT, 80.0))
                if projected_pra < 15.0:
                    skipped += 1
                    continue

                pra_floor, pra_ceiling = _pra_floor_ceiling(
                    recent, points, rebounds, assists
                )
                fd_line, fd_flag = _fanduel_pra_line(
                    player.team_name,
                    player.player_name,
                    player.opponent_team_name,
                    projected_pra,
                )

                existing = (
                    db.query(PRAProjections)
                    .filter(
                        PRAProjections.date == today,
                        PRAProjections.player_id == player.player_id,
                    )
                    .first()
                )
                payload = {
                    "player_name": player.player_name,
                    "opponent_team_name": player.opponent_team_name,
                    "projected_points": round(points, 1),
                    "projected_rebounds": round(rebounds, 1),
                    "projected_assists": round(assists, 1),
                    "projected_pra": round(projected_pra, 1),
                    "pra_floor": pra_floor,
                    "pra_ceiling": pra_ceiling,
                    "fanduel_line": fd_line,
                    "fanduel_over_under": fd_flag,
                }
                if existing:
                    for k, v in payload.items():
                        setattr(existing, k, v)
                    updated += 1
                else:
                    db.add(
                        PRAProjections(
                            date=today,
                            player_id=player.player_id,
                            **payload,
                        )
                    )
                    created += 1
                db.commit()
            except Exception:
                logger.exception(
                    "generate_pra_predictions: failed for %s", player.player_name
                )
                db.rollback()
                errors += 1

        return {
            "status": "ok",
            "date": today.isoformat(),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "players_considered": len(active),
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }
    finally:
        db.close()
