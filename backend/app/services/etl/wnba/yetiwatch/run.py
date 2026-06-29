"""YetiWatch pre-game news job — runs upstream of WNBA projection generators."""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.database import SessionLocal
from app.models.predictions_models import WNBATodayActivePlayers, WNBAYetiWatchSignal
from app.services.etl.wnba._db_upsert import upsert_many
from app.services.etl.wnba._espn import now_eastern
from app.services.etl.wnba.yetiwatch.apply_signals import apply_signals_to_slate
from app.services.etl.wnba.yetiwatch.bedrock import bedrock_enabled, invoke_bedrock_json
from app.services.etl.wnba.yetiwatch.heuristic import synthesize_heuristic
from app.services.etl.wnba.yetiwatch.ingest import (
    dedupe_items,
    fetch_candidate_items,
    items_for_player,
)
from app.services.etl.wnba.yetiwatch.models import YetiWatchSignalPayload

logger = logging.getLogger(__name__)


def _make_run_id(game_date) -> str:
    stamp = now_eastern().strftime("%H%M")
    return f"wnba-{game_date.isoformat()}-r{stamp}"


def _synthesize_player(
    *,
    run_id: str,
    as_of: datetime,
    player: WNBATodayActivePlayers,
    items,
) -> YetiWatchSignalPayload:
    if bedrock_enabled() and items:
        raw = invoke_bedrock_json(
            player_name=player.player_name,
            player_id=player.player_id,
            team_id=player.team_id,
            opponent_id=player.opponent_team_id,
            game_start_iso=f"{player.game_date.isoformat()}T00:00:00Z",
            home_or_away="home" if player.home_game else "away",
            b2b_bool=False,
            run_id=run_id,
            as_of_iso=as_of.replace(microsecond=0).isoformat() + "Z",
            baseline_role="unknown",
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
        run_id=run_id,
        as_of=as_of,
        player_id=player.player_id,
        player_name=player.player_name,
        team_id=player.team_id,
        game_date=player.game_date,
        opponent_id=player.opponent_team_id,
        items=items,
    )


def run() -> dict:
    today = now_eastern().date()
    as_of = datetime.utcnow()
    run_id = _make_run_id(today)

    all_items, fetch_ok = fetch_candidate_items()
    if not fetch_ok:
        logger.warning("YetiWatch: injury ingest failed; emitting neutral slate")

    db = SessionLocal()
    synthesized = 0
    neutral = 0
    upsert_rows: list[dict] = []
    try:
        active_rows = (
            db.query(WNBATodayActivePlayers)
            .filter(WNBATodayActivePlayers.game_date == today)
            .all()
        )
        if not active_rows:
            return {
                "status": "ok",
                "date": today.isoformat(),
                "run_id": run_id,
                "players": 0,
                "reason": "empty_slate",
            }

        for player in active_rows:
            player_items = dedupe_items(
                items_for_player(
                    all_items,
                    player_name=player.player_name,
                    team_name=player.team_name,
                )
            )
            payload = _synthesize_player(
                run_id=run_id,
                as_of=as_of,
                player=player,
                items=player_items,
            )
            if not player_items:
                neutral += 1
            else:
                synthesized += 1

            upsert_rows.append(
                {
                    "run_id": run_id,
                    "as_of": as_of,
                    "player_id": player.player_id,
                    "game_date": today,
                    "game_id": payload.game_id,
                    "team_id": player.team_id,
                    "opponent_id": player.opponent_team_id,
                    "payload_json": payload.model_dump(mode="json", by_alias=True),
                    "news_string": payload.news_string,
                    "created_at": as_of,
                }
            )

        upsert_many(
            db,
            WNBAYetiWatchSignal,
            upsert_rows,
            conflict_keys=["player_id", "game_date"],
        )
        db.commit()

        apply_result = apply_signals_to_slate(db, game_date=today)
        return {
            "status": "ok",
            "date": today.isoformat(),
            "run_id": run_id,
            "players": len(active_rows),
            "synthesized": synthesized,
            "neutral": neutral,
            "bedrock": bedrock_enabled(),
            "apply": apply_result,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(run())
