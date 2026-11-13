"""
NHL starter confirmation before goalie save predictions.

Starter source order: NHL boxscore ``starter`` flag (confirmed), then the ESPN
scoreboard ``probableStartingGoalie`` (confirmed / expected -> probable), else the
slot is skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import logging

import requests

from app.models.predictions_models import NHLGoalie
from app.services.etl.nhl._db import db_session
from app.services.etl.nhl._slate import game_datetime_et
from app.services.etl.nhl.nhl_api_client import NHLAPIClient
from app.services.auto_pick.sources._nhl_teams import nhl_full_name
from app.services.espn_results import _norm

logger = logging.getLogger(__name__)

# Confirmation confidence (0–100) stored on prediction context / row metadata.
CONFIDENCE_CONFIRMED_PRIMARY = 95.0
CONFIDENCE_PROBABLE = 70.0
CONFIDENCE_UNCONFIRMED = 35.0

ESPN_NHL_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard"
)
_ESPN_METHODS = {"confirmed": "confirmed", "expected": "probable"}

SKIP_STARTER_UNCONFIRMED = "starter_unconfirmed"
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
    method: str | None = None  # confirmed | probable
    source: str | None = None  # nhl_boxscore | espn
    full_name: str | None = None


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


def db_goalie_by_player_id(player_id: int) -> NHLGoalie | None:
    return db_session.query(NHLGoalie).filter(NHLGoalie.player_id == player_id).first()


def fetch_espn_probables(game_date) -> dict[str, tuple[str, str]]:
    """ESPN scoreboard goalies: ``_norm(team displayName)`` -> (full name, method)."""
    try:
        resp = requests.get(
            ESPN_NHL_SCOREBOARD,
            params={"dates": game_date.strftime("%Y%m%d")},
            timeout=10,
        )
        resp.raise_for_status()
        events = resp.json().get("events", [])
    except Exception as exc:
        logger.warning("ESPN NHL probables fetch failed for %s: %s", game_date, exc)
        return {}

    out: dict[str, tuple[str, str]] = {}
    for event in events:
        for comp in (event.get("competitions") or [{}])[0].get("competitors", []):
            team = _norm((comp.get("team") or {}).get("displayName"))
            for prob in comp.get("probables") or []:
                if prob.get("name") != "probableStartingGoalie":
                    continue
                method = _ESPN_METHODS.get(((prob.get("status") or {}).get("type")))
                name = (prob.get("athlete") or {}).get("fullName")
                if team and name and method:
                    out[team] = (name, method)
    return out


def _roster_goalies(
    client: NHLAPIClient, abbrev: str, cache: dict[str, list[dict]]
) -> list[dict]:
    if abbrev not in cache:
        try:
            cache[abbrev] = (client.get_team_roster(abbrev) or {}).get("goalies", [])
        except Exception as exc:
            logger.warning("NHL roster fetch failed for %s: %s", abbrev, exc)
            cache[abbrev] = []
    return cache[abbrev]


def _roster_name(g: dict) -> str:
    return f"{(g.get('firstName') or {}).get('default', '')} {(g.get('lastName') or {}).get('default', '')}".strip()


def match_roster_goalie(goalies: list[dict], espn_name: str) -> dict | None:
    """Roster goalie for an ESPN name: exact normalized name, else unique last name."""
    want = _norm(espn_name)
    for g in goalies:
        if _norm(_roster_name(g)) == want:
            return g
    last = _norm(want.split(" ")[-1]) if want else ""
    hits = [
        g for g in goalies if _norm((g.get("lastName") or {}).get("default")) == last
    ]
    return hits[0] if len(hits) == 1 else None


def _slot(
    base: dict,
    *,
    goalie_id,
    goalie_name,
    confidence,
    should_predict,
    reason,
    method=None,
    source=None,
    full_name=None,
) -> GoalieStarterContext:
    return GoalieStarterContext(
        **base,
        goalie_id=goalie_id,
        goalie_name=goalie_name,
        starter_confirmed=method == "confirmed",
        confidence=confidence,
        should_predict=should_predict,
        prediction_skipped_reason=reason,
        method=method,
        source=source,
        full_name=full_name,
    )


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
    espn_starter: dict | None = None,
    roster_name: str | None = None,
) -> GoalieStarterContext:
    """
    Decide whether to run goalie_saves_model for this slot.

    Priority: boxscore starter flag (confirmed) > ESPN starter
    ({"id", "full_name", "method"}) > skip (starter_unconfirmed). A starter with
    no NHLGoalie row is skipped (no_db_goalie): the model needs the row.
    ``roster_name`` is the NHL roster "First Last" for the starter, when known.
    """
    base = dict(
        game_id=game_id,
        game_date=game_date,
        game_time=game_time,
        is_home=is_home,
        team_id=team_id,
        team_name=team_name,
        opponent_team_id=opponent_team_id,
        opponent_team_name=opponent_team_name,
    )
    unconfirmed = dict(
        goalie_id=None,
        goalie_name=None,
        confidence=CONFIDENCE_UNCONFIRMED,
        should_predict=False,
        reason=SKIP_STARTER_UNCONFIRMED,
    )

    if api_starter:
        api_id, api_name = _api_goalie_identity(api_starter)
        method, source, full_name = "confirmed", "nhl_boxscore", api_name
    elif espn_starter:
        api_id, api_name = espn_starter.get("id"), espn_starter["full_name"]
        method, source, full_name = espn_starter["method"], "espn", api_name
    else:
        return _slot(base, **unconfirmed)

    if api_id is None:
        return _slot(base, **{**unconfirmed, "goalie_name": api_name})

    confidence = (
        CONFIDENCE_CONFIRMED_PRIMARY if method == "confirmed" else CONFIDENCE_PROBABLE
    )
    db_row = db_goalie_by_player_id(api_id)
    return _slot(
        base,
        goalie_id=api_id,
        goalie_name=db_row.name if db_row else api_name,
        confidence=confidence,
        should_predict=db_row is not None,
        reason=None if db_row else SKIP_NO_DB_GOALIE,
        method=method,
        source=source,
        full_name=roster_name or full_name,
    )


def build_slate_starter_context(
    games: list[dict], client: NHLAPIClient | None = None
) -> SlateStarterSummary:
    """
    Build starter confirmation context for all goalie slots on the slate.
    """
    api = client or NHLAPIClient()
    slots: list[GoalieStarterContext] = []
    espn_by_date: dict = {}  # one ESPN fetch per ET game date
    rosters: dict[str, list[dict]] = {}

    def espn_for(game_date, team_id, abbrev) -> tuple[dict | None, str | None]:
        if game_date not in espn_by_date:
            espn_by_date[game_date] = fetch_espn_probables(game_date)
        full = nhl_full_name(team_id)
        hit = espn_by_date[game_date].get(_norm(full)) if full else None
        if not hit:
            return None, None
        espn_name, method = hit
        g = match_roster_goalie(_roster_goalies(api, abbrev, rosters), espn_name)
        if not g:
            return None, None
        return {
            "id": g["id"],
            "full_name": espn_name,
            "method": method,
        }, _roster_name(g)

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

        for is_home, starter in ((True, home_starter), (False, away_starter)):
            side, other = (
                (game["homeTeam"], game["awayTeam"])
                if is_home
                else (game["awayTeam"], game["homeTeam"])
            )
            espn, roster_name = None, None
            if starter:
                sid, _ = _api_goalie_identity(starter)
                roster_name = next(
                    (
                        _roster_name(g)
                        for g in _roster_goalies(api, side.get("abbrev", ""), rosters)
                        if g.get("id") == sid
                    ),
                    None,
                )
            else:
                espn, roster_name = espn_for(
                    game_date, side["id"], side.get("abbrev", "")
                )
            slots.append(
                resolve_goalie_slot(
                    game_id=game_id,
                    game_date=game_date,
                    game_time=game_time,
                    is_home=is_home,
                    team_id=side["id"],
                    team_name=side["placeName"]["default"],
                    opponent_team_id=other["id"],
                    opponent_team_name=other["placeName"]["default"],
                    api_starter=starter,
                    espn_starter=espn,
                    roster_name=roster_name,
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
            "method": ctx.method,
            "source": ctx.source,
            "full_name": ctx.full_name,
        }
    }
    if ctx.prediction_skipped_reason:
        meta["prediction_skipped_reason"] = ctx.prediction_skipped_reason
    return meta


def confirmation_timestamp() -> datetime:
    return datetime.utcnow()
