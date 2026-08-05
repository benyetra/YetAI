from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any

from app.services.ballpark_pal.client import BallparkPalClient
from app.services.ballpark_pal.config import ballpark_pal_enabled
from app.services.ballpark_pal import store

logger = logging.getLogger(__name__)


def _items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    if "items" in payload:
        return _items(payload["items"])
    if "data" in payload:
        return _items(payload["data"])
    return []


def _selected_probabilities(
    probabilities: list[dict[str, Any]],
) -> dict[int, dict[str, dict[str, Any]]]:
    selected: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for item in probabilities:
        subject = item.get("subject") or {}
        subject_id = subject.get("id")
        market_key = item.get("marketKey")
        if subject_id is None or not market_key:
            continue
        selected[int(subject_id)][str(market_key)] = item
    return selected


def _player_rows(
    averages: dict[str, Any],
    probabilities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = _selected_probabilities(probabilities)
    rows = []
    for collection, role in (
        ("batters", "batter"),
        ("pitchers", "pitcher"),
        ("teams", "team"),
    ):
        for item in _items(averages.get(collection)):
            team_id = int(item["teamId"])
            player_id = team_id if role == "team" else int(item["playerId"])
            rows.append(
                {
                    "player_id": player_id,
                    "team_id": team_id,
                    "role": role,
                    "averages": item,
                    "selected_probs": selected.get(player_id, {}),
                }
            )
    return rows


def _group_by_game(
    payload: Any,
) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in _items(payload):
        game_id = item.get("gameId")
        if game_id is not None:
            grouped[int(game_id)].append(item)
    return grouped


def sync_ballpark_pal_slate(
    slate_date: date,
    *,
    client: BallparkPalClient | None = None,
    session=None,
) -> dict:
    if not ballpark_pal_enabled():
        return {"status": "skipped", "reason": "disabled"}

    owns_session = session is None
    if owns_session:
        from app.services.etl.mlb import _db

        session = _db.init_session()

    try:
        api_client = client or BallparkPalClient()
        iso_date = slate_date.isoformat()
        games_payload = api_client.games(iso_date)
        if games_payload is None:
            session.rollback()
            return {"status": "error", "error": "games_fetch_failed"}

        games = _items(games_payload)
        player_count = 0
        for game in games:
            game_id = int(game["gameId"])
            averages = api_client.projections_averages(game_id) or {}
            probabilities_payload = api_client.projections_probabilities(game_id) or []
            probabilities = _items(probabilities_payload)
            store.upsert_game_snapshot(
                session,
                slate_date,
                game_id,
                team_away_id=int(game["teamAwayId"]),
                team_home_id=int(game["teamHomeId"]),
                as_of=datetime.now(timezone.utc),
                averages=averages,
                probabilities={"items": probabilities},
                game_pk=game_id,
            )
            player_count += store.upsert_player_projs(
                session,
                slate_date,
                game_id,
                _player_rows(averages, probabilities),
            )

        park_factor_count = 0
        for game_id, rows in _group_by_game(api_client.parkfactors(iso_date)).items():
            normalized = [{"scope": "game", "factors": item} for item in rows]
            park_factor_count += store.upsert_park_factors(
                session, slate_date, game_id, normalized
            )
        for game_id, rows in _group_by_game(
            api_client.parkfactors_hitters(date=iso_date)
        ).items():
            normalized = [
                {
                    "scope": "hitter",
                    "player_id": int(item["playerId"]),
                    "factors": item,
                }
                for item in rows
            ]
            park_factor_count += store.upsert_park_factors(
                session, slate_date, game_id, normalized
            )

        matchup_count = 0
        for game_id, rows in _group_by_game(
            api_client.matchups(iso_date, starters=True)
        ).items():
            normalized = [
                {
                    "batter_id": int(item["batterId"]),
                    "pitcher_id": int(item["pitcherId"]),
                    "probs": item,
                }
                for item in rows
                if item.get("pitcherId") is not None
            ]
            matchup_count += store.upsert_matchups(
                session, slate_date, game_id, normalized
            )

        session.commit()
        return {
            "status": "ok",
            "games": len(games),
            "players": player_count,
            "park_factors": park_factor_count,
            "matchups": matchup_count,
        }
    except Exception as exc:
        logger.warning("Ballpark Pal slate sync failed: %s", exc)
        if session is not None:
            session.rollback()
        return {"status": "error", "error": str(exc)}
    finally:
        if owns_session:
            _db.close_session()
