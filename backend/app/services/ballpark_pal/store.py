from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.services.ballpark_pal.models import (
    BppGameSnapshot,
    BppMatchupSnapshot,
    BppParkFactorSnapshot,
    BppPlayerProjSnapshot,
)

logger = logging.getLogger(__name__)


def _game_pk(bpp_game_id: int, candidate: int | None = None) -> int:
    if candidate is not None and candidate != bpp_game_id:
        logger.warning(
            "Ballpark Pal game ID mismatch bpp_game_id=%s game_pk=%s; using BPP ID",
            bpp_game_id,
            candidate,
        )
    return bpp_game_id


def upsert_game_snapshot(
    session: Session,
    slate_date: date,
    bpp_game_id: int,
    *,
    averages: dict[str, Any],
    probabilities: dict[str, Any],
    team_away_id: int,
    team_home_id: int,
    as_of: datetime,
    game_pk: int | None = None,
) -> None:
    row = (
        session.query(BppGameSnapshot)
        .filter_by(slate_date=slate_date, bpp_game_id=bpp_game_id)
        .one_or_none()
    )
    values = {
        "game_pk": _game_pk(bpp_game_id, game_pk),
        "team_away_id": team_away_id,
        "team_home_id": team_home_id,
        "as_of": as_of,
        "averages_json": averages,
        "probabilities_json": probabilities,
    }
    if row is None:
        session.add(
            BppGameSnapshot(
                slate_date=slate_date,
                bpp_game_id=bpp_game_id,
                **values,
            )
        )
    else:
        for key, value in values.items():
            setattr(row, key, value)
    session.flush()


def upsert_player_projs(
    session: Session,
    slate_date: date,
    bpp_game_id: int,
    rows: list[dict[str, Any]],
) -> int:
    for item in rows:
        role = item["role"]
        team_id = int(item["team_id"])
        player_id = team_id if role == "team" else int(item["player_id"])
        row = (
            session.query(BppPlayerProjSnapshot)
            .filter_by(
                slate_date=slate_date,
                bpp_game_id=bpp_game_id,
                player_id=player_id,
                role=role,
            )
            .one_or_none()
        )
        values = {
            "game_pk": _game_pk(bpp_game_id, item.get("game_pk")),
            "team_id": team_id,
            "averages_json": item.get("averages") or {},
            "selected_probs_json": item.get("selected_probs") or {},
        }
        if row is None:
            session.add(
                BppPlayerProjSnapshot(
                    slate_date=slate_date,
                    bpp_game_id=bpp_game_id,
                    player_id=player_id,
                    role=role,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(row, key, value)
    session.flush()
    return len(rows)


def upsert_park_factors(
    session: Session,
    slate_date: date,
    bpp_game_id: int,
    rows: list[dict[str, Any]],
) -> int:
    for item in rows:
        scope = item["scope"]
        player_id = 0 if scope == "game" else int(item["player_id"])
        row = (
            session.query(BppParkFactorSnapshot)
            .filter_by(
                slate_date=slate_date,
                bpp_game_id=bpp_game_id,
                scope=scope,
                player_id=player_id,
            )
            .one_or_none()
        )
        values = {
            "game_pk": _game_pk(bpp_game_id, item.get("game_pk")),
            "factors_json": item.get("factors") or {},
        }
        if row is None:
            session.add(
                BppParkFactorSnapshot(
                    slate_date=slate_date,
                    bpp_game_id=bpp_game_id,
                    scope=scope,
                    player_id=player_id,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(row, key, value)
    session.flush()
    return len(rows)


def upsert_matchups(
    session: Session,
    slate_date: date,
    bpp_game_id: int,
    rows: list[dict[str, Any]],
) -> int:
    for item in rows:
        batter_id = int(item["batter_id"])
        pitcher_id = int(item["pitcher_id"])
        row = (
            session.query(BppMatchupSnapshot)
            .filter_by(
                slate_date=slate_date,
                batter_id=batter_id,
                pitcher_id=pitcher_id,
            )
            .one_or_none()
        )
        values = {
            "bpp_game_id": bpp_game_id,
            "game_pk": _game_pk(bpp_game_id, item.get("game_pk")),
            "probs_json": item.get("probs") or {},
        }
        if row is None:
            session.add(
                BppMatchupSnapshot(
                    slate_date=slate_date,
                    batter_id=batter_id,
                    pitcher_id=pitcher_id,
                    **values,
                )
            )
        else:
            for key, value in values.items():
                setattr(row, key, value)
    session.flush()
    return len(rows)


def load_game_snapshot(
    session: Session, game_pk: int, slate_date: date
) -> BppGameSnapshot | None:
    return (
        session.query(BppGameSnapshot)
        .filter_by(game_pk=game_pk, slate_date=slate_date)
        .first()
    )


def load_player_proj(
    session: Session, player_id: int, slate_date: date, role: str
) -> BppPlayerProjSnapshot | None:
    return (
        session.query(BppPlayerProjSnapshot)
        .filter_by(player_id=player_id, slate_date=slate_date, role=role)
        .order_by(BppPlayerProjSnapshot.updated_at.desc())
        .first()
    )


def load_matchup(
    session: Session, batter_id: int, pitcher_id: int, slate_date: date
) -> BppMatchupSnapshot | None:
    return (
        session.query(BppMatchupSnapshot)
        .filter_by(
            batter_id=batter_id,
            pitcher_id=pitcher_id,
            slate_date=slate_date,
        )
        .first()
    )


def load_hitter_park_factor(
    session: Session,
    player_id: int,
    slate_date: date,
    bpp_game_id: int | None = None,
) -> BppParkFactorSnapshot | None:
    query = session.query(BppParkFactorSnapshot).filter_by(
        player_id=player_id,
        slate_date=slate_date,
        scope="hitter",
    )
    if bpp_game_id is not None:
        query = query.filter_by(bpp_game_id=bpp_game_id)
    return query.order_by(BppParkFactorSnapshot.updated_at.desc()).first()
