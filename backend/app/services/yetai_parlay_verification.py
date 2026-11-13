"""Settlement helpers for YetAI parlay picks stored with ``parlay_legs`` JSON."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timezone
from types import SimpleNamespace
from typing import Any

from app.models.database_models import BetType
from app.services import yetai_grading
from app.services.yetai_bets_service_db import (
    clamp_yetai_result,
    settle_window_elapsed,
)
from app.services.yetai_grading import Outcome

_LEG_BET_TYPE_MAP = {
    "moneyline": BetType.MONEYLINE,
    "money line": BetType.MONEYLINE,
    "ml": BetType.MONEYLINE,
    "spread": BetType.SPREAD,
    "point spread": BetType.SPREAD,
    "puck line": BetType.SPREAD,
    "run line": BetType.SPREAD,
    "total": BetType.TOTAL,
    "total (over/under)": BetType.TOTAL,
    "totals": BetType.TOTAL,
    "over/under": BetType.TOTAL,
    "player prop": BetType.PROP,
    "prop": BetType.PROP,
    "player props": BetType.PROP,
}

TERMINAL_LEG_STATUSES = ("won", "lost", "pushed", "void")


def normalize_leg_bet_type(raw: str | None) -> BetType:
    key = (raw or "").strip().lower()
    return _LEG_BET_TYPE_MAP.get(key, BetType.PROP)


def _parse_time(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def game_date_for_parlay_leg(leg: dict[str, Any], parent=None) -> date | None:
    """Leg game day: grading.game_date, then commence_time, then the parent's day."""
    return yetai_grading.game_day_for(_leg_as_bet(leg)) or (
        yetai_grading.game_day_for(parent) if parent is not None else None
    )


def _leg_as_bet(leg: dict[str, Any], day: date | None = None) -> SimpleNamespace:
    """Synthetic bet-like object for ``grade_pick``; ``day`` is the last-resort game day."""
    commence = _parse_time(leg.get("commence_time"))
    if commence is not None and commence.tzinfo is not None:
        commence = commence.astimezone(timezone.utc).replace(tzinfo=None)
    return SimpleNamespace(
        id=str(leg.get("game_id") or "parlay-leg"),
        sport=str(leg.get("sport") or ""),
        bet_type=normalize_leg_bet_type(leg.get("bet_type")),
        selection=str(leg.get("pick") or ""),
        home_team=leg.get("home_team"),
        away_team=leg.get("away_team"),
        commence_time=commence,
        created_at=datetime.combine(day, time.min) if day else None,
        prediction_factors={
            "grading": leg.get("grading"),
            "event_id": leg.get("game_id"),
        },
    )


def verify_parlay_leg(
    leg: dict[str, Any],
    parent,
    now: datetime,
    window_over: bool,
    backstop: bool = False,
) -> tuple[str, str, str]:
    """(leg_status, leg_result, outcome kind); ``pending`` while the leg cannot be graded.

    Past the retry window a pending leg is voided only on a real not-found answer, never
    while ESPN reports it scheduled/in progress or the last try was an error; past the
    backstop it is voided whatever the reason.
    """
    day = game_date_for_parlay_leg(leg, parent)
    outcome = yetai_grading.grade_pick(_leg_as_bet(leg, day))
    kind = outcome.kind
    if kind in TERMINAL_LEG_STATUSES:
        return kind, outcome.result, kind
    waiting = kind == "error" or outcome.result in yetai_grading.WAITING
    if kind == "ungradeable" or backstop or (window_over and not waiting):
        return "void", f"Ungradeable: {outcome.result}", kind
    return "pending", outcome.result, kind


def combine_parlay_leg_statuses(statuses: list[str]) -> tuple[str, str] | None:
    """Standard parlay rules over leg statuses; None while any leg is pending."""
    if not statuses:
        return None
    normalized = [(s or "pending").lower() for s in statuses]
    total = len(normalized)
    lost = normalized.count("lost")
    if lost:
        return "lost", f"Parlay lost: {lost} of {total} legs lost"
    if "pending" in normalized:
        return None
    live = [s for s in normalized if s not in ("pushed", "void")]
    if live:
        return "won", f"Parlay won: all {len(live)} active legs won"
    return "void", f"Parlay void: all {total} legs void or pushed"


def _american_to_decimal(odds: Any) -> float | None:
    try:
        o = float(str(odds).strip().replace("+", ""))
    except (TypeError, ValueError):
        return None
    if o >= 100:
        return 1 + o / 100
    if o <= -100:
        return 1 + 100 / -o
    return None


def effective_parlay_odds(legs: list[dict[str, Any]]) -> float | None:
    """American odds of the won legs when void/pushed legs dropped out, else None.

    None also when a remaining leg's odds cannot be read (units then use the posted price).
    """
    statuses = [(leg.get("leg_status") or "").lower() for leg in legs]
    if not any(s in ("void", "pushed") for s in statuses):
        return None
    decimal = 1.0
    for leg, status in zip(legs, statuses):
        if status in ("void", "pushed"):
            continue
        d = _american_to_decimal(leg.get("odds"))
        if d is None:
            return None
        decimal *= d
    if decimal <= 1:
        return None
    return round((decimal - 1) * 100 if decimal >= 2 else -100 / (decimal - 1), 2)


def parse_parlay_legs(raw: Any) -> list[dict[str, Any]] | None:
    """Leg dicts from the column (list or JSON string); None when there are none usable."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(raw, list):
        return None
    legs = [leg for leg in raw if isinstance(leg, dict)]
    return legs or None


def annotate_leg_result(
    leg: dict[str, Any], status: str, result: str
) -> dict[str, Any]:
    updated = dict(leg)
    updated["leg_status"] = status
    updated["leg_result"] = clamp_yetai_result(result, max_len=120)
    return updated


def parlay_last_day(bet) -> date | None:
    legs = parse_parlay_legs(getattr(bet, "parlay_legs", None)) or []
    days = [game_date_for_parlay_leg(leg, bet) for leg in legs]
    return max((d for d in days if d), default=None)


def grade_parlay(
    bet, now: datetime, window_over: bool | None = None, backstop: bool = False
) -> tuple[Outcome, list[dict[str, Any]]]:
    """
    Grade every non-terminal leg and combine.

    Returns (Outcome, updated_legs). Outcome kind is won/lost/void when the parlay is
    decided, ``ungradeable`` when it has no usable legs, else ``error`` (a leg hit an
    ESPN error) or ``not_ready``. A lost leg decides the parlay at once. ``window_over``
    defaults to the last leg's day + SETTLE_RETRY_DAYS.
    """
    legs = parse_parlay_legs(bet.parlay_legs)
    if legs is None:
        return Outcome("ungradeable", "Parlay has no usable legs"), []
    if window_over is None:
        window_over = settle_window_elapsed(parlay_last_day(bet), now)

    updated: list[dict[str, Any]] = []
    kinds: list[str] = []
    for leg in legs:
        prior = (leg.get("leg_status") or "").lower()
        if prior in TERMINAL_LEG_STATUSES:
            updated.append(leg)
            continue
        status, result, kind = verify_parlay_leg(leg, bet, now, window_over, backstop)
        if status == "pending":
            kinds.append(kind)
        updated.append(annotate_leg_result(leg, status, result))

    statuses = [leg.get("leg_status") or "pending" for leg in updated]
    combined = combine_parlay_leg_statuses(statuses)
    if combined is None:
        waiting = next(
            (l.get("leg_result") for l in updated if l.get("leg_status") == "pending"),
            None,
        )
        kind = "error" if "error" in kinds else "not_ready"
        return Outcome(kind, waiting or "Legs pending"), updated

    kind, text = combined
    bits = [
        f"L{i + 1} {leg.get('leg_status')}: "
        f"{clamp_yetai_result(str(leg.get('leg_result') or ''), max_len=40)}"
        for i, leg in enumerate(updated)
    ]
    return Outcome(kind, f"{text}. {' | '.join(bits)}"), updated
