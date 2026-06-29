"""YetiWatch pre-game news job — runs upstream of projection generators."""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.services.etl.nba._espn import now_eastern
from app.services.etl.yetiwatch.bedrock import bedrock_enabled, invoke_bedrock_json
from app.services.etl.yetiwatch.heuristic import synthesize_heuristic
from app.services.etl.yetiwatch.ingest import dedupe_items, items_for_subject
from app.services.etl.yetiwatch.models import YetiWatchSignalPayload
from app.services.etl.yetiwatch.slate import SlateSubject
from app.services.etl.yetiwatch.sports.registry import get_adapter
from app.services.etl.yetiwatch.store import upsert_signals

logger = logging.getLogger(__name__)


def _make_run_id(sport: str, game_date) -> str:
    stamp = now_eastern().strftime("%H%M")
    return f"{sport}-{game_date.isoformat()}-r{stamp}"


def _synthesize_subject(
    *,
    sport: str,
    run_id: str,
    as_of: datetime,
    subject: SlateSubject,
    items,
) -> YetiWatchSignalPayload:
    if bedrock_enabled() and items:
        raw = invoke_bedrock_json(
            player_name=subject.entity_name,
            player_id=subject.entity_id,
            team_id=subject.team_id or 0,
            opponent_id=subject.opponent_id,
            game_start_iso=f"{subject.game_date.isoformat()}T00:00:00Z",
            home_or_away="home" if subject.home_game else "away",
            b2b_bool=False,
            run_id=run_id,
            as_of_iso=as_of.replace(microsecond=0).isoformat() + "Z",
            baseline_role=subject.baseline_role,
            items=[
                {
                    "tier": item.tier.value,
                    "source_label": item.source_label,
                    "item_ts_iso": item.item_ts.replace(microsecond=0).isoformat()
                    + "Z",
                    "text": item.text,
                }
                for item in items
            ],
        )
        return YetiWatchSignalPayload.model_validate(raw)

    return synthesize_heuristic(
        sport=sport,
        run_id=run_id,
        as_of=as_of,
        entity_id=subject.entity_id,
        entity_name=subject.entity_name,
        team_id=subject.team_id or 0,
        game_date=subject.game_date,
        opponent_id=subject.opponent_id,
        items=items,
    )


def run_for_sport(sport: str) -> dict:
    adapter = get_adapter(sport)
    game_date = adapter.game_date()
    as_of = datetime.utcnow()
    run_id = _make_run_id(sport, game_date)

    db = SessionLocal()
    synthesized = 0
    neutral = 0
    upsert_rows: list[dict] = []
    try:
        all_items, fetch_ok = adapter.fetch_candidate_items(db)
        if not fetch_ok:
            logger.warning(
                "YetiWatch[%s]: ingest failed; emitting neutral slate", sport
            )

        subjects = adapter.load_slate(db, game_date)
        if not subjects:
            return {
                "status": "ok",
                "sport": sport,
                "date": game_date.isoformat(),
                "run_id": run_id,
                "entities": 0,
                "reason": "empty_slate",
            }

        for subject in subjects:
            subject_items = dedupe_items(
                items_for_subject(
                    all_items,
                    entity_name=subject.entity_name,
                    team_name=None,
                )
            )
            payload = _synthesize_subject(
                sport=sport,
                run_id=run_id,
                as_of=as_of,
                subject=subject,
                items=subject_items,
            )
            if not subject_items:
                neutral += 1
            else:
                synthesized += 1

            upsert_rows.append(
                {
                    "sport": sport,
                    "run_id": run_id,
                    "as_of": as_of,
                    "entity_id": subject.entity_id,
                    "game_date": game_date,
                    "game_id": payload.game_id,
                    "team_id": subject.team_id,
                    "opponent_id": subject.opponent_id,
                    "payload_json": payload.model_dump(mode="json", by_alias=True),
                    "news_string": payload.news_string,
                    "created_at": as_of,
                }
            )

        upsert_signals(db, upsert_rows)
        db.commit()

        apply_result = adapter.apply_signals(db, game_date)
        return {
            "status": "ok",
            "sport": sport,
            "date": game_date.isoformat(),
            "run_id": run_id,
            "entities": len(subjects),
            "synthesized": synthesized,
            "neutral": neutral,
            "bedrock": bedrock_enabled(),
            "apply": apply_result,
        }
    finally:
        db.close()


def run() -> dict:
    """Default entrypoint — WNBA for backward compatibility."""
    return run_for_sport("wnba")
