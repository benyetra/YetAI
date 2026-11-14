"""Per-day NHL projection accuracy → unified bucket shape.

Six buckets across goalies, player shots, and team totals. Each prediction
type contributes one O/U bucket (sportsbook-line calls) and one MAE bucket so
the dashboard always has a model-quality signal even when no graded calls exist.
Team shots has no projection writer, so it has no tiles.

Daily tiles, the window overview and per-row results all read the rows from
``_nhl_rows`` so a row, a tile and the overview cannot disagree.
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
    ou_row_result,
    overview_item_from_markets,
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


def _fetch(db: Session, model: Any, start: date_type, end: date_type) -> list[Any]:
    return (
        db.query(model).filter(model.game_date >= start, model.game_date <= end).all()
    )


def _latest_by_key(rows: list[Any], key_fn) -> list[Any]:
    """One prediction per key, highest id wins (same rule as the API list's dedupe_keys)."""
    latest: dict[Any, Any] = {}
    for r in sorted(rows, key=lambda r: r.id or 0):
        latest[key_fn(r)] = r
    return list(latest.values())


def _nhl_rows(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, list[dict[str, Any]]]:
    """Merged projection+actual rows for the three NHL O/U markets over [start, end].

    The one row builder behind daily tiles, window overview and per-row results.
    Actuals are keyed with the game date (a player/goalie/matchup recurs across a
    window); totals join on team ids because the boxscore and the projection writer
    spell team names differently and "New York" is two teams.
    ``actual_expected`` is True when grading ran for that date in that market, so a
    missing player actual reads as "dnp" rather than "ungraded".
    """
    goalie_actuals = _fetch(db, NHLGoalieActuals, start, end)
    by_gid = {(a.goalie_id, a.game_date): a for a in goalie_actuals}
    goalie_dates = {a.game_date for a in goalie_actuals}
    goalie_rows = []
    for p in _latest_by_key(
        _fetch(db, NHLGoaliePredictions, start, end),
        lambda p: (p.goalie_id, p.game_date),
    ):
        a = by_gid.get((p.goalie_id, p.game_date))
        # A superseded starter's row is kept for history but is not a call: his
        # full-game line must not be graded against relief-minutes saves.
        scratched = bool(p.was_scratch)
        goalie_rows.append(
            {
                "id": p.id,
                "game_date": p.game_date,
                "predicted_saves": p.predicted_saves,
                "saves_line": p.saves_line,
                "betting_pick": (
                    None if scratched else _parse_pick(p.betting_recommendation)
                ),
                "scratched": scratched,
                "actual_saves": None if scratched else (a.actual_saves if a else None),
                "actual_expected": p.game_date in goalie_dates,
            }
        )

    shot_actuals = _fetch(db, NHLPlayerShotsActuals, start, end)
    by_pid = {(a.player_id, a.game_date): a for a in shot_actuals}
    shot_dates = {a.game_date for a in shot_actuals}
    player_shots = []
    for p in _latest_by_key(
        _fetch(db, NHLPlayerShotsPredictions, start, end),
        lambda p: (p.player_id, p.game_date),
    ):
        a = by_pid.get((p.player_id, p.game_date))
        player_shots.append(
            {
                "id": p.id,
                "game_date": p.game_date,
                "predicted_shots": p.predicted_shots,
                "shots_line": p.shots_line,
                "betting_pick": _parse_pick(p.betting_recommendation),
                "actual_shots": a.actual_shots if a else None,
                "actual_expected": p.game_date in shot_dates,
            }
        )

    total_actuals = _fetch(db, NHLTeamTotalsActuals, start, end)
    by_game = {(a.game_date, a.home_team_id, a.away_team_id): a for a in total_actuals}
    total_dates = {a.game_date for a in total_actuals}
    team_totals = []
    for p in _latest_by_key(
        _fetch(db, NHLTeamTotalsPredictions, start, end),
        lambda p: (p.game_date, p.home_team_id, p.away_team_id),
    ):
        a = by_game.get((p.game_date, p.home_team_id, p.away_team_id))
        team_totals.append(
            {
                "id": p.id,
                "game_date": p.game_date,
                "predicted_total_goals": p.predicted_total_goals,
                "draftkings_ou_line": p.draftkings_ou_line,
                "betting_pick": _parse_pick(p.betting_recommendation),
                "actual_total_goals": a.actual_total_goals if a else None,
                "actual_home_goals": a.actual_home_goals if a else None,
                "actual_away_goals": a.actual_away_goals if a else None,
                "actual_expected": p.game_date in total_dates,
            }
        )
    return {
        "goalie": goalie_rows,
        "player_shots": player_shots,
        "team_totals": team_totals,
    }


# (response key in GET /predictions/nhl, row-set key, line field, actual field)
_MARKETS = (
    ("goalie_predictions", "goalie", "saves_line", "actual_saves"),
    ("player_shots", "player_shots", "shots_line", "actual_shots"),
    ("team_totals", "team_totals", "draftkings_ou_line", "actual_total_goals"),
)


def past_row_results(
    db: Session, *, target_date: date_type
) -> dict[str, dict[int, dict[str, Any]]]:
    """{response_key: {projection id: {"actual", "result", ...}}} for one past date."""
    sets = _nhl_rows(db, start=target_date, end=target_date)
    out: dict[str, dict[int, dict[str, Any]]] = {}
    for response_key, rk, line_f, actual_f in _MARKETS:
        rows: dict[int, dict[str, Any]] = {}
        for r in sets[rk]:
            result = ou_row_result(
                line=r[line_f],
                pick=r["betting_pick"],
                actual=r[actual_f],
                actual_expected=r["actual_expected"],
            )
            item: dict[str, Any] = {"actual": r[actual_f], "result": result}
            if r.get("scratched"):
                item["scratched"] = True
            if rk == "team_totals":
                item.update(
                    actual_home_score=r["actual_home_goals"],
                    actual_away_score=r["actual_away_goals"],
                    actual_total_goals=r["actual_total_goals"],
                    recommendation_correct=(
                        result == "hit" if result in ("hit", "miss") else None
                    ),
                )
            rows[r["id"]] = item
        out[response_key] = rows
    return out


def daily_accuracy(db: Session, *, target_date: date_type) -> dict[str, Any]:
    """Build the NHL accuracy summary for `target_date`."""
    r = _nhl_rows(db, start=target_date, end=target_date)
    goalie_rows, player_shots, team_totals = (
        r["goalie"],
        r["player_shots"],
        r["team_totals"],
    )

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

    available = bool(goalie_rows or player_shots or team_totals)
    return assemble(
        date_str=target_date.isoformat(),
        buckets=buckets,
        available=available,
    )


# (diagnostics key, label, row-set key, line field, actual field)
_OVERVIEW_SPECS = (
    ("goalie_saves_ou", "Goalie saves O/U", "goalie", "saves_line", "actual_saves"),
    (
        "player_shots_ou",
        "Player shots O/U",
        "player_shots",
        "shots_line",
        "actual_shots",
    ),
    (
        "team_totals_ou",
        "Team totals O/U",
        "team_totals",
        "draftkings_ou_line",
        "actual_total_goals",
    ),
)


def season_overview(db: Session, *, start: date_type, end: date_type) -> dict[str, Any]:
    """Window NHL accuracy — one population per published O/U market."""
    r = _nhl_rows(db, start=start, end=end)
    markets = {
        label: ou_call_graded_counts(
            r[rk],
            line_field=line_f,
            pick_field="betting_pick",
            actual_field=actual_f,
        )
        for _key, label, rk, line_f, actual_f in _OVERVIEW_SPECS
    }
    return overview_item_from_markets(sport="nhl", label="NHL", markets=markets)


def season_overview_diagnostics(
    db: Session, *, start: date_type, end: date_type
) -> dict[str, Any]:
    """Structured counts for admin/debug — same row sets as ``season_overview``."""
    r = _nhl_rows(db, start=start, end=end)
    parts_out: list[dict[str, Any]] = []
    markets: dict[str, tuple[int, int]] = {}
    for key, label, rk, line_f, actual_f in _OVERVIEW_SPECS:
        bd = ou_call_graded_breakdown(
            r[rk],
            line_field=line_f,
            pick_field="betting_pick",
            actual_field=actual_f,
        )
        c, t = bd["graded_correct"], bd["graded_total"]
        markets[label] = (c, t)
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
        "overview": overview_item_from_markets(
            sport="nhl", label="NHL", markets=markets
        ),
        "parts": parts_out,
    }
