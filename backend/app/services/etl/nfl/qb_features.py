"""QB passing-yards feature engineering (tier baseline + matchup/form context).

Feature matrix is intentionally small and leak-safe: rolling averages use only
prior weeks. Missing context falls back to league priors so shadow/promote
paths never hard-fail.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

# League priors (REG, approximate)
_LEAGUE_AVG_PASS_YARDS = 220.0
_LEAGUE_AVG_OPP_PASS_ALLOWED = 220.0
_LEAGUE_AVG_TEAM_TOTAL = 22.5
_DEFAULT_REST_DAYS = 7.0
_DEFAULT_TEMP_F = 65.0
_DEFAULT_WIND_MPH = 5.0

FEATURE_NAMES: tuple[str, ...] = (
    "tier_yards",
    "is_backup",
    "week",
    "confidence",
    "season",
    "rolling_yards_l3",
    "rolling_yards_l5",
    "season_avg_yards",
    "opp_pass_yds_allowed",
    "is_home",
    "rest_days",
    "implied_team_total",
    "wind_speed",
    "temperature",
    "dome",
)


def feature_names() -> list[str]:
    return list(FEATURE_NAMES)


def _float_or(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def rolling_mean(values: Sequence[float], *, window: int) -> float | None:
    """Mean of the last ``window`` values; None if empty."""
    if not values or window <= 0:
        return None
    tail = list(values)[-window:]
    if not tail:
        return None
    return float(sum(tail) / len(tail))


def prior_yards_for_player(
    history: Iterable[Mapping[str, Any]],
    *,
    player_key: str,
    season: int,
    week: int,
    player_id_key: str = "qb_player_id",
    name_key: str = "qb_player_name",
    yards_key: str = "actual_passing_yards",
    season_key: str = "season",
    week_key: str = "week",
) -> list[float]:
    """
    Leak-safe prior actual yards for a QB before ``(season, week)``.

    ``player_key`` may be an id or display name; matches either column.
    """
    key_norm = str(player_key).strip().lower()
    prior: list[tuple[int, int, float]] = []
    for row in history:
        pid = str(row.get(player_id_key) or "").strip().lower()
        pname = str(row.get(name_key) or "").strip().lower()
        if key_norm not in {pid, pname}:
            continue
        row_season = int(row.get(season_key) or 0)
        row_week = int(row.get(week_key) or 0)
        if row_season > season or (row_season == season and row_week >= week):
            continue
        yards = row.get(yards_key)
        if yards is None:
            continue
        try:
            prior.append((row_season, row_week, float(yards)))
        except (TypeError, ValueError):
            continue
    prior.sort(key=lambda t: (t[0], t[1]))
    return [y for _, _, y in prior]


def form_features_from_prior_yards(
    prior_yards: Sequence[float],
    *,
    tier_yards: float,
) -> dict[str, float]:
    """Rolling / season form with tier fallback when history is thin."""
    tier = _float_or(tier_yards, _LEAGUE_AVG_PASS_YARDS)
    l3 = rolling_mean(prior_yards, window=3)
    l5 = rolling_mean(prior_yards, window=5)
    season_avg = (
        rolling_mean(prior_yards, window=len(prior_yards)) if prior_yards else None
    )
    return {
        "rolling_yards_l3": float(l3 if l3 is not None else tier),
        "rolling_yards_l5": float(l5 if l5 is not None else tier),
        "season_avg_yards": float(season_avg if season_avg is not None else tier),
    }


def schedule_is_home(
    team_abbr: str, home_team: str | None, away_team: str | None
) -> float:
    if not team_abbr or not home_team:
        return 0.5
    t = team_abbr.strip().upper()
    if t == str(home_team).strip().upper():
        return 1.0
    if away_team and t == str(away_team).strip().upper():
        return 0.0
    return 0.5


def rest_days_from_bye(days_since_last_game: float | None) -> float:
    if days_since_last_game is None:
        return _DEFAULT_REST_DAYS
    return _clamp(float(days_since_last_game), 3.0, 21.0)


def build_qb_features(
    *,
    tier_yards: float,
    season: int,
    week: int,
    is_backup: bool = False,
    confidence: float = 0.65,
    context: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """
    Assemble the GBM feature vector.

    ``context`` optional keys:
      rolling_yards_l3, rolling_yards_l5, season_avg_yards,
      opp_pass_yds_allowed, is_home, rest_days, implied_team_total,
      wind_speed, temperature, dome
    """
    ctx = dict(context or {})
    tier = _float_or(tier_yards, _LEAGUE_AVG_PASS_YARDS)
    form = form_features_from_prior_yards(
        [],
        tier_yards=tier,
    )
    # Prefer explicit form from context over empty prior
    for key in ("rolling_yards_l3", "rolling_yards_l5", "season_avg_yards"):
        if ctx.get(key) is not None:
            form[key] = _float_or(ctx.get(key), form[key])

    is_home = ctx.get("is_home")
    if is_home is None and ctx.get("home_team") is not None:
        is_home = schedule_is_home(
            str(ctx.get("team_abbr") or ""),
            ctx.get("home_team"),
            ctx.get("away_team"),
        )

    rest_raw = ctx.get("rest_days")
    if rest_raw is None:
        rest_days = _DEFAULT_REST_DAYS
    else:
        rest_days = rest_days_from_bye(_float_or(rest_raw, _DEFAULT_REST_DAYS))

    return {
        "tier_yards": tier,
        "is_backup": 1.0 if is_backup else 0.0,
        "week": float(week),
        "confidence": _clamp(_float_or(confidence, 0.65), 0.3, 0.95),
        "season": float(season),
        "rolling_yards_l3": form["rolling_yards_l3"],
        "rolling_yards_l5": form["rolling_yards_l5"],
        "season_avg_yards": form["season_avg_yards"],
        "opp_pass_yds_allowed": _float_or(
            ctx.get("opp_pass_yds_allowed"), _LEAGUE_AVG_OPP_PASS_ALLOWED
        ),
        "is_home": _float_or(is_home, 0.5),
        "rest_days": rest_days,
        "implied_team_total": _float_or(
            ctx.get("implied_team_total"), _LEAGUE_AVG_TEAM_TOTAL
        ),
        "wind_speed": _float_or(ctx.get("wind_speed"), _DEFAULT_WIND_MPH),
        "temperature": _float_or(ctx.get("temperature"), _DEFAULT_TEMP_F),
        "dome": 1.0 if bool(ctx.get("dome")) else 0.0,
    }


def enrich_context_from_actual_row(
    row: Any,
    *,
    history: Sequence[Mapping[str, Any]],
    player_key: str,
    tier_yards: float,
) -> dict[str, Any]:
    """Build context for training from a QBActuals-like row + prior history."""
    season = int(getattr(row, "season", 0) or 0)
    week = int(getattr(row, "week", 0) or 0)
    prior = prior_yards_for_player(
        history,
        player_key=player_key,
        season=season,
        week=week,
    )
    form = form_features_from_prior_yards(prior, tier_yards=tier_yards)
    ctx: dict[str, Any] = {**form}
    temp = getattr(row, "game_temperature", None)
    wind = getattr(row, "game_wind_speed", None)
    if temp is not None:
        ctx["temperature"] = float(temp)
    if wind is not None:
        ctx["wind_speed"] = float(wind)
    weather = str(getattr(row, "game_weather", "") or "").lower()
    if "dome" in weather or "indoor" in weather or "retractable" in weather:
        ctx["dome"] = True
    return ctx


def estimate_opp_pass_allowed_from_weekly(
    weekly_rows: Sequence[Mapping[str, Any]],
    *,
    opponent_abbr: str,
    season: int,
    week: int,
    team_key: str = "recent_team",
    yards_key: str = "passing_yards",
) -> float | None:
    """
    Opponent pass yards allowed ≈ mean of opposing QBs' pass yards vs that team
    in prior weeks of the same season (proxy when defense tables are absent).
    """
    opp = opponent_abbr.strip().upper()
    if not opp:
        return None
    allowed: list[float] = []
    for row in weekly_rows:
        # Prefer explicit defense allowed if present
        if row.get("team") and str(row.get("team")).upper() == opp:
            if row.get("passing_yards_allowed") is not None:
                try:
                    row_week = int(row.get("week") or 0)
                    row_season = int(row.get("season") or season)
                    if row_season == season and 0 < row_week < week:
                        allowed.append(float(row["passing_yards_allowed"]))
                except (TypeError, ValueError):
                    pass
        # QB weekly: yards thrown *against* opponent when opponent == defense
        # nflverse weekly has `opponent_team`
        row_opp = str(row.get("opponent_team") or row.get("opponent") or "").upper()
        row_team = str(row.get(team_key) or row.get("team") or "").upper()
        pos = str(row.get("position") or "").upper()
        if pos and pos != "QB":
            continue
        if row_opp != opp:
            continue
        if row_team == opp:
            continue
        try:
            row_week = int(row.get("week") or 0)
            row_season = int(row.get("season") or season)
        except (TypeError, ValueError):
            continue
        if row_season != season or row_week >= week or row_week < 1:
            continue
        yards = row.get(yards_key)
        if yards is None:
            continue
        try:
            allowed.append(float(yards))
        except (TypeError, ValueError):
            continue
    if not allowed:
        return None
    return float(sum(allowed) / len(allowed))
