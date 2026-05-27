"""Per-day NHL projection accuracy → unified bucket shape.

Eight buckets across goalies, team shots, player shots, and team totals.
Each prediction type contributes one O/U bucket (sportsbook-line calls)
and one MAE bucket so the dashboard always has a model-quality signal
even when no graded calls exist.

The team/player shot and team totals actuals tables are populated by
the new `collect_*_actuals` Celery tasks (this PR).
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.predictions_models import (
    NHLGoalieActuals,
    NHLGoaliePredictions,
    NHLPlayerShotsActuals,
    NHLPlayerShotsPredictions,
    NHLTeamShotsActuals,
    NHLTeamShotsPredictions,
    NHLTeamTotalsActuals,
    NHLTeamTotalsPredictions,
)
from app.services.accuracy_shared import (
    AccuracyBucket,
    assemble,
    mae_bucket,
    ou_call_bucket,
    ou_call_graded_breakdown,
    ou_call_graded_counts,
    overview_item_from_totals,
)


def _parse_pick(recommendation: Optional[str]) -> Optional[str]:
    """Extract 'over'/'under' from 'OVER 28.5' / 'UNDER 28.5' / 'PASS'."""
    if not recommendation:
        return None
    head = recommendation.strip().split(" ", 1)[0].lower()
    if head in ("over", "o"):
        return "over"
    if head in ("under", "u"):
        return "under"
    return None


def _goalie_rows(db: Session, target_date: date_type) -> list[dict[str, Any]]:
    proj = (
        db.query(NHLGoaliePredictions)
        .filter(NHLGoaliePredictions.game_date == target_date)
        .all()
    )
    actuals = (
        db.query(NHLGoalieActuals)
        .filter(NHLGoalieActuals.game_date == target_date)
        .all()
    )
    by_gid = {a.goalie_id: a for a in actuals}
    return [
        {
            "predicted_saves": p.predicted_saves,
            "saves_line": p.saves_line,
            "betting_pick": _parse_pick(p.betting_recommendation),
            "actual_saves": (
                by_gid.get(p.goalie_id).actual_saves
                if by_gid.get(p.goalie_id)
                else None
            ),
        }
        for p in proj
    ]


def _team_shots_rows(db: Session, target_date: date_type) -> list[dict[str, Any]]:
    """Same row shape on prediction side as actuals — both have a `team_name`
    and `game_date` we key on. The actuals writer already mirrors
    predicted_shots / shots_line / betting_recommendation onto the actuals
    row so we read everything from the actuals table when present.
    """
    proj = (
        db.query(NHLTeamShotsPredictions)
        .filter(NHLTeamShotsPredictions.game_date == target_date)
        .all()
    )
    actuals = (
        db.query(NHLTeamShotsActuals)
        .filter(NHLTeamShotsActuals.game_date == target_date)
        .all()
    )
    by_key = {(a.team_name, a.game_date): a for a in actuals}
    rows: list[dict[str, Any]] = []
    for p in proj:
        a = by_key.get((p.team_name, p.game_date))
        rows.append(
            {
                "predicted_shots": p.predicted_shots,
                "shots_line": p.shots_line,
                "betting_pick": _parse_pick(p.betting_recommendation),
                "actual_shots": a.actual_shots if a else None,
            }
        )
    return rows


def _player_shots_rows(db: Session, target_date: date_type) -> list[dict[str, Any]]:
    proj = (
        db.query(NHLPlayerShotsPredictions)
        .filter(NHLPlayerShotsPredictions.game_date == target_date)
        .all()
    )
    actuals = (
        db.query(NHLPlayerShotsActuals)
        .filter(NHLPlayerShotsActuals.game_date == target_date)
        .all()
    )
    by_pid = {a.player_id: a for a in actuals}
    rows: list[dict[str, Any]] = []
    for p in proj:
        a = by_pid.get(p.player_id)
        rows.append(
            {
                "predicted_shots": p.predicted_shots,
                "shots_line": p.shots_line,
                "betting_pick": _parse_pick(p.betting_recommendation),
                "actual_shots": a.actual_shots if a else None,
            }
        )
    return rows


def _team_totals_rows(db: Session, target_date: date_type) -> list[dict[str, Any]]:
    proj = (
        db.query(NHLTeamTotalsPredictions)
        .filter(NHLTeamTotalsPredictions.game_date == target_date)
        .all()
    )
    actuals = (
        db.query(NHLTeamTotalsActuals)
        .filter(NHLTeamTotalsActuals.game_date == target_date)
        .all()
    )
    # Match on (home_team_name, away_team_name) — predictions don't carry
    # game_id but the (home, away, date) tuple is unique per slate.
    by_key = {(a.home_team_name, a.away_team_name): a for a in actuals}
    rows: list[dict[str, Any]] = []
    for p in proj:
        a = by_key.get((p.home_team_name, p.away_team_name))
        rows.append(
            {
                "predicted_total_goals": p.predicted_total_goals,
                "draftkings_ou_line": p.draftkings_ou_line,
                "betting_pick": _parse_pick(p.betting_recommendation),
                "actual_total_goals": a.actual_total_goals if a else None,
            }
        )
    return rows


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Build the NHL accuracy summary for `target_date`."""
    goalie_rows = _goalie_rows(db, target_date)
    team_shots = _team_shots_rows(db, target_date)
    player_shots = _player_shots_rows(db, target_date)
    team_totals = _team_totals_rows(db, target_date)

    buckets: list[AccuracyBucket] = [
        # ---- Goalies ----------------------------------------------------
        ou_call_bucket(
            goalie_rows,
            line_field="saves_line",
            pick_field="betting_pick",
            actual_field="actual_saves",
            projected_field="predicted_saves",
            label="Goalie Saves O/U",
            key="goalie_saves_ou",
        ),
        mae_bucket(
            goalie_rows,
            projected_field="predicted_saves",
            actual_field="actual_saves",
            label="Goalie Saves",
            key="goalie_saves_mae",
            unit_label="saves",
        ),
        # ---- Team shots -------------------------------------------------
        ou_call_bucket(
            team_shots,
            line_field="shots_line",
            pick_field="betting_pick",
            actual_field="actual_shots",
            projected_field="predicted_shots",
            label="Team Shots O/U",
            key="team_shots_ou",
        ),
        mae_bucket(
            team_shots,
            projected_field="predicted_shots",
            actual_field="actual_shots",
            label="Team Shots",
            key="team_shots_mae",
            unit_label="SOG",
        ),
        # ---- Player shots ----------------------------------------------
        ou_call_bucket(
            player_shots,
            line_field="shots_line",
            pick_field="betting_pick",
            actual_field="actual_shots",
            projected_field="predicted_shots",
            label="Player Shots O/U",
            key="player_shots_ou",
        ),
        mae_bucket(
            player_shots,
            projected_field="predicted_shots",
            actual_field="actual_shots",
            label="Player Shots",
            key="player_shots_mae",
            unit_label="SOG",
        ),
        # ---- Team totals ------------------------------------------------
        ou_call_bucket(
            team_totals,
            line_field="draftkings_ou_line",
            pick_field="betting_pick",
            actual_field="actual_total_goals",
            projected_field="predicted_total_goals",
            label="Team Totals O/U",
            key="team_totals_ou",
        ),
        mae_bucket(
            team_totals,
            projected_field="predicted_total_goals",
            actual_field="actual_total_goals",
            label="Team Totals",
            key="team_totals_mae",
            unit_label="goals",
        ),
    ]

    available = bool(goalie_rows or team_shots or player_shots or team_totals)
    return assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=available,
    )


def _nhl_season_overview_row_sets(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, list[dict[str, Any]]]:
    """Projection+actual row dicts for the four NHL overview O/U sources."""
    proj_g = (
        db.query(NHLGoaliePredictions)
        .filter(
            NHLGoaliePredictions.game_date >= start,
            NHLGoaliePredictions.game_date <= end,
        )
        .all()
    )
    act_g = (
        db.query(NHLGoalieActuals)
        .filter(
            NHLGoalieActuals.game_date >= start,
            NHLGoalieActuals.game_date <= end,
        )
        .all()
    )
    by_gid = {a.goalie_id: a for a in act_g}
    goalie_rows = [
        {
            "predicted_saves": p.predicted_saves,
            "saves_line": p.saves_line,
            "betting_pick": _parse_pick(p.betting_recommendation),
            "actual_saves": (
                by_gid.get(p.goalie_id).actual_saves
                if by_gid.get(p.goalie_id)
                else None
            ),
        }
        for p in proj_g
    ]

    proj_ts = (
        db.query(NHLTeamShotsPredictions)
        .filter(
            NHLTeamShotsPredictions.game_date >= start,
            NHLTeamShotsPredictions.game_date <= end,
        )
        .all()
    )
    act_ts = (
        db.query(NHLTeamShotsActuals)
        .filter(
            NHLTeamShotsActuals.game_date >= start,
            NHLTeamShotsActuals.game_date <= end,
        )
        .all()
    )
    by_ts = {(a.team_name, a.game_date): a for a in act_ts}
    team_shots: list[dict[str, Any]] = []
    for p in proj_ts:
        a = by_ts.get((p.team_name, p.game_date))
        team_shots.append(
            {
                "predicted_shots": p.predicted_shots,
                "shots_line": p.shots_line,
                "betting_pick": _parse_pick(p.betting_recommendation),
                "actual_shots": a.actual_shots if a else None,
            }
        )

    proj_ps = (
        db.query(NHLPlayerShotsPredictions)
        .filter(
            NHLPlayerShotsPredictions.game_date >= start,
            NHLPlayerShotsPredictions.game_date <= end,
        )
        .all()
    )
    act_ps = (
        db.query(NHLPlayerShotsActuals)
        .filter(
            NHLPlayerShotsActuals.game_date >= start,
            NHLPlayerShotsActuals.game_date <= end,
        )
        .all()
    )
    by_pid = {a.player_id: a for a in act_ps}
    player_shots: list[dict[str, Any]] = []
    for p in proj_ps:
        a = by_pid.get(p.player_id)
        player_shots.append(
            {
                "predicted_shots": p.predicted_shots,
                "shots_line": p.shots_line,
                "betting_pick": _parse_pick(p.betting_recommendation),
                "actual_shots": a.actual_shots if a else None,
            }
        )

    proj_tt = (
        db.query(NHLTeamTotalsPredictions)
        .filter(
            NHLTeamTotalsPredictions.game_date >= start,
            NHLTeamTotalsPredictions.game_date <= end,
        )
        .all()
    )
    act_tt = (
        db.query(NHLTeamTotalsActuals)
        .filter(
            NHLTeamTotalsActuals.game_date >= start,
            NHLTeamTotalsActuals.game_date <= end,
        )
        .all()
    )
    by_tt = {(a.home_team_name, a.away_team_name): a for a in act_tt}
    team_totals: list[dict[str, Any]] = []
    for p in proj_tt:
        a = by_tt.get((p.home_team_name, p.away_team_name))
        team_totals.append(
            {
                "predicted_total_goals": p.predicted_total_goals,
                "draftkings_ou_line": p.draftkings_ou_line,
                "betting_pick": _parse_pick(p.betting_recommendation),
                "actual_total_goals": a.actual_total_goals if a else None,
            }
        )

    return {
        "goalie": goalie_rows,
        "team_shots": team_shots,
        "player_shots": player_shots,
        "team_totals": team_totals,
    }


def season_overview(db: Session, *, start: date_type, end: date_type) -> dict[str, Any]:
    """Window NHL accuracy — combined O/U hit rate across graded line plays."""
    r = _nhl_season_overview_row_sets(db, start=start, end=end)
    parts = [
        ou_call_graded_counts(
            r["goalie"],
            line_field="saves_line",
            pick_field="betting_pick",
            actual_field="actual_saves",
        ),
        ou_call_graded_counts(
            r["team_shots"],
            line_field="shots_line",
            pick_field="betting_pick",
            actual_field="actual_shots",
        ),
        ou_call_graded_counts(
            r["player_shots"],
            line_field="shots_line",
            pick_field="betting_pick",
            actual_field="actual_shots",
        ),
        ou_call_graded_counts(
            r["team_totals"],
            line_field="draftkings_ou_line",
            pick_field="betting_pick",
            actual_field="actual_total_goals",
        ),
    ]
    correct = sum(p[0] for p in parts)
    total = sum(p[1] for p in parts)
    return overview_item_from_totals(
        sport="nhl", label="NHL", correct=correct, total=total
    )


def season_overview_diagnostics(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, Any]:
    """Structured counts for admin/debug — same row sets as ``season_overview``."""
    r = _nhl_season_overview_row_sets(db, start=start, end=end)
    specs = [
        (
            "goalie_saves_ou",
            "Goalie saves O/U",
            "goalie",
            "saves_line",
            "betting_pick",
            "actual_saves",
        ),
        (
            "team_shots_ou",
            "Team shots O/U",
            "team_shots",
            "shots_line",
            "betting_pick",
            "actual_shots",
        ),
        (
            "player_shots_ou",
            "Player shots O/U",
            "player_shots",
            "shots_line",
            "betting_pick",
            "actual_shots",
        ),
        (
            "team_totals_ou",
            "Team totals O/U",
            "team_totals",
            "draftkings_ou_line",
            "betting_pick",
            "actual_total_goals",
        ),
    ]
    parts_out: list[dict[str, Any]] = []
    correct = 0
    total = 0
    for key, label, rk, lf, pf, af in specs:
        rows = r[rk]
        bd = ou_call_graded_breakdown(
            rows, line_field=lf, pick_field=pf, actual_field=af
        )
        c, t = bd["graded_correct"], bd["graded_total"]
        correct += c
        total += t
        parts_out.append(
            {
                "key": key,
                "label": label,
                "kind": "ou",
                "breakdown": bd,
                "graded_correct": c,
                "graded_total": t,
            }
        )
    return {
        "sport": "nhl",
        "date_bounds": {"start": start.isoformat(), "end": end.isoformat()},
        "overview": overview_item_from_totals(
            sport="nhl", label="NHL", correct=correct, total=total
        ),
        "parts": parts_out,
    }
