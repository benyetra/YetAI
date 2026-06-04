"""Settlement helpers for YetAI parlay picks stored with ``parlay_legs`` JSON."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Optional, Tuple

import requests
from sqlalchemy.orm import Session

from app.models.database_models import BetType, Game, GameStatus, YetAIBet
from app.services.yetai_bets_service_db import (
    PROP_EVENT_DATE_RE,
    YetAIBetsServiceDB,
    clamp_yetai_result,
)

logger = logging.getLogger(__name__)

_LEG_BET_TYPE_MAP = {
    "moneyline": BetType.MONEYLINE,
    "money line": BetType.MONEYLINE,
    "ml": BetType.MONEYLINE,
    "spread": BetType.SPREAD,
    "point spread": BetType.SPREAD,
    "total": BetType.TOTAL,
    "totals": BetType.TOTAL,
    "over/under": BetType.TOTAL,
    "player prop": BetType.PROP,
    "prop": BetType.PROP,
    "player props": BetType.PROP,
}


def normalize_leg_bet_type(raw: str | None) -> BetType:
    key = (raw or "").strip().lower()
    return _LEG_BET_TYPE_MAP.get(key, BetType.PROP)


def game_date_for_parlay_leg(leg: dict[str, Any]) -> date:
    commence_raw = leg.get("commence_time")
    if commence_raw:
        try:
            if isinstance(commence_raw, datetime):
                return commence_raw.date()
            return datetime.fromisoformat(
                str(commence_raw).replace("Z", "+00:00")
            ).date()
        except (TypeError, ValueError):
            pass
    game_id = str(leg.get("game_id") or "")
    match = PROP_EVENT_DATE_RE.search(game_id)
    if match:
        return date.fromisoformat(match.group(1))
    return datetime.utcnow().date()


def yetai_bet_from_parlay_leg(leg: dict[str, Any]) -> YetAIBet:
    odds_raw = leg.get("odds", -110)
    if isinstance(odds_raw, str):
        odds_raw = odds_raw.strip().replace("+", "")
    commence_time = None
    if leg.get("commence_time"):
        try:
            raw = leg["commence_time"]
            commence_time = (
                raw
                if isinstance(raw, datetime)
                else datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            )
        except (TypeError, ValueError):
            commence_time = None

    return YetAIBet(
        id=str(leg.get("game_id") or "parlay-leg"),
        title=str(leg.get("game") or leg.get("pick") or "Parlay leg"),
        description="",
        bet_type=normalize_leg_bet_type(leg.get("bet_type")),
        selection=str(leg.get("pick") or ""),
        odds=float(odds_raw),
        confidence=float(leg.get("confidence") or 0),
        sport=str(leg.get("sport") or ""),
        home_team=leg.get("home_team"),
        away_team=leg.get("away_team"),
        commence_time=commence_time,
        prediction_factors={"event_id": leg.get("game_id")},
    )


def _teams_match(stored: str | None, candidate: str | None) -> bool:
    a = (stored or "").strip().lower()
    b = (candidate or "").strip().lower()
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    a_tokens = {t for t in re.split(r"[\s@]+", a) if len(t) > 2}
    b_tokens = {t for t in re.split(r"[\s@]+", b) if len(t) > 2}
    return bool(a_tokens & b_tokens)


def _lookup_final_scores_in_games(
    db: Session, home: str, away: str, game_day: date
) -> Optional[Tuple[int, int]]:
    rows = (
        db.query(Game)
        .filter(
            Game.status == GameStatus.FINAL,
            Game.commence_time >= datetime.combine(game_day, datetime.min.time()),
            Game.commence_time < datetime.combine(game_day, datetime.max.time()),
        )
        .all()
    )
    for row in rows:
        if _teams_match(row.home_team, home) and _teams_match(row.away_team, away):
            return int(row.home_score or 0), int(row.away_score or 0)
        if _teams_match(row.home_team, away) and _teams_match(row.away_team, home):
            return int(row.away_score or 0), int(row.home_score or 0)
    return None


def _lookup_mlb_final_scores(
    home: str, away: str, game_day: date
) -> Optional[Tuple[int, int]]:
    date_str = game_day.strftime("%Y-%m-%d")
    try:
        response = requests.get(
            "https://statsapi.mlb.com/api/v1/schedule",
            params={"sportId": 1, "date": date_str, "hydrate": "linescore"},
            timeout=15,
        )
        response.raise_for_status()
        for day in response.json().get("dates") or []:
            for game in day.get("games") or []:
                if game.get("status", {}).get("abstractGameState") != "Final":
                    continue
                teams = game.get("teams") or {}
                home_info = (teams.get("home") or {}).get("team") or {}
                away_info = (teams.get("away") or {}).get("team") or {}
                home_name = home_info.get("name") or home_info.get("teamName") or ""
                away_name = away_info.get("name") or away_info.get("teamName") or ""
                if not (
                    (_teams_match(home, home_name) and _teams_match(away, away_name))
                    or (_teams_match(home, away_name) and _teams_match(away, home_name))
                ):
                    continue
                linescore = game.get("linescore") or {}
                return int(linescore.get("home", {}).get("runs") or 0), int(
                    linescore.get("away", {}).get("runs") or 0
                )
    except Exception as exc:
        logger.warning("MLB score lookup failed for %s @ %s: %s", away, home, exc)
    return None


def _lookup_nhl_final_scores(
    home: str, away: str, game_day: date
) -> Optional[Tuple[int, int]]:
    from app.services.etl.nhl._boxscore import (
        get_completed_games_for_date,
        get_game_boxscore,
    )

    for game in get_completed_games_for_date(game_day):
        game_id = game.get("id")
        if not game_id:
            continue
        box = get_game_boxscore(int(game_id))
        if not box:
            continue
        home_team = ((box.get("homeTeam") or {}).get("name") or {}).get("default", "")
        away_team = ((box.get("awayTeam") or {}).get("name") or {}).get("default", "")
        if not (
            (_teams_match(home, home_team) and _teams_match(away, away_team))
            or (_teams_match(home, away_team) and _teams_match(away, home_team))
        ):
            continue
        home_score = int((box.get("homeTeam") or {}).get("score") or 0)
        away_score = int((box.get("awayTeam") or {}).get("score") or 0)
        if _teams_match(home, away_team) and _teams_match(away, home_team):
            return away_score, home_score
        return home_score, away_score
    return None


def resolve_final_scores_for_leg(
    db: Session,
    service: YetAIBetsServiceDB,
    leg: dict[str, Any],
    synthetic: YetAIBet,
    game_day: date,
) -> Optional[Tuple[int, int]]:
    home = (synthetic.home_team or "").strip()
    away = (synthetic.away_team or "").strip()
    if home and away:
        scores = _lookup_final_scores_in_games(db, home, away, game_day)
        if scores:
            return scores

    if service._is_mlb_sport(synthetic.sport):
        return _lookup_mlb_final_scores(home, away, game_day)
    if service._is_nhl_sport(synthetic.sport):
        return _lookup_nhl_final_scores(home, away, game_day)

    if service._is_nba_sport(synthetic.sport):
        from app.models.predictions_models import NBASpreadActuals

        row = (
            db.query(NBASpreadActuals)
            .filter(
                NBASpreadActuals.game_date == game_day,
                NBASpreadActuals.home_team_name == home,
                NBASpreadActuals.away_team_name == away,
            )
            .first()
        )
        if row:
            return int(row.home_score), int(row.away_score)
    return None


def verify_parlay_leg(
    leg: dict[str, Any],
    service: YetAIBetsServiceDB,
    prop_service,
    db: Session,
) -> Optional[Tuple[str, str]]:
    """Return (status, result) for one leg, or None when the game is not ready."""
    synthetic = yetai_bet_from_parlay_leg(leg)
    game_day = game_date_for_parlay_leg(leg)

    if service._is_prop_bet(synthetic):
        if service._is_mlb_sport(synthetic.sport):
            return prop_service.verify_yetai_mlb_prop(synthetic, game_day)
        if service._is_nba_sport(synthetic.sport):
            return prop_service.verify_yetai_nba_prop(synthetic, game_day)
        return None

    if service._is_spread_bet(synthetic) and service._is_nba_sport(synthetic.sport):
        return service._verify_yetai_nba_spread_from_actuals(synthetic, game_day, db)

    scores = resolve_final_scores_for_leg(db, service, leg, synthetic, game_day)
    if scores is None and service._is_nba_sport(synthetic.sport):
        return service._verify_yetai_nba_spread_from_actuals(synthetic, game_day, db)
    if scores is None:
        return None

    home_score, away_score = scores
    return service._evaluate_yetai_bet_outcome(synthetic, home_score, away_score)


def combine_parlay_leg_statuses(statuses: list[str]) -> Optional[Tuple[str, str]]:
    """Apply standard parlay rules to resolved leg statuses."""
    if not statuses:
        return None
    if any(status is None for status in statuses):
        return None

    normalized = [status.lower() for status in statuses]
    if any(status == "lost" for status in normalized):
        lost = sum(1 for status in normalized if status == "lost")
        return "lost", f"Parlay lost: {lost} of {len(statuses)} legs lost"
    if any(
        status == "pending" or status == "pending_manual_review"
        for status in normalized
    ):
        return None

    active = [status for status in normalized if status != "pushed"]
    if not active:
        return "pushed", f"Parlay pushed: all {len(statuses)} legs pushed"

    if all(status == "won" for status in active):
        return "won", f"Parlay won: all {len(active)} active legs won"

    return None


def annotate_leg_result(
    leg: dict[str, Any], status: str, result: str
) -> dict[str, Any]:
    updated = dict(leg)
    updated["leg_status"] = status
    updated["leg_result"] = clamp_yetai_result(result, max_len=120)
    return updated


def verify_yetai_parlay(
    bet: YetAIBet,
    service: YetAIBetsServiceDB,
    prop_service,
    db: Session,
) -> Optional[Tuple[str, str, list[dict[str, Any]]]]:
    """
    Grade all JSON legs and settle the parent parlay when every leg is resolved.

    Returns (parent_status, parent_result, updated_legs) or None if still pending.
    """
    legs = bet.parlay_legs if isinstance(bet.parlay_legs, list) else []
    if len(legs) < 2:
        return None

    updated_legs: list[dict[str, Any]] = []
    leg_statuses: list[str] = []
    leg_results: list[str] = []

    for leg in legs:
        if not isinstance(leg, dict):
            return None
        prior_status = (leg.get("leg_status") or "").lower()
        if prior_status in ("won", "lost", "pushed"):
            updated_legs.append(leg)
            leg_statuses.append(prior_status)
            leg_results.append(str(leg.get("leg_result") or prior_status))
            continue

        outcome = verify_parlay_leg(leg, service, prop_service, db)
        if outcome is None:
            updated_legs.append(leg)
            leg_statuses.append("pending")
            leg_results.append("Pending")
            continue

        status, result = outcome
        updated_legs.append(annotate_leg_result(leg, status, result))
        leg_statuses.append(status)
        leg_results.append(result)

    combined = combine_parlay_leg_statuses(leg_statuses)
    if combined is None:
        return None

    parent_status, parent_result = combined
    detail_bits = [
        f"L{i + 1} {leg_statuses[i]}: {clamp_yetai_result(leg_results[i], max_len=40)}"
        for i in range(len(leg_statuses))
    ]
    parent_result = clamp_yetai_result(
        f"{parent_result}. {' | '.join(detail_bits)}", max_len=200
    )
    return parent_status, parent_result, updated_legs
