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
_LEAGUE_AVG_DEF_EPA = 0.0  # pass EPA allowed (higher = worse defense)
_LEAGUE_AVG_PRESSURE = 0.25
_LEAGUE_AVG_TEAM_TOTAL = 22.5
_LEAGUE_AVG_TOTAL_LINE = 45.0
_DEFAULT_REST_DAYS = 7.0
_DEFAULT_TEMP_F = 65.0
_DEFAULT_WIND_MPH = 5.0
_DEFAULT_COVER = 3.0  # cover_3
_DEFAULT_MAN_ZONE = 0.0  # zone
_DEFAULT_SCHEME_PRESSURE = 0.5  # medium

_COVER_BASE_TO_FLOAT: dict[str, float] = {
    "cover_1": 1.0,
    "cover_2": 2.0,
    "cover_3": 3.0,
    "cover_4": 4.0,
    "cover_6": 6.0,
}
_MAN_ZONE_TO_FLOAT: dict[str, float] = {"man": 1.0, "zone": 0.0}
_PRESSURE_TO_FLOAT: dict[str, float] = {
    "low": 0.25,
    "medium": 0.5,
    "high": 0.75,
}

FEATURE_NAMES: tuple[str, ...] = (
    "tier_yards",
    "is_backup",
    "week",
    "confidence",
    "season",
    "rolling_yards_l3",
    "rolling_yards_l5",
    "season_avg_yards",
    "rolling_attempts_l3",
    "rolling_ypa_l3",
    "rolling_comp_pct_l3",
    "opp_pass_yds_allowed",
    "opp_def_epa",
    "opp_pressure_rate",
    "injury_risk",
    "is_home",
    "rest_days",
    "implied_team_total",
    "wind_speed",
    "temperature",
    "dome",
    # Market (nflverse schedules / game lines)
    "total_line",
    "spread_line",
    "pass_yds_line",
    "line_minus_tier",
    # Curated opponent defensive scheme tags
    "opp_cover_base",
    "opp_man_zone",
    "opp_scheme_pressure",
)

_LEAGUE_AVG_ATTEMPTS = 34.0
_LEAGUE_AVG_YPA = 7.0
_LEAGUE_AVG_COMP_PCT = 0.65


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


def prior_game_stats_for_player(
    history: Iterable[Mapping[str, Any]],
    *,
    player_key: str,
    season: int,
    week: int,
    player_id_key: str = "qb_player_id",
    name_key: str = "qb_player_name",
    season_key: str = "season",
    week_key: str = "week",
) -> list[dict[str, float]]:
    """Leak-safe prior game stats (yards/attempts/completions) before ``(season, week)``."""
    key_norm = str(player_key).strip().lower()
    prior: list[tuple[int, int, dict[str, float]]] = []
    for row in history:
        pid = str(row.get(player_id_key) or "").strip().lower()
        pname = str(row.get(name_key) or "").strip().lower()
        if key_norm not in {pid, pname}:
            continue
        row_season = int(row.get(season_key) or 0)
        row_week = int(row.get(week_key) or 0)
        if row_season > season or (row_season == season and row_week >= week):
            continue
        yards = row.get("actual_passing_yards")
        if yards is None:
            yards = row.get("passing_yards")
        if yards is None:
            continue
        try:
            y = float(yards)
        except (TypeError, ValueError):
            continue
        attempts = row.get("actual_attempts")
        if attempts is None:
            attempts = row.get("attempts") or row.get("passing_attempts")
        completions = row.get("actual_completions")
        if completions is None:
            completions = row.get("completions") or row.get("passing_completions")
        try:
            att = float(attempts) if attempts is not None else None
        except (TypeError, ValueError):
            att = None
        try:
            comp = float(completions) if completions is not None else None
        except (TypeError, ValueError):
            comp = None
        prior.append(
            (
                row_season,
                row_week,
                {
                    "yards": y,
                    "attempts": float(att) if att is not None and att > 0 else 0.0,
                    "completions": float(comp) if comp is not None else 0.0,
                },
            )
        )
    prior.sort(key=lambda t: (t[0], t[1]))
    return [stats for _, _, stats in prior]


def form_volume_features_from_prior(
    prior_stats: Sequence[Mapping[str, float]],
) -> dict[str, float]:
    """Rolling attempts / YPA / completion% from prior games (league fallback)."""
    attempts = [float(r.get("attempts") or 0.0) for r in prior_stats]
    yards = [float(r.get("yards") or 0.0) for r in prior_stats]
    completions = [float(r.get("completions") or 0.0) for r in prior_stats]
    att_l3 = rolling_mean([a for a in attempts if a > 0], window=3)
    # YPA / comp% over last up to 3 games with attempts
    ypa_vals: list[float] = []
    comp_vals: list[float] = []
    for a, y, c in zip(attempts, yards, completions):
        if a and a > 0:
            ypa_vals.append(y / a)
            comp_vals.append(c / a)
    ypa_l3 = rolling_mean(ypa_vals, window=3)
    comp_l3 = rolling_mean(comp_vals, window=3)
    return {
        "rolling_attempts_l3": float(
            att_l3 if att_l3 is not None else _LEAGUE_AVG_ATTEMPTS
        ),
        "rolling_ypa_l3": float(ypa_l3 if ypa_l3 is not None else _LEAGUE_AVG_YPA),
        "rolling_comp_pct_l3": float(
            comp_l3 if comp_l3 is not None else _LEAGUE_AVG_COMP_PCT
        ),
    }


def blend_tier_with_form(
    static_tier: float,
    prior_yards: Sequence[float],
    *,
    min_games: int = 3,
    form_weight: float = 0.40,
) -> float:
    """
    Dynamic tier: blend static name table with leak-safe rolling form.

    When fewer than ``min_games`` priors exist, returns static tier unchanged.
    """
    tier = _float_or(static_tier, _LEAGUE_AVG_PASS_YARDS)
    if len(prior_yards) < min_games:
        return round(tier, 1)
    form = rolling_mean(prior_yards, window=min(5, len(prior_yards)))
    if form is None:
        return round(tier, 1)
    w = _clamp(float(form_weight), 0.0, 0.75)
    blended = (1.0 - w) * tier + w * float(form)
    return round(_clamp(blended, 150.0, 350.0), 1)


def resolve_yards_baseline(
    *,
    tier_yards: float,
    pass_yds_line: float | None,
    line_is_real: bool | None = None,
) -> float:
    """
    Baseline for residual learning/prediction.

    When a real market line is present (and differs from tier), use
    ``0.5 * (tier + line)`` so the GBM learns residual vs a market-aware
    anchor instead of chasing the raw line feature.
    """
    tier = _float_or(tier_yards, _LEAGUE_AVG_PASS_YARDS)
    if pass_yds_line is None:
        return round(tier, 1)
    line = _float_or(pass_yds_line, tier)
    real = line_is_real
    if real is None:
        real = abs(line - tier) > 0.5
    if not real:
        return round(tier, 1)
    return round(0.5 * (tier + line), 1)


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


def encode_scheme_tags(entry: Mapping[str, Any] | None) -> dict[str, float]:
    """Encode YAML defensive scheme tags → numeric GBM features."""
    if not entry:
        return {
            "opp_cover_base": _DEFAULT_COVER,
            "opp_man_zone": _DEFAULT_MAN_ZONE,
            "opp_scheme_pressure": _DEFAULT_SCHEME_PRESSURE,
        }
    cover_raw = str(entry.get("cover_base") or "cover_3").lower().replace("-", "_")
    cover = _COVER_BASE_TO_FLOAT.get(cover_raw, _DEFAULT_COVER)
    mz_raw = str(entry.get("man_zone_lean") or "zone").lower()
    man_zone = _MAN_ZONE_TO_FLOAT.get(mz_raw, _DEFAULT_MAN_ZONE)
    press_raw = str(entry.get("pressure_lean") or "medium").lower()
    pressure = _PRESSURE_TO_FLOAT.get(press_raw, _DEFAULT_SCHEME_PRESSURE)
    return {
        "opp_cover_base": float(cover),
        "opp_man_zone": float(man_zone),
        "opp_scheme_pressure": float(pressure),
    }


def scheme_features_for_opponent(
    opponent_abbr: str,
    *,
    schemes: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, float]:
    """Look up curated scheme tags for the opposing defense."""
    if schemes is None:
        try:
            from app.services.etl.nfl.scheme_loader import load_schemes_from_yaml

            schemes = load_schemes_from_yaml()
        except Exception:
            schemes = {}
    opp = (opponent_abbr or "").strip().upper()
    entry = schemes.get(opp) if schemes else None
    if entry is None and schemes and opp:
        # Full-name keys are also present in load_schemes_from_yaml
        entry = schemes.get(opp)
    return encode_scheme_tags(entry)


def implied_team_total_from_market(
    *,
    total_line: float | None,
    spread_line: float | None,
    is_home: float | None = None,
) -> float | None:
    """
    Classic implied team total from game total + spread.

    ``spread_line`` is from the home team's perspective (nflverse): negative =
    home favored. For the team of interest, pass the spread *for that team*
    (negative = favored) via ``spread_line`` and set ``is_home`` unused —
    callers should already flip sign for away teams.
    """
    if total_line is None:
        return None
    total = _float_or(total_line, _LEAGUE_AVG_TOTAL_LINE)
    spread = _float_or(spread_line, 0.0)
    # spread negative → favored → higher implied
    implied = total / 2.0 - spread / 2.0
    _ = is_home
    return float(implied)


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
      rolling_attempts_l3, rolling_ypa_l3, rolling_comp_pct_l3,
      opp_pass_yds_allowed, opp_def_epa, opp_pressure_rate, injury_risk,
      is_home, rest_days, implied_team_total, wind_speed, temperature, dome,
      total_line, spread_line, pass_yds_line, line_minus_tier, line_is_real,
      opp_cover_base, opp_man_zone, opp_scheme_pressure,
      opponent_abbr / scheme tags
    """
    ctx = dict(context or {})
    # Prefer dynamic (form-blended) tier when callers supply it
    if ctx.get("dynamic_tier_yards") is not None:
        tier = _float_or(ctx.get("dynamic_tier_yards"), _LEAGUE_AVG_PASS_YARDS)
    else:
        tier = _float_or(tier_yards, _LEAGUE_AVG_PASS_YARDS)
    form = form_features_from_prior_yards(
        [],
        tier_yards=tier,
    )
    # Prefer explicit form from context over empty prior
    for key in ("rolling_yards_l3", "rolling_yards_l5", "season_avg_yards"):
        if ctx.get(key) is not None:
            form[key] = _float_or(ctx.get(key), form[key])

    volume = {
        "rolling_attempts_l3": _LEAGUE_AVG_ATTEMPTS,
        "rolling_ypa_l3": _LEAGUE_AVG_YPA,
        "rolling_comp_pct_l3": _LEAGUE_AVG_COMP_PCT,
    }
    for key in ("rolling_attempts_l3", "rolling_ypa_l3", "rolling_comp_pct_l3"):
        if ctx.get(key) is not None:
            volume[key] = _float_or(ctx.get(key), volume[key])

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

    injury_risk = ctx.get("injury_risk")
    if injury_risk is None:
        injury_risk = injury_risk_from_status(ctx.get("injury_status"))

    # Scheme: prefer explicit numerics, else encode tags / opponent lookup
    if any(
        ctx.get(k) is not None
        for k in ("opp_cover_base", "opp_man_zone", "opp_scheme_pressure")
    ):
        scheme = {
            "opp_cover_base": _float_or(ctx.get("opp_cover_base"), _DEFAULT_COVER),
            "opp_man_zone": _float_or(ctx.get("opp_man_zone"), _DEFAULT_MAN_ZONE),
            "opp_scheme_pressure": _float_or(
                ctx.get("opp_scheme_pressure"), _DEFAULT_SCHEME_PRESSURE
            ),
        }
    elif ctx.get("cover_base") is not None or ctx.get("scheme") is not None:
        tags = ctx.get("scheme") if isinstance(ctx.get("scheme"), Mapping) else ctx
        scheme = encode_scheme_tags(tags)  # type: ignore[arg-type]
    elif ctx.get("opponent_abbr"):
        scheme = scheme_features_for_opponent(str(ctx["opponent_abbr"]))
    else:
        scheme = encode_scheme_tags(None)

    total_line = ctx.get("total_line")
    spread_line = ctx.get("spread_line")
    implied = ctx.get("implied_team_total")
    if implied is None and total_line is not None:
        implied = implied_team_total_from_market(
            total_line=_float_or(total_line, _LEAGUE_AVG_TOTAL_LINE),
            spread_line=_float_or(spread_line, 0.0) if spread_line is not None else 0.0,
        )

    # pass_yds_line: market prop when present; else anchor near tier
    pass_line_raw = ctx.get("pass_yds_line")
    line_is_real = ctx.get("line_is_real")
    if pass_line_raw is None:
        pass_line = tier
        if line_is_real is None:
            line_is_real = False
    else:
        pass_line = _float_or(pass_line_raw, tier)
        if line_is_real is None:
            line_is_real = abs(pass_line - tier) > 0.5
    line_minus_tier = ctx.get("line_minus_tier")
    if line_minus_tier is None:
        line_minus_tier = float(pass_line) - float(tier) if line_is_real else 0.0

    return {
        "tier_yards": tier,
        "is_backup": 1.0 if is_backup else 0.0,
        "week": float(week),
        "confidence": _clamp(_float_or(confidence, 0.65), 0.3, 0.95),
        "season": float(season),
        "rolling_yards_l3": form["rolling_yards_l3"],
        "rolling_yards_l5": form["rolling_yards_l5"],
        "season_avg_yards": form["season_avg_yards"],
        "rolling_attempts_l3": volume["rolling_attempts_l3"],
        "rolling_ypa_l3": volume["rolling_ypa_l3"],
        "rolling_comp_pct_l3": volume["rolling_comp_pct_l3"],
        "opp_pass_yds_allowed": _float_or(
            ctx.get("opp_pass_yds_allowed"), _LEAGUE_AVG_OPP_PASS_ALLOWED
        ),
        "opp_def_epa": _float_or(ctx.get("opp_def_epa"), _LEAGUE_AVG_DEF_EPA),
        "opp_pressure_rate": _clamp(
            _float_or(ctx.get("opp_pressure_rate"), _LEAGUE_AVG_PRESSURE), 0.05, 0.55
        ),
        "injury_risk": _clamp(_float_or(injury_risk, 0.0), 0.0, 1.0),
        "is_home": _float_or(is_home, 0.5),
        "rest_days": rest_days,
        "implied_team_total": _float_or(implied, _LEAGUE_AVG_TEAM_TOTAL),
        "wind_speed": _float_or(ctx.get("wind_speed"), _DEFAULT_WIND_MPH),
        "temperature": _float_or(ctx.get("temperature"), _DEFAULT_TEMP_F),
        "dome": 1.0 if bool(ctx.get("dome")) else 0.0,
        "total_line": _float_or(total_line, _LEAGUE_AVG_TOTAL_LINE),
        "spread_line": _float_or(spread_line, 0.0),
        "pass_yds_line": _float_or(pass_line, tier),
        "line_minus_tier": float(line_minus_tier),
        "opp_cover_base": scheme["opp_cover_base"],
        "opp_man_zone": scheme["opp_man_zone"],
        "opp_scheme_pressure": scheme["opp_scheme_pressure"],
    }


def injury_risk_from_status(status: Any) -> float:
    """Map injury report status → [0, 1] risk for the projected starter."""
    s = str(status or "healthy").strip().lower()
    if s in {"out", "ir", "doubtful"}:
        return 1.0
    if s in {"questionable", "q"}:
        return 0.55
    if s in {"probable"}:
        return 0.2
    return 0.0


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
    prior_stats = prior_game_stats_for_player(
        history,
        player_key=player_key,
        season=season,
        week=week,
    )
    prior_yards = [float(s["yards"]) for s in prior_stats]
    form = form_features_from_prior_yards(prior_yards, tier_yards=tier_yards)
    volume = form_volume_features_from_prior(prior_stats)
    dynamic_tier = blend_tier_with_form(tier_yards, prior_yards)
    ctx: dict[str, Any] = {
        **form,
        **volume,
        "dynamic_tier_yards": dynamic_tier,
    }
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


def estimate_opp_defense_from_weekly(
    weekly_rows: Sequence[Mapping[str, Any]],
    *,
    opponent_abbr: str,
    season: int,
    week: int,
) -> dict[str, float]:
    """
    Defense quality vs the pass from prior QB weekly rows facing ``opponent``.

    Uses ``passing_epa`` when present (EPA allowed) and sack rate as a pressure
    proxy. Falls back to empty dict when sample is thin.
    """
    opp = opponent_abbr.strip().upper()
    if not opp:
        return {}
    epa_vals: list[float] = []
    sack_rates: list[float] = []
    for row in weekly_rows:
        pos = str(row.get("position") or "").upper()
        if pos and pos != "QB":
            continue
        row_opp = str(row.get("opponent_team") or row.get("opponent") or "").upper()
        if row_opp != opp:
            continue
        try:
            row_week = int(row.get("week") or 0)
            row_season = int(row.get("season") or season)
        except (TypeError, ValueError):
            continue
        if row_season != season or row_week >= week or row_week < 1:
            continue
        if row.get("passing_epa") is not None:
            try:
                epa_vals.append(float(row["passing_epa"]))
            except (TypeError, ValueError):
                pass
        attempts = row.get("attempts") or row.get("passing_attempts")
        sacks = row.get("sacks")
        if attempts is not None and sacks is not None:
            try:
                att = float(attempts)
                if att > 0:
                    sack_rates.append(float(sacks) / att)
            except (TypeError, ValueError):
                pass
    out: dict[str, float] = {}
    if len(epa_vals) >= 2:
        out["opp_def_epa"] = float(sum(epa_vals) / len(epa_vals))
    if len(sack_rates) >= 2:
        out["opp_pressure_rate"] = float(sum(sack_rates) / len(sack_rates))
    return out


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
