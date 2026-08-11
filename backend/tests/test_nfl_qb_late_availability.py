"""Tests for late QB availability (Questionable→Out near kickoff)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.etl.nfl.qb_late_availability import (
    escalate_questionable,
    hours_until_kickoff,
    late_injury_risk,
    late_yard_adjustment,
    should_promote_backup,
)


def test_hours_until_kickoff():
    now = datetime(2026, 9, 13, 14, 0, tzinfo=timezone.utc)
    ko = now + timedelta(hours=3)
    assert abs(hours_until_kickoff(ko, now=now) - 3.0) < 1e-6


def test_escalate_questionable_inside_late_window():
    assert escalate_questionable("Questionable", hours_to_kickoff=2.0) == "Out"
    assert escalate_questionable("Questionable", hours_to_kickoff=6.0) == "Questionable"
    assert escalate_questionable("Healthy", hours_to_kickoff=1.0) == "Healthy"


def test_should_promote_backup_on_late_q():
    assert should_promote_backup("Questionable", hours_to_kickoff=2.5) is True
    assert should_promote_backup("Questionable", hours_to_kickoff=10.0) is False
    assert should_promote_backup("Out", hours_to_kickoff=48.0) is True


def test_late_injury_risk_ramps():
    early = late_injury_risk("Questionable", hours_to_kickoff=48.0)
    mid = late_injury_risk("Questionable", hours_to_kickoff=8.0)
    late = late_injury_risk("Questionable", hours_to_kickoff=2.0)
    assert early == 0.55
    assert mid > early
    assert late == 1.0


def test_backup_late_yard_cut_heavier():
    yards_early, meta_e = late_yard_adjustment(
        base_yards=240.0, is_backup=True, hours_to_kickoff=48.0
    )
    yards_late, meta_l = late_yard_adjustment(
        base_yards=240.0, is_backup=True, hours_to_kickoff=4.0
    )
    assert yards_late < yards_early
    assert meta_l.get("backup_late_cut") is True
    assert meta_e.get("yard_cut") == 25.0


def test_questionable_escalate_yard_cut():
    yards, meta = late_yard_adjustment(
        base_yards=260.0,
        injury_status="Questionable",
        hours_to_kickoff=2.0,
    )
    assert yards <= 260.0 - 28.0 + 0.1
    assert meta["effective_status"] == "out"
