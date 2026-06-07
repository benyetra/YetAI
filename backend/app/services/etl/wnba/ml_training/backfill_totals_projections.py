"""Backfill pred_wnba_totals_projections for historical ML training."""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime
from typing import Any

from app.core.database import SessionLocal
from app.models.predictions_models import (
    WNBAGameLines,
    WNBASpreadActuals,
    WNBATotalsActuals,
    WNBATotalsProjections,
)
from app.services.etl.wnba import totals_projector as tp
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba.backfill_spread_actuals import run_from_spread
from app.services.etl.wnba.ml_training.totals_backfill_context import build_context
from app.services.etl.wnba.ml_training.replay_totals_projection import (
    generate_projection_as_of,
    projection_to_row,
)

logger = logging.getLogger(__name__)

GameKey = tuple[date, str, str]
BATCH_SIZE = 100


def _load_game_keys(
    db,
    season_start: date,
    season_end: date,
    *,
    use_spread_actuals: bool,
) -> list[GameKey]:
    totals = (
        db.query(WNBATotalsActuals)
        .filter(WNBATotalsActuals.game_date >= season_start)
        .filter(WNBATotalsActuals.game_date <= season_end)
        .order_by(WNBATotalsActuals.game_date.asc())
        .all()
    )
    if totals:
        return [(a.game_date, a.home_team_name, a.away_team_name) for a in totals]

    if not use_spread_actuals:
        return []

    spreads = (
        db.query(WNBASpreadActuals)
        .filter(WNBASpreadActuals.game_date >= season_start)
        .filter(WNBASpreadActuals.game_date <= season_end)
        .order_by(WNBASpreadActuals.game_date.asc())
        .all()
    )
    logger.info(
        "backfill_totals_projections: using %d spread actuals (no totals actuals)",
        len(spreads),
    )
    return [(a.game_date, a.home_team_name, a.away_team_name) for a in spreads]


def _preload_market_lines(
    db, season_start: date, season_end: date
) -> dict[GameKey, float]:
    lines = (
        db.query(WNBAGameLines)
        .filter(WNBAGameLines.game_date >= season_start)
        .filter(WNBAGameLines.game_date <= season_end)
        .all()
    )
    out: dict[GameKey, float] = {}
    for line in lines:
        if line.total is None:
            continue
        out[(line.game_date, line.home_team_name, line.away_team_name)] = float(
            line.total
        )
    return out


def _existing_keys(db, season_start: date, season_end: date) -> set[GameKey]:
    rows = (
        db.query(
            WNBATotalsProjections.game_date,
            WNBATotalsProjections.home_team_name,
            WNBATotalsProjections.away_team_name,
        )
        .filter(WNBATotalsProjections.game_date >= season_start)
        .filter(WNBATotalsProjections.game_date <= season_end)
        .all()
    )
    return {(r.game_date, r.home_team_name, r.away_team_name) for r in rows}


def _market_fields_from_projected(
    projected_total: float, market_total: float
) -> dict[str, Any]:
    edge = projected_total - market_total
    recommendation = "NO_PLAY"
    confidence = 0.5
    if edge > 2:
        recommendation = "OVER"
        confidence = min(0.5 + (abs(edge) * 0.05), 0.85)
    elif edge < -2:
        recommendation = "UNDER"
        confidence = min(0.5 + (abs(edge) * 0.05), 0.85)
    return {
        "market_total": market_total,
        "edge": round(edge, 1),
        "recommendation": recommendation,
        "confidence_score": round(confidence, 2),
    }


def sync_market_totals_from_lines(
    *,
    season_start: date,
    season_end: date,
) -> dict[str, Any]:
    """Refresh ``market_total`` (and edge fields) on stored projections from game lines."""
    db = SessionLocal()
    updated = 0
    unchanged = 0
    still_missing = 0
    batch: list[dict] = []
    try:
        market_lines = _preload_market_lines(db, season_start, season_end)
        projections = (
            db.query(WNBATotalsProjections)
            .filter(WNBATotalsProjections.game_date >= season_start)
            .filter(WNBATotalsProjections.game_date <= season_end)
            .all()
        )
        for proj in projections:
            key: GameKey = (proj.game_date, proj.home_team_name, proj.away_team_name)
            market_total = market_lines.get(key)
            if market_total is None:
                if proj.market_total is None:
                    still_missing += 1
                else:
                    unchanged += 1
                continue
            if proj.market_total == market_total:
                unchanged += 1
                continue
            if proj.projected_total is None:
                unchanged += 1
                continue

            row = {
                "game_date": proj.game_date,
                "home_team_name": proj.home_team_name,
                "away_team_name": proj.away_team_name,
                **_market_fields_from_projected(
                    float(proj.projected_total), market_total
                ),
            }
            batch.append(row)
            if len(batch) >= BATCH_SIZE:
                upsert_many(
                    db,
                    WNBATotalsProjections,
                    batch,
                    conflict_keys=["game_date", "home_team_name", "away_team_name"],
                    update_keys=[
                        "market_total",
                        "edge",
                        "recommendation",
                        "confidence_score",
                    ],
                )
                db.commit()
                updated += len(batch)
                batch.clear()

        if batch:
            upsert_many(
                db,
                WNBATotalsProjections,
                batch,
                conflict_keys=["game_date", "home_team_name", "away_team_name"],
            )
            db.commit()
            updated += len(batch)

        result = {
            "status": "ok",
            "season_start": str(season_start),
            "season_end": str(season_end),
            "projections": len(projections),
            "updated": updated,
            "unchanged": unchanged,
            "still_missing_market": still_missing,
        }
        logger.info("sync_market_totals_from_lines complete: %s", result)
        return result
    finally:
        db.close()


def run(
    *,
    season_start: date,
    season_end: date,
    force: bool = False,
    use_spread_actuals: bool = True,
    sync_actuals_from_spread: bool = False,
    include_injury: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    if sync_actuals_from_spread:
        sync = run_from_spread(season_start=season_start, season_end=season_end)
        logger.info("sync totals actuals from spread: %s", sync)

    db = SessionLocal()
    written = 0
    skipped = 0
    batch: list[dict] = []
    try:
        tp.db = db
        tp.load_team_data()

        game_keys = _load_game_keys(
            db,
            season_start,
            season_end,
            use_spread_actuals=use_spread_actuals,
        )
        if not game_keys:
            return {
                "status": "no_games",
                "season_start": str(season_start),
                "season_end": str(season_end),
            }

        if limit is not None:
            game_keys = game_keys[:limit]

        existing = set() if force else _existing_keys(db, season_start, season_end)
        market_lines = _preload_market_lines(db, season_start, season_end)
        backfill_ctx = build_context(db, season_start, season_end)
        stats_cache = backfill_ctx.stats_cache

        pending = sum(1 for key in game_keys if key not in existing)
        logger.info(
            "backfill_totals_projections: %d games to process (%d skip existing)",
            pending,
            len(game_keys) - pending,
        )

        for idx, key in enumerate(game_keys, start=1):
            game_date, home_team, away_team = key
            if key in existing:
                skipped += 1
                continue

            projection = generate_projection_as_of(
                home_team=home_team,
                away_team=away_team,
                game_date=game_date,
                market_total=market_lines.get(key),
                stats_cache=stats_cache,
                include_injury=include_injury,
                backfill_ctx=backfill_ctx,
            )
            batch.append(projection_to_row(projection))

            if len(batch) >= BATCH_SIZE:
                upsert_many(
                    db,
                    WNBATotalsProjections,
                    batch,
                    conflict_keys=["game_date", "home_team_name", "away_team_name"],
                    update_keys=[
                        "market_total",
                        "edge",
                        "recommendation",
                        "confidence_score",
                    ],
                )
                db.commit()
                written += len(batch)
                batch.clear()

            if idx % 250 == 0:
                logger.info(
                    "backfill progress: %d/%d written=%d skipped=%d",
                    idx,
                    len(game_keys),
                    written + len(batch),
                    skipped,
                )

        if batch:
            upsert_many(
                db,
                WNBATotalsProjections,
                batch,
                conflict_keys=["game_date", "home_team_name", "away_team_name"],
            )
            db.commit()
            written += len(batch)

        result = {
            "status": "ok",
            "season_start": str(season_start),
            "season_end": str(season_end),
            "games": len(game_keys),
            "written": written,
            "skipped_existing": skipped,
            "force": force,
        }
        logger.info("backfill_totals_projections complete: %s", result)
        return result
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(
        description="Backfill WNBA totals projections for ML training"
    )
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing projections in the date window",
    )
    parser.add_argument(
        "--sync-actuals-from-spread",
        action="store_true",
        help="Copy spread actuals into totals actuals before backfill",
    )
    parser.add_argument(
        "--no-spread-fallback",
        action="store_true",
        help="Do not use spread actuals when totals actuals are empty",
    )
    parser.add_argument(
        "--include-injury",
        action="store_true",
        help="Apply current injury table (not point-in-time; use for recent slates only)",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--sync-markets-only",
        action="store_true",
        help="Only refresh market_total on existing projections from pred_wnba_game_lines",
    )
    args = parser.parse_args()

    if args.sync_markets_only:
        out = sync_market_totals_from_lines(
            season_start=date.fromisoformat(args.start),
            season_end=date.fromisoformat(args.end),
        )
        print(out)
        if out.get("status") not in ("ok",):
            raise SystemExit(1)
        raise SystemExit(0)

    out = run(
        season_start=date.fromisoformat(args.start),
        season_end=date.fromisoformat(args.end),
        force=args.force,
        use_spread_actuals=not args.no_spread_fallback,
        sync_actuals_from_spread=args.sync_actuals_from_spread,
        include_injury=args.include_injury,
        limit=args.limit,
    )
    print(out)
    if out.get("status") not in ("ok",):
        raise SystemExit(1)
