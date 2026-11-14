"""
Prediction endpoints — surfaces YetiBets' ML prediction tables (the pred_*
schema) via YetAI's REST API.

Each sport endpoint returns the most recent rows from the highest-value
prediction tables for that sport. PRO and ELITE subscribers only.

Today's auth path returns subscription_tier='pro' for any valid-looking JWT
(see app/main.py:get_current_user), so the tier guard is effectively permissive
in dev; the guard will start enforcing real tiers once auth is fixed.
"""

import importlib
from datetime import date as date_type, timedelta
from typing import Any, Callable, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import DateTime, func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_admin
from app.core.database import get_db
from app.models.predictions_models import (
    AssistsProjections,
    BlocksProjections,
    GameActuals,
    GameProjections,
    Homer,
    KickerPredictions,
    NFLAnytimeTDPredictions,
    NFLGameLines,
    NFLSpreadProjections,
    NFLTotalsProjections,
    NBAGameLines,
    NBASpreadProjections,
    NBATotalsProjections,
    NHLGoaliePredictions,
    NHLPlayerShotsPredictions,
    NHLTeamTotalsPredictions,
    Pitcher,
    PointsProjections,
    PRAProjections,
    ProjectedHits,
    ProjectedHomers,
    QBPredictions,
    ReboundsProjections,
    RecentGames,
    RecvYdsPredictions,
    StealsProjections,
    StrikeoutActuals,
    StrikeoutProjections,
    ThreePointProjections,
    WNBAAssistsProjections,
    WNBAGameLines,
    WNBAPointsProjections,
    WNBAPRAProjections,
    WNBARecentGames,
    WNBAReboundsProjections,
    WNBASpreadProjections,
    WNBAThreePtMadeProjections,
    WNBATotalsProjections,
)
from app.services.etl.grading_window import eastern_today
from app.services.etl.nba._season import season_opener
from app.services.etl.yetiwatch.news import attach_news_to_rows
from app.services.mlb_strikeout_pick import enrich_strikeout_projection_row
from app.services.player_prop_projection_display import (
    attach_mlb_batter_team_opponent,
    attach_team_opponent_fields,
    enrich_prop_rows,
    enrich_strikeout_display_row,
)

router = APIRouter(prefix="/api/v1/predictions", tags=["predictions"])

ALLOWED_TIERS = {"pro", "elite", "PRO", "ELITE"}
DEFAULT_LIMIT = 50
# Ranked by minutes, this covers the rotations of a 12-game NBA slate.
NBA_PROP_DEFAULT_LIMIT = 200
WNBA_PROP_DEFAULT_LIMIT = 75
MAX_LIMIT = 500
ANYTIME_TD_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})


def require_paid_tier(current_user: dict = Depends(get_current_user)) -> dict:
    """Guard: only PRO/ELITE subscribers can read predictions."""
    tier = current_user.get("subscription_tier", "free")
    if tier not in ALLOWED_TIERS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Predictions require a PRO or ELITE subscription.",
        )
    return current_user


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


def _safe_tz(tz: str) -> str:
    """Validate the IANA timezone string. Falls back to UTC if invalid."""
    try:
        ZoneInfo(tz)
        return tz
    except (ZoneInfoNotFoundError, ValueError):
        return "UTC"


def _query_recent(
    db: Session,
    model: Any,
    date_col_name: str | None,
    target_date: date_type | None,
    limit: int,
    *,
    tz: str = "UTC",
    dedupe_keys: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    q = db.query(model)
    if date_col_name and target_date is not None:
        col = getattr(model, date_col_name)
        if isinstance(col.type, DateTime):
            # Naive DateTime columns are stored as UTC. Convert to the user's
            # timezone, then extract the calendar date so the picker matches
            # what the user sees locally.
            local_col = func.timezone(tz, func.timezone("UTC", col))
            q = q.filter(func.date(local_col) == target_date)
        else:
            # Date columns: compare directly.
            q = q.filter(col == target_date)
    if hasattr(model, "id"):
        q = q.order_by(model.id.desc())
    fetch_limit = limit * 5 if dedupe_keys else limit
    rows = [_row_to_dict(r) for r in q.limit(fetch_limit).all()]
    if not dedupe_keys:
        return rows[:limit]
    latest: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(k) for k in dedupe_keys)
        if key not in latest:
            latest[key] = row
    return list(latest.values())[:limit]


def _is_past_date(target_date: date_type | None) -> bool:
    """True for an explicit date before today in Eastern time (a graded slate)."""
    return target_date is not None and target_date < eastern_today()


def _merge_past_results(
    payload: dict[str, Any], sport: str, db: Session, target_date: date_type | None
) -> dict[str, Any]:
    """Attach each row's graded ``actual``/``result`` for a past date.

    Merges ``<sport>_accuracy_service.past_row_results`` into the response lists
    by key and row ``id``; rows the grader has no entry for read ``ungraded``.
    Today/future dates are returned unchanged.
    """
    if not _is_past_date(target_date):
        return payload
    service = importlib.import_module(f"app.services.{sport}_accuracy_service")
    results = service.past_row_results(db, target_date=target_date)
    for key, by_id in results.items():
        rows = payload.get(key)
        if not rows:
            continue
        payload[key] = [
            (
                {**row, **by_id[row.get("id")]}
                if row.get("id") in by_id
                else {**row, "result": "ungraded"}
            )
            for row in rows
        ]
    return payload


def _nfl_slate_season_week(
    target_date: date_type | None,
) -> tuple[int, int]:
    """Resolve NFL season/week for API fallback when slate date has no rows."""
    from app.services.etl.nfl.nfl_common import (
        get_current_nfl_week,
        resolve_nfl_season,
    )

    ref = target_date if target_date is not None else date_type.today()
    season = resolve_nfl_season(None)
    week = get_current_nfl_week(season, today=ref)
    return season, week


def _nfl_week_date_bounds(season: int, week: int) -> tuple[date_type, date_type]:
    from app.services.etl.nfl.nfl_common import _first_regular_season_thursday

    start = _first_regular_season_thursday(season) + timedelta(days=(week - 1) * 7)
    return start, start + timedelta(days=6)


def _query_nfl_by_season_week(
    db: Session,
    model: Any,
    season: int,
    week: int,
    limit: int,
    *,
    dedupe_keys: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    q = db.query(model).filter(model.season == season, model.week == week)
    if hasattr(model, "id"):
        q = q.order_by(model.id.desc())
    fetch_limit = limit * 5 if dedupe_keys else limit
    rows = [_row_to_dict(r) for r in q.limit(fetch_limit).all()]
    if not dedupe_keys:
        return rows[:limit]
    latest: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(k) for k in dedupe_keys)
        if key not in latest:
            latest[key] = row
    return list(latest.values())[:limit]


def _query_nfl_by_game_date_range(
    db: Session,
    model: Any,
    date_col_name: str,
    start: date_type,
    end: date_type,
    limit: int,
    *,
    tz: str = "UTC",
) -> list[dict[str, Any]]:
    col = getattr(model, date_col_name)
    q = db.query(model)
    if isinstance(col.type, DateTime):
        local_col = func.date(func.timezone(tz, func.timezone("UTC", col)))
        q = q.filter(local_col >= start, local_col <= end)
    else:
        q = q.filter(col >= start, col <= end)
    if hasattr(model, "id"):
        q = q.order_by(model.id.desc())
    return [_row_to_dict(r) for r in q.limit(limit).all()]


def _query_nfl_latest_deduped(
    db: Session,
    model: Any,
    limit: int,
    *,
    dedupe_keys: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Latest row per dedupe key when models lack season/week (e.g. kickers)."""
    q = db.query(model)
    if hasattr(model, "id"):
        q = q.order_by(model.id.desc())
    fetch_limit = limit * 5
    rows = [_row_to_dict(r) for r in q.limit(fetch_limit).all()]
    latest: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(k) for k in dedupe_keys)
        if key not in latest:
            latest[key] = row
    return list(latest.values())[:limit]


def _query_recent_nfl_with_fallback(
    db: Session,
    model: Any,
    date_col_name: str | None,
    target_date: date_type | None,
    limit: int,
    *,
    tz: str = "UTC",
    dedupe_keys: tuple[str, ...] | None = None,
    latest_dedupe_keys: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    rows = _query_recent(
        db,
        model,
        date_col_name,
        target_date,
        limit,
        tz=tz,
        dedupe_keys=dedupe_keys,
    )
    if rows or target_date is None:
        return rows

    season, week = _nfl_slate_season_week(target_date)
    if hasattr(model, "season") and hasattr(model, "week"):
        return _query_nfl_by_season_week(
            db,
            model,
            season,
            week,
            limit,
            dedupe_keys=dedupe_keys,
        )
    if date_col_name:
        start, end = _nfl_week_date_bounds(season, week)
        range_rows = _query_nfl_by_game_date_range(
            db, model, date_col_name, start, end, limit, tz=tz
        )
        if range_rows:
            return range_rows
    if latest_dedupe_keys:
        return _query_nfl_latest_deduped(
            db, model, limit, dedupe_keys=latest_dedupe_keys
        )
    return []


def _query_nfl_anytime_td_predictions(
    db: Session,
    target_date: date_type | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Anytime-TD rows for skill positions, deduped; edge DESC then P(TD) DESC."""
    from sqlalchemy import nullslast

    def _fetch(*, season: int | None = None, week: int | None = None) -> list[Any]:
        q = db.query(NFLAnytimeTDPredictions).filter(
            NFLAnytimeTDPredictions.position.in_(ANYTIME_TD_POSITIONS)
        )
        if target_date is not None and season is None:
            q = q.filter(NFLAnytimeTDPredictions.game_date == target_date)
        if season is not None and week is not None:
            q = q.filter(
                NFLAnytimeTDPredictions.season == season,
                NFLAnytimeTDPredictions.week == week,
            )
        fetch_limit = limit * 5
        return (
            q.order_by(
                nullslast(NFLAnytimeTDPredictions.edge.desc()),
                NFLAnytimeTDPredictions.td_probability.desc(),
            )
            .limit(fetch_limit)
            .all()
        )

    def _sort_key(row: Any) -> tuple:
        edge = getattr(row, "edge", None)
        return (
            edge is None,
            -(float(edge) if edge is not None else 0.0),
            -float(row.td_probability),
        )

    def _dedupe_sort(raw: list[Any]) -> list[dict[str, Any]]:
        latest: dict[tuple[Any, ...], Any] = {}
        for row in raw:
            key = (row.season, row.week, row.player_id)
            if key not in latest:
                latest[key] = row
        deduped = sorted(latest.values(), key=_sort_key)
        return [_row_to_dict(r) for r in deduped[:limit]]

    if target_date is None:
        return _dedupe_sort(_fetch())

    rows = _dedupe_sort(_fetch())
    if rows:
        return rows

    season, week = _nfl_slate_season_week(target_date)
    return _dedupe_sort(_fetch(season=season, week=week))


def _load_wnba_season_minutes_avg(
    db: Session, player_ids: list[int], as_of: date_type
) -> dict[int, float]:
    """Season-to-date MPG from pred_wnba_recent_games (games strictly before as_of)."""
    if not player_ids:
        return {}
    rows = (
        db.query(
            WNBARecentGames.player_id,
            func.avg(WNBARecentGames.minutes).label("season_mpg"),
        )
        .filter(
            WNBARecentGames.player_id.in_(player_ids),
            WNBARecentGames.game_date < as_of,
            WNBARecentGames.minutes.isnot(None),
            WNBARecentGames.minutes > 0,
        )
        .group_by(WNBARecentGames.player_id)
        .all()
    )
    return {int(r.player_id): float(r.season_mpg) for r in rows}


def _load_nba_season_minutes_avg(
    db: Session, player_ids: list[int], as_of: date_type
) -> dict[int, float]:
    """This season's MPG from pred_recent_games (games strictly before as_of)."""
    if not player_ids:
        return {}
    rows = (
        db.query(
            RecentGames.player_id,
            func.avg(RecentGames.minutes).label("season_mpg"),
        )
        .filter(
            RecentGames.player_id.in_(player_ids),
            RecentGames.game_date >= season_opener(as_of),
            RecentGames.game_date < as_of,
            RecentGames.minutes > 0,
        )
        .group_by(RecentGames.player_id)
        .all()
    )
    return {int(r.player_id): float(r.season_mpg) for r in rows}


def _query_wnba_props_by_season_minutes(
    db: Session,
    model: Any,
    target_date: date_type | None,
    limit: int,
    *,
    tz: str = "UTC",
) -> list[dict[str, Any]]:
    """Return prop projections for a slate, ranked by season MPG (not insert order)."""
    return _query_props_by_minutes(
        db, model, target_date, limit, _load_wnba_season_minutes_avg, tz=tz
    )


def _query_nba_props_by_season_minutes(
    db: Session,
    model: Any,
    target_date: date_type | None,
    limit: int,
    *,
    tz: str = "UTC",
) -> list[dict[str, Any]]:
    """Return prop projections for a slate, ranked by season MPG (not insert order).

    Insert order follows the roster table's team order (API-Sports ids,
    Washington last), so it says nothing about which players matter."""
    return _query_props_by_minutes(
        db, model, target_date, limit, _load_nba_season_minutes_avg, tz=tz
    )


def _query_props_by_minutes(
    db: Session,
    model: Any,
    target_date: date_type | None,
    limit: int,
    load_mpg: Callable[[Session, list[int], date_type], dict[int, float]],
    *,
    tz: str = "UTC",
) -> list[dict[str, Any]]:
    if target_date is None:
        return _query_recent(db, model, "date", None, limit, tz=tz)

    rows = [
        _row_to_dict(r) for r in db.query(model).filter(model.date == target_date).all()
    ]
    if not rows:
        return []
    past = _is_past_date(target_date)
    if past:
        # Past slates show every graded row (the tiles count them all), one per
        # player per date: the latest projection, as the accuracy service keeps.
        latest: dict[Any, dict[str, Any]] = {}
        for r in sorted(rows, key=lambda r: r.get("id") or 0):
            latest[
                r.get("player_id") if r.get("player_id") is not None else r.get("id")
            ] = r
        rows = list(latest.values())

    player_ids = [int(r["player_id"]) for r in rows if r.get("player_id") is not None]
    mpg_by_player = load_mpg(db, player_ids, target_date)
    rows.sort(
        key=lambda r: (
            mpg_by_player.get(int(r["player_id"]), 0.0)
            if r.get("player_id") is not None
            else 0.0
        ),
        reverse=True,
    )
    return rows if past else rows[:limit]


@router.get("/health")
def health() -> dict[str, Any]:
    """Public — confirms the predictions module is wired up."""
    return {"status": "ok", "module": "predictions", "tables_exposed": 15}


@router.get("/accuracy/overview/diagnostics")
async def predictions_accuracy_overview_diagnostics(
    window: Literal["season", "last_30"] = Query("season"),
    _admin: dict = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Admin-only: row-level breakdown for Stat Projections overview denominators."""
    from app.services.accuracy_overview_service import (
        build_accuracy_overview_diagnostics,
    )

    return build_accuracy_overview_diagnostics(db, window=window)


@router.get("/accuracy/overview")
def predictions_accuracy_overview(
    window: Literal["season", "last_30"] = Query("season"),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Season-to-date (or last 30 days) global model accuracy per league."""
    from app.services.accuracy_overview_service import build_accuracy_overview

    return build_accuracy_overview(db, window=window)


def _attach_p_over_total(row: dict[str, Any], line: float) -> dict[str, Any]:
    """Add empirical P(over) at ``line`` from MC rates stored on the row."""
    from app.services.etl.mlb.monte_carlo import p_over_total_for_game_row

    p_over = p_over_total_for_game_row(row, line)
    return {
        **row,
        "total_line": line,
        "p_over_total": p_over,
        "p_under_total": round(1.0 - p_over, 4),
    }


@router.get("/mlb/p-over-total")
def mlb_p_over_total(
    game_id: int = Query(..., description="MLB game_pk"),
    line: float = Query(..., description="Total runs line (e.g. 8.5)"),
    target_date: date_type | None = Query(default=None, alias="date"),
    n_sims: int = Query(default=8000, ge=500, le=50000),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """P(total runs > line) for one game from Monte Carlo rates on the projection."""
    from datetime import date as date_cls

    from app.services.etl.mlb.monte_carlo import p_over_total_for_game_row

    lookup_date = target_date or date_cls.today()
    row = (
        db.query(GameProjections)
        .filter(
            GameProjections.game_id == game_id,
            GameProjections.date == lookup_date,
        )
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No game projection for game_id={game_id} on {lookup_date}",
        )

    payload = _row_to_dict(row)
    p_over = p_over_total_for_game_row(payload, line, n_sims=n_sims)
    return {
        "game_id": game_id,
        "date": lookup_date.isoformat(),
        "home_team": payload.get("home_team"),
        "away_team": payload.get("away_team"),
        "total_line": line,
        "p_over_total": p_over,
        "p_under_total": round(1.0 - p_over, 4),
        "n_sims": n_sims,
        "projected_total": payload.get("projected_total"),
        "home_win_prob": payload.get("home_win_prob"),
        "sim_distribution": payload.get("sim_distribution"),
    }


@router.get("/mlb")
def mlb_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    tz: str = Query(default="UTC"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    total_line: float | None = Query(
        default=None,
        description="When set, each game_projection includes p_over_total at this line",
    ),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recent MLB props: strikeouts, game slate, batter boards, HR picks.

    Each strikeout projection row is enriched with actual_strikeouts and
    actual_innings_pitched when the corresponding StrikeoutActuals row
    exists for the same date — the frontend uses these to render
    actual-vs-projection columns on past-date views.

    Game projections are enriched with final scores and ml/spread/total
    grading flags from pred_game_actuals when available.

    Pass ``total_line`` (e.g. 8.5) to add ``p_over_total`` / ``p_under_total`` on
    each game projection (empirical Monte Carlo using stored sim rates).
    """
    tz = _safe_tz(tz)
    strikeouts = _query_recent(
        db, StrikeoutProjections, "date", target_date, limit, tz=tz
    )
    # Drop rows with blank pitcher_name (incomplete ETL writes) and dedupe by
    # pitcher_id so the same pitcher doesn't appear twice in the table.
    seen_pitchers: set[str] = set()
    pitcher_meta: dict[str, Pitcher] = {
        p.pitcher_id: p for p in db.query(Pitcher).all()
    }
    cleaned_strikeouts = []
    for row in strikeouts:
        name = (row.get("pitcher_name") or "").strip()
        if not name:
            continue
        pid = row.get("pitcher_id")
        if pid in seen_pitchers:
            continue
        seen_pitchers.add(pid)
        meta = pitcher_meta.get(str(pid)) if pid is not None else None
        # A past row keeps the line it was published with; today's live pitcher
        # line/flags would grade yesterday's pick against a different number.
        live = not _is_past_date(target_date)
        if meta:
            line = row.get("fanduel_line")
            fd_point = getattr(meta, "fanduel_point", None)
            if live and (line is None or line <= 0) and fd_point and fd_point > 0:
                row = {**row, "fanduel_line": fd_point}
            row = {
                **row,
                "team_name": getattr(meta, "team", None),
                "opponent_team_name": getattr(meta, "opponent", None),
                "team": getattr(meta, "team", None),
                "opponent": getattr(meta, "opponent", None),
            }
        enriched = enrich_strikeout_projection_row(
            row,
            fanduel_flag=getattr(meta, "fanduel_flag", None) if meta and live else None,
            prob_over=getattr(meta, "prob_over", None) if meta and live else None,
            pick_edge_pct=(
                getattr(meta, "pick_edge_pct", None) if meta and live else None
            ),
        )
        cleaned_strikeouts.append(enrich_strikeout_display_row(enriched))

    # Merge actuals for the selected date. When target_date is None (today),
    # actuals likely don't exist yet — the lookup returns an empty dict and
    # rows pass through unchanged.
    actuals_date = target_date
    if actuals_date is None and cleaned_strikeouts:
        first_date = cleaned_strikeouts[0].get("date")
        if first_date is not None:
            actuals_date = first_date
    if actuals_date is not None:
        actuals_by_pid = {
            r.pitcher_id: r
            for r in db.query(StrikeoutActuals)
            .filter(StrikeoutActuals.date == actuals_date)
            .all()
        }
        for row in cleaned_strikeouts:
            actual = actuals_by_pid.get(row.get("pitcher_id"))
            row["actual_strikeouts"] = actual.actual_strikeouts if actual else None
            row["actual_innings_pitched"] = (
                actual.actual_innings_pitched if actual else None
            )

    game_rows = _query_recent(db, GameProjections, "date", target_date, limit, tz=tz)
    if total_line is not None:
        game_rows = [_attach_p_over_total(r, total_line) for r in game_rows]

    game_actuals_date = target_date
    if game_actuals_date is None and game_rows:
        first_game_date = game_rows[0].get("date")
        if first_game_date is not None:
            game_actuals_date = first_game_date
    if game_actuals_date is not None:
        from app.services.mlb_game_picks import enrich_game_projection_row

        actuals_by_gid = {
            a.game_id: a
            for a in db.query(GameActuals)
            .filter(GameActuals.date == game_actuals_date)
            .all()
        }
        enriched_games: list[dict[str, Any]] = []
        for row in game_rows:
            actual = actuals_by_gid.get(row.get("game_id"))
            if actual:
                row = {
                    **row,
                    "actual_home_score": actual.home_score,
                    "actual_away_score": actual.away_score,
                    "actual_total_runs": actual.total_runs,
                    "actual_winner": actual.winner,
                    "ml_correct": actual.ml_correct,
                    "spread_correct": actual.spread_correct,
                    "total_correct": actual.total_correct,
                }
            enriched_games.append(enrich_game_projection_row(row))
        game_rows = enriched_games

    cleaned_strikeouts = attach_news_to_rows(
        db,
        cleaned_strikeouts,
        sport="mlb",
        entity_key="pitcher_id",
        date_key="date",
    )

    projected_hits = attach_mlb_batter_team_opponent(
        db, _query_recent(db, ProjectedHits, "date", target_date, limit, tz=tz)
    )
    projected_homers = attach_mlb_batter_team_opponent(
        db, _query_recent(db, ProjectedHomers, "date", target_date, limit, tz=tz)
    )
    home_run_predictions = attach_team_opponent_fields(
        _query_recent(db, Homer, "game_time", target_date, limit, tz=tz)
    )

    return _merge_past_results(
        {
            "strikeout_projections": cleaned_strikeouts,
            "game_projections": game_rows,
            "projected_hits": projected_hits,
            "projected_homers": projected_homers,
            "home_run_predictions": home_run_predictions,
        },
        "mlb",
        db,
        target_date,
    )


@router.get("/mlb/accuracy")
def mlb_accuracy(
    target_date: date_type = Query(..., alias="date"),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Per-day projection accuracy for the AccuracySummary cards.

    Returns three buckets: pitcher_ks_ou (FanDuel-line call accuracy +
    K MAE), projected_hits (success rate for batters projected to get
    hits), and projected_homers (success rate for batters projected to
    hit a HR). `available` is true when any data exists for the date.

    `date` is required — meaningful summaries need a fully-played day.
    """
    from app.services.mlb_accuracy_service import daily_accuracy

    return daily_accuracy(db, target_date=target_date)


@router.get("/nba")
def nba_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    tz: str = Query(default="UTC"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    prop_limit: int = Query(
        default=NBA_PROP_DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description="Max player prop rows per stat; ranked by season minutes per game.",
    ),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """NBA: game totals O/U and spreads, plus points, assists, rebounds, etc.

    Player props return up to ``prop_limit`` rows per stat for the requested
    date, ordered by this season's minutes per game.
    """
    from app.services.game_projection_schedule import attach_game_times_from_lines

    tz = _safe_tz(tz)
    spreads = _query_recent(
        db, NBASpreadProjections, "game_date", target_date, limit, tz=tz
    )
    totals = _query_recent(
        db, NBATotalsProjections, "game_date", target_date, limit, tz=tz
    )
    spreads = attach_game_times_from_lines(db, spreads, NBAGameLines)
    totals = attach_game_times_from_lines(db, totals, NBAGameLines)
    props = {
        "points": (PointsProjections, "points"),
        "assists": (AssistsProjections, "assists"),
        "rebounds": (ReboundsProjections, "rebounds"),
        "three_point": (ThreePointProjections, "three_pt_made"),
        "steals": (StealsProjections, "steals"),
        "blocks": (BlocksProjections, "blocks"),
        "pra": (PRAProjections, "pra"),
    }
    return _merge_past_results(
        {
            "totals": totals,
            "spreads": spreads,
            **{
                key: enrich_prop_rows(
                    _query_nba_props_by_season_minutes(
                        db, model, target_date, prop_limit, tz=tz
                    ),
                    sport="nba",
                    stat=stat,
                    db=db,
                )
                for key, (model, stat) in props.items()
            },
        },
        "nba",
        db,
        target_date,
    )


@router.get("/nfl")
def nfl_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    tz: str = Query(default="UTC"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recent NFL props: QB passing yards, kicker FG, and game spreads/totals."""
    from app.services.game_projection_schedule import attach_game_times_from_lines

    tz = _safe_tz(tz)
    spreads = _query_recent_nfl_with_fallback(
        db, NFLSpreadProjections, "game_date", target_date, limit, tz=tz
    )
    totals = _query_recent_nfl_with_fallback(
        db, NFLTotalsProjections, "game_date", target_date, limit, tz=tz
    )
    spreads = attach_game_times_from_lines(db, spreads, NFLGameLines)
    totals = attach_game_times_from_lines(db, totals, NFLGameLines)
    return _merge_past_results(
        {
            "qb_predictions": enrich_prop_rows(
                _query_recent_nfl_with_fallback(
                    db,
                    QBPredictions,
                    "game_date",
                    target_date,
                    limit,
                    tz=tz,
                    dedupe_keys=("season", "week", "qb_player_id"),
                ),
                sport="nfl",
                stat="passing_yards",
                db=db,
            ),
            "kicker_predictions": attach_team_opponent_fields(
                _query_recent_nfl_with_fallback(
                    db,
                    KickerPredictions,
                    "game_date",
                    target_date,
                    limit,
                    tz=tz,
                    latest_dedupe_keys=("kicker_player_id",),
                )
            ),
            "anytime_td_predictions": _query_nfl_anytime_td_predictions(
                db, target_date, limit
            ),
            "receiving_yards_predictions": enrich_prop_rows(
                _query_recent_nfl_with_fallback(
                    db,
                    RecvYdsPredictions,
                    "game_date",
                    target_date,
                    limit,
                    tz=tz,
                    dedupe_keys=("season", "week", "player_id"),
                ),
                sport="nfl",
                stat="receiving_yards",
                db=db,
            ),
            "spreads": spreads,
            "totals": totals,
        },
        "nfl",
        db,
        target_date,
    )


@router.get("/nba/accuracy")
def nba_accuracy(
    target_date: date_type = Query(..., alias="date"),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Per-day NBA projection accuracy → unified bucket shape."""
    from app.services.nba_accuracy_service import daily_accuracy

    return daily_accuracy(db, target_date=target_date)


@router.get("/nfl/accuracy")
def nfl_accuracy(
    target_date: date_type = Query(..., alias="date"),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Per-day NFL projection accuracy → unified bucket shape."""
    from app.services.nfl_accuracy_service import daily_accuracy

    return daily_accuracy(db, target_date=target_date)


@router.get("/nhl")
def nhl_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    tz: str = Query(default="UTC"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Recent NHL props: goalie saves, player SOG, game totals O/U."""
    tz = _safe_tz(tz)
    return _merge_past_results(
        {
            "goalie_predictions": enrich_prop_rows(
                _query_recent(
                    db,
                    NHLGoaliePredictions,
                    "game_date",
                    target_date,
                    limit,
                    tz=tz,
                    dedupe_keys=("goalie_id", "game_date"),
                ),
                sport="nhl",
                stat="saves",
                db=db,
            ),
            "player_shots": enrich_prop_rows(
                _query_recent(
                    db,
                    NHLPlayerShotsPredictions,
                    "game_date",
                    target_date,
                    limit,
                    tz=tz,
                    dedupe_keys=("player_id", "game_date"),
                ),
                sport="nhl",
                stat="shots",
                db=db,
            ),
            "team_totals": _query_recent(
                db,
                NHLTeamTotalsPredictions,
                "game_date",
                target_date,
                limit,
                tz=tz,
                dedupe_keys=("home_team_id", "away_team_id", "game_date"),
            ),
        },
        "nhl",
        db,
        target_date,
    )


@router.get("/nhl/accuracy")
def nhl_accuracy(
    target_date: date_type = Query(..., alias="date"),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Per-day NHL projection accuracy → unified bucket shape."""
    from app.services.nhl_accuracy_service import daily_accuracy

    return daily_accuracy(db, target_date=target_date)


@router.get("/wnba")
def wnba_predictions(
    target_date: date_type | None = Query(default=None, alias="date"),
    tz: str = Query(default="UTC"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    prop_limit: int = Query(
        default=WNBA_PROP_DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description="Max player prop rows per stat; ranked by season minutes per game.",
    ),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """WNBA: totals, spread/win-prob, and player props.

    Spread and totals rows include final scores and ml/spread/total grading when
    pred_wnba_*_actuals exist for the requested date (same pattern as MLB games).

    Player props (points/assists/rebounds/3PM/PRA) return up to ``prop_limit`` rows
    for the requested date, ordered by season-to-date minutes per game.
    """
    from app.services.wnba_game_picks import enrich_wnba_game_predictions
    from app.services.game_projection_schedule import attach_game_times_from_lines

    tz = _safe_tz(tz)
    spreads = _query_recent(
        db, WNBASpreadProjections, "game_date", target_date, limit, tz=tz
    )
    totals = _query_recent(
        db, WNBATotalsProjections, "game_date", target_date, limit, tz=tz
    )
    spreads = attach_game_times_from_lines(db, spreads, WNBAGameLines)
    totals = attach_game_times_from_lines(db, totals, WNBAGameLines)
    spreads, totals = enrich_wnba_game_predictions(
        db, spreads, totals, target_date=target_date
    )
    return _merge_past_results(
        {
            "totals": totals,
            "spreads": spreads,
            "points": enrich_prop_rows(
                _query_wnba_props_by_season_minutes(
                    db, WNBAPointsProjections, target_date, prop_limit, tz=tz
                ),
                sport="wnba",
                stat="points",
                db=db,
            ),
            "assists": enrich_prop_rows(
                _query_wnba_props_by_season_minutes(
                    db, WNBAAssistsProjections, target_date, prop_limit, tz=tz
                ),
                sport="wnba",
                stat="assists",
                db=db,
            ),
            "rebounds": enrich_prop_rows(
                _query_wnba_props_by_season_minutes(
                    db, WNBAReboundsProjections, target_date, prop_limit, tz=tz
                ),
                sport="wnba",
                stat="rebounds",
                db=db,
            ),
            "three_point": enrich_prop_rows(
                _query_wnba_props_by_season_minutes(
                    db, WNBAThreePtMadeProjections, target_date, prop_limit, tz=tz
                ),
                sport="wnba",
                stat="three_pt_made",
                db=db,
            ),
            "pra": enrich_prop_rows(
                _query_wnba_props_by_season_minutes(
                    db, WNBAPRAProjections, target_date, prop_limit, tz=tz
                ),
                sport="wnba",
                stat="pra",
                db=db,
            ),
        },
        "wnba",
        db,
        target_date,
    )


@router.get("/wnba/accuracy")
def wnba_accuracy(
    target_date: date_type = Query(..., alias="date"),
    _user: dict = Depends(require_paid_tier),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Per-day WNBA projection accuracy → unified bucket shape."""
    from app.services.wnba_accuracy_service import daily_accuracy

    return daily_accuracy(db, target_date=target_date)
