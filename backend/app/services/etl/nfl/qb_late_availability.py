"""Late-week / gameday QB availability adjustments.

Closer to kickoff, Questionable → Out transitions are common. This module:
- escalates injury risk and yard discounts as kickoff approaches
- cuts backup projections more aggressively when the backup is live
- supports a Celery gameday refresh that re-runs QB + kicker boards
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_TRUTHY = frozenset({"1", "true", "yes"})

# Hours before kickoff when Questionable is treated nearly as unavailable.
_LATE_Q_HOURS = 3.0
# Hours before kickoff when Questionable soft-downgrade escalates.
_ESCALATE_Q_HOURS = 12.0

# Yard cuts (in addition to / instead of baseline qb_tiers soft downgrades)
_Q_LATE_YARD_CUT = 28.0
_Q_ESCALATE_YARD_CUT = 18.0
_BACKUP_BASE_CUT = 25.0
_BACKUP_LATE_EXTRA_CUT = 20.0  # total ≈ 45 when very late
_BACKUP_YARD_FLOOR = 130.0


def late_availability_enabled() -> bool:
    """Kill-switch; default on."""
    raw = os.getenv("NFL_QB_LATE_AVAILABILITY", "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def hours_until_kickoff(
    kickoff: datetime | None,
    *,
    now: datetime | None = None,
) -> float | None:
    """Signed hours until kickoff (negative if already started)."""
    if kickoff is None:
        return None
    now_dt = now or datetime.now(timezone.utc)
    ko = kickoff
    if ko.tzinfo is None:
        ko = ko.replace(tzinfo=timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    return (ko - now_dt).total_seconds() / 3600.0


def escalate_questionable(
    status: Any,
    *,
    hours_to_kickoff: float | None,
) -> str:
    """
    Map Questionable → Out when inside the late window.

    Practice-report nuance is unavailable offline; hours-to-kickoff is the
    proxy for "final inactive list" timing.
    """
    normalized = str(status or "Healthy").strip()
    lowered = normalized.lower()
    if hours_to_kickoff is None or not late_availability_enabled():
        return normalized
    if lowered not in {"questionable", "q"}:
        return normalized
    if hours_to_kickoff <= _LATE_Q_HOURS:
        return "Out"
    return normalized


def late_injury_risk(
    status: Any,
    *,
    hours_to_kickoff: float | None,
    is_backup: bool = False,
) -> float:
    """Injury risk in [0, 1], escalated near kickoff for Questionable."""
    from app.services.etl.nfl.qb_features import injury_risk_from_status

    effective = escalate_questionable(status, hours_to_kickoff=hours_to_kickoff)
    risk = injury_risk_from_status(effective)
    if is_backup:
        risk = max(risk, 0.9)
        return risk
    if not late_availability_enabled() or hours_to_kickoff is None:
        return risk
    lowered = str(status or "").strip().lower()
    if lowered in {"questionable", "q"} and hours_to_kickoff <= _ESCALATE_Q_HOURS:
        # Between escalate and late windows: ramp from 0.55 → ~0.9
        if hours_to_kickoff > _LATE_Q_HOURS:
            span = max(1e-6, _ESCALATE_Q_HOURS - _LATE_Q_HOURS)
            t = 1.0 - (hours_to_kickoff - _LATE_Q_HOURS) / span
            risk = max(risk, 0.55 + 0.35 * min(1.0, max(0.0, t)))
        else:
            risk = 1.0
    return float(min(1.0, max(0.0, risk)))


def late_yard_adjustment(
    *,
    base_yards: float,
    injury_status: Any = None,
    is_backup: bool = False,
    hours_to_kickoff: float | None = None,
) -> tuple[float, dict[str, Any]]:
    """
    Apply late-availability yard cuts.

    Returns ``(adjusted_yards, meta)``. Callers that already applied
    ``qb_tiers`` soft downgrades should pass the *pre-tier* base and apply
    this instead, or pass tier yards and request ``replace_tier_cuts``.
    """
    meta: dict[str, Any] = {
        "late_availability": late_availability_enabled(),
        "hours_to_kickoff": hours_to_kickoff,
        "is_backup": bool(is_backup),
    }
    yards = float(base_yards)
    status = str(injury_status or "Healthy").strip().lower()
    effective = escalate_questionable(
        injury_status, hours_to_kickoff=hours_to_kickoff
    ).lower()
    meta["effective_status"] = effective

    if is_backup:
        cut = _BACKUP_BASE_CUT
        if (
            late_availability_enabled()
            and hours_to_kickoff is not None
            and hours_to_kickoff <= _ESCALATE_Q_HOURS
        ):
            cut += _BACKUP_LATE_EXTRA_CUT
            meta["backup_late_cut"] = True
        yards = max(_BACKUP_YARD_FLOOR, yards - cut)
        meta["yard_cut"] = cut
        return round(yards, 1), meta

    if effective in {"out", "ir", "doubtful"}:
        # Starter unavailable — projection path should have promoted backup;
        # if we still land here, collapse confidence via heavy cut.
        yards = max(_BACKUP_YARD_FLOOR, yards - 40.0)
        meta["yard_cut"] = 40.0
        return round(yards, 1), meta

    if status in {"questionable", "q"} and late_availability_enabled():
        if hours_to_kickoff is not None and hours_to_kickoff <= _LATE_Q_HOURS:
            cut = _Q_LATE_YARD_CUT
        elif hours_to_kickoff is not None and hours_to_kickoff <= _ESCALATE_Q_HOURS:
            cut = _Q_ESCALATE_YARD_CUT
        else:
            cut = 12.0  # match qb_tiers soft downgrade
        yards = max(150.0, yards - cut)
        meta["yard_cut"] = cut
        return round(yards, 1), meta

    meta["yard_cut"] = 0.0
    return round(yards, 1), meta


def should_promote_backup(
    injury_status: Any,
    *,
    hours_to_kickoff: float | None,
) -> bool:
    """True when starter should be replaced by depth chart #2."""
    effective = escalate_questionable(injury_status, hours_to_kickoff=hours_to_kickoff)
    return effective.lower() in {"out", "ir", "doubtful"}


def apply_late_availability_to_qb_row(
    qb_data: Mapping[str, Any],
    *,
    kickoff: datetime | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Mutate a starting-QB dict with late availability fields.

    Expects keys from ``get_dynamic_starting_qbs``; returns a new dict.
    """
    out = dict(qb_data)
    hours = hours_until_kickoff(kickoff, now=now)
    status = out.get("injury_status") or "Healthy"
    is_backup = bool(out.get("is_backup"))

    if should_promote_backup(status, hours_to_kickoff=hours) and not is_backup:
        # Flag for caller — depth chart promotion already happened for Out;
        # for escalated Q we mark promote_requested so dynamic can swap.
        out["promote_backup_requested"] = True
        out["injury_status"] = escalate_questionable(status, hours_to_kickoff=hours)
    else:
        out["promote_backup_requested"] = False
        out["injury_status"] = escalate_questionable(status, hours_to_kickoff=hours)

    out["hours_to_kickoff"] = hours
    out["injury_risk"] = late_injury_risk(
        status,
        hours_to_kickoff=hours,
        is_backup=is_backup or bool(out.get("promote_backup_requested")),
    )
    out["late_availability_meta"] = {
        "hours_to_kickoff": hours,
        "effective_status": out["injury_status"],
        "promote_backup_requested": out["promote_backup_requested"],
    }
    return out
