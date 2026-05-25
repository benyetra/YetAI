"""
NHL starter confirmation before goalie save predictions.

Queries today's slate via NHL API boxscores (starter flag) and compares
against the team's primary goalie in the database (most games played).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import logging

from app.models.predictions_models import NHLGoalie
from app.services.etl.nhl._db import db_session
from app.services.etl.nhl._slate import game_datetime_et
from app.services.etl.nhl.nhl_api_client import NHLAPIClient

logger = logging.getLogger(__name__)

# Confirmation confidence (0–100) stored on prediction context / row metadata.
CONFIDENCE_CONFIRMED_PRIMARY = 95.0
CONFIDENCE_UNCONFIRMED = 35.0

SKIP_STARTER_UNCONFIRMED = "starter_unconfirmed"
SKIP_BACKUP_EXPECTED = "backup_expected"
SKIP_NO_DB_GOALIE = "no_db_goalie"


@dataclass(frozen=True)
class GoalieStarterContext:
    """Per-goalie slot on today's slate."""

    game_id: int
    game_date: Any
    game_time: Any
    is_home: bool
    team_id: int
    team_name: str
    opponent_team_id: int
    opponent_team_name: str
    goalie_id: int | None
    goalie_name: str | None
    starter_confirmed: bool
    confidence: float
    should_predict: bool
    prediction_skipped_reason: str | None


@dataclass
class SlateStarterSummary:
    slots: list[GoalieStarterContext]
    confirmed: int = 0
    skipped: int = 0
    predicted_eligible: int = 0

    @classmethod
    def from_slots(cls, slots: list[GoalieStarterContext]) -> SlateStarterSummary:
        confirmed = sum(1 for s in slots if s.starter_confirmed)
        skipped = sum(1 for s in slots if not s.should_predict)
        eligible = sum(1 for s in slots if s.should_predict)
        return cls(
            slots=slots,
            confirmed=confirmed,
            skipped=skipped,
            predicted_eligible=eligible,
        )


def _api_goalie_identity(api_goalie: dict) -> tuple[int | None, str]:
    player_id = api_goalie.get("playerId")
    name = (api_goalie.get("name") or {}).get("default") or api_goalie.get("name", "")
    if isinstance(name, dict):
        name = name.get("default", "Unknown")
    return player_id, str(name or "Unknown")


def get_starters_from_boxscore(
    client: NHLAPIClient, game_id: int
) -> tuple[dict | None, dict | None]:
    """Return (home_starter, away_starter) dicts from game boxscore, if flagged."""
    boxscore = client.get_game_boxscore(game_id)
    if not boxscore:
        return None, None

    home_goalies = (
        boxscore.get("playerByGameStats", {}).get("homeTeam", {}).get("goalies", [])
    )
    away_goalies = (
        boxscore.get("playerByGameStats", {}).get("awayTeam", {}).get("goalies", [])
    )
    home_starter = next((g for g in home_goalies if g.get("starter")), None)
    away_starter = next((g for g in away_goalies if g.get("starter")), None)
    return home_starter, away_starter


def primary_db_goalie(team_name: str) -> NHLGoalie | None:
    """Team's #1 goalie by games played (same heuristic as daily_predictions)."""
    return (
        db_session.query(NHLGoalie)
        .filter(NHLGoalie.team_name == team_name, NHLGoalie.games_played > 0)
        .order_by(NHLGoalie.games_played.desc())
        .first()
    )


def db_goalie_by_player_id(player_id: int) -> NHLGoalie | None:
    return db_session.query(NHLGoalie).filter(NHLGoalie.player_id == player_id).first()


def resolve_goalie_slot(
    *,
    game_id: int,
    game_date,
    game_time,
    is_home: bool,
    team_id: int,
    team_name: str,
    opponent_team_id: int,
    opponent_team_name: str,
    api_starter: dict | None,
) -> GoalieStarterContext:
    """
    Decide whether to run goalie_saves_model for this slot.

    - API starter matches DB primary → predict (confirmed).
    - API starter is a different player → skip (backup_expected).
    - No API starter → skip (starter_unconfirmed).
    """
    primary = primary_db_goalie(team_name)

    if not api_starter:
        return GoalieStarterContext(
            game_id=game_id,
            game_date=game_date,
            game_time=game_time,
            is_home=is_home,
            team_id=team_id,
            team_name=team_name,
            opponent_team_id=opponent_team_id,
            opponent_team_name=opponent_team_name,
            goalie_id=primary.player_id if primary else None,
            goalie_name=primary.name if primary else None,
            starter_confirmed=False,
            confidence=CONFIDENCE_UNCONFIRMED,
            should_predict=False,
            prediction_skipped_reason=SKIP_STARTER_UNCONFIRMED,
        )

    api_id, api_name = _api_goalie_identity(api_starter)
    if api_id is None:
        return GoalieStarterContext(
            game_id=game_id,
            game_date=game_date,
            game_time=game_time,
            is_home=is_home,
            team_id=team_id,
            team_name=team_name,
            opponent_team_id=opponent_team_id,
            opponent_team_name=opponent_team_name,
            goalie_id=None,
            goalie_name=api_name,
            starter_confirmed=False,
            confidence=CONFIDENCE_UNCONFIRMED,
            should_predict=False,
            prediction_skipped_reason=SKIP_STARTER_UNCONFIRMED,
        )

    if primary and api_id != primary.player_id:
        logger.info(
            "Skipping %s @ %s: backup %s (id=%s) expected; primary %s (id=%s)",
            opponent_team_name,
            team_name,
            api_name,
            api_id,
            primary.name,
            primary.player_id,
        )
        return GoalieStarterContext(
            game_id=game_id,
            game_date=game_date,
            game_time=game_time,
            is_home=is_home,
            team_id=team_id,
            team_name=team_name,
            opponent_team_id=opponent_team_id,
            opponent_team_name=opponent_team_name,
            goalie_id=api_id,
            goalie_name=api_name,
            starter_confirmed=True,
            confidence=CONFIDENCE_CONFIRMED_PRIMARY,
            should_predict=False,
            prediction_skipped_reason=SKIP_BACKUP_EXPECTED,
        )

    db_row = db_goalie_by_player_id(api_id) or primary
    if not db_row:
        return GoalieStarterContext(
            game_id=game_id,
            game_date=game_date,
            game_time=game_time,
            is_home=is_home,
            team_id=team_id,
            team_name=team_name,
            opponent_team_id=opponent_team_id,
            opponent_team_name=opponent_team_name,
            goalie_id=api_id,
            goalie_name=api_name,
            starter_confirmed=True,
            confidence=CONFIDENCE_CONFIRMED_PRIMARY,
            should_predict=False,
            prediction_skipped_reason=SKIP_NO_DB_GOALIE,
        )

    return GoalieStarterContext(
        game_id=game_id,
        game_date=game_date,
        game_time=game_time,
        is_home=is_home,
        team_id=team_id,
        team_name=team_name,
        opponent_team_id=opponent_team_id,
        opponent_team_name=opponent_team_name,
        goalie_id=db_row.player_id,
        goalie_name=db_row.name,
        starter_confirmed=True,
        confidence=CONFIDENCE_CONFIRMED_PRIMARY,
        should_predict=True,
        prediction_skipped_reason=None,
    )


def build_slate_starter_context(
    games: list[dict], client: NHLAPIClient | None = None
) -> SlateStarterSummary:
    """
    Build starter confirmation context for all goalie slots on the slate.
    """
    api = client or NHLAPIClient()
    slots: list[GoalieStarterContext] = []

    for game in games:
        game_id = game.get("id")
        if not game_id:
            continue

        game_date, game_time = game_datetime_et(game)
        home_team = game["homeTeam"]["placeName"]["default"]
        away_team = game["awayTeam"]["placeName"]["default"]
        home_team_id = game["homeTeam"]["id"]
        away_team_id = game["awayTeam"]["id"]

        home_starter, away_starter = get_starters_from_boxscore(api, game_id)

        slots.append(
            resolve_goalie_slot(
                game_id=game_id,
                game_date=game_date,
                game_time=game_time,
                is_home=True,
                team_id=home_team_id,
                team_name=home_team,
                opponent_team_id=away_team_id,
                opponent_team_name=away_team,
                api_starter=home_starter,
            )
        )
        slots.append(
            resolve_goalie_slot(
                game_id=game_id,
                game_date=game_date,
                game_time=game_time,
                is_home=False,
                team_id=away_team_id,
                team_name=away_team,
                opponent_team_id=home_team_id,
                opponent_team_name=home_team,
                api_starter=away_starter,
            )
        )

    summary = SlateStarterSummary.from_slots(slots)
    logger.info(
        "Starter confirmation: %s slots, %s confirmed, %s eligible, %s skipped",
        len(slots),
        summary.confirmed,
        summary.predicted_eligible,
        summary.skipped,
    )
    return summary


def starter_features_metadata(ctx: GoalieStarterContext) -> dict:
    """Optional JSON for NHLGoaliePredictions.features_used."""
    meta: dict[str, Any] = {
        "starter_confirmation": {
            "starter_confirmed": ctx.starter_confirmed,
            "confidence": ctx.confidence,
        }
    }
    if ctx.prediction_skipped_reason:
        meta["prediction_skipped_reason"] = ctx.prediction_skipped_reason
    return meta


def confirmation_timestamp() -> datetime:
    return datetime.utcnow()
