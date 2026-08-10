"""Pure feature builders for NFL anytime-TD projections."""

from __future__ import annotations

from typing import Any

from app.services.etl.nfl.team_names import normalize_team_name

# League-average priors (REG season, per-game unless noted)
_TEAM_RZ_TRIPS_PRIOR = 3.2
_LEAGUE_AVG_TEAM_TOTAL = 22.5
_CONVERSION_RATE_PRIOR: dict[str, float] = {
    "QB": 0.15,
    "RB": 0.35,
    "WR": 0.22,
    "TE": 0.25,
}
_PLAYER_RZ_SHARE_PRIOR: dict[str, float] = {
    "QB": 0.08,
    "RB": 0.25,
    "WR": 0.18,
    "TE": 0.15,
}
_TDS_ALLOWED_PRIOR: dict[str, float] = {
    "QB": 0.25,
    "RB": 0.55,
    "WR": 0.45,
    "TE": 0.30,
}
_RZ_TD_RATE_ALLOWED_PRIOR = 0.52
_DEF_EPA_PRIOR = 0.0
_EARLY_DOWN_PASS_PRIOR = 0.48
_TEAM_RZ_PASS_RATE_PRIOR = 0.52
_SNAP_PCT_PRIOR = 0.55

_COVER_ADJ: dict[str, dict[str, float]] = {
    "cover_1": {"QB": 0.98, "RB": 0.95, "WR": 1.08, "TE": 1.06},
    "cover_2": {"QB": 1.0, "RB": 1.05, "WR": 0.98, "TE": 0.97},
    "cover_3": {"QB": 1.0, "RB": 1.0, "WR": 1.0, "TE": 1.0},
    "cover_4": {"QB": 0.97, "RB": 1.06, "WR": 0.96, "TE": 0.95},
    "cover_6": {"QB": 0.94, "RB": 0.92, "WR": 1.07, "TE": 1.05},
}
_MAN_ZONE_ADJ: dict[str, dict[str, float]] = {
    "man": {"QB": 1.0, "RB": 0.96, "WR": 1.06, "TE": 1.04},
    "zone": {"QB": 1.0, "RB": 1.03, "WR": 0.98, "TE": 0.98},
}
_PRESSURE_ADJ: dict[str, dict[str, float]] = {
    "low": {"QB": 1.05, "RB": 0.98, "WR": 1.0, "TE": 1.0},
    "medium": {"QB": 1.0, "RB": 1.0, "WR": 1.0, "TE": 1.0},
    "high": {"QB": 0.92, "RB": 1.04, "WR": 0.98, "TE": 0.97},
}


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _pos(position: str) -> str:
    p = position.strip().upper()
    return p if p in _CONVERSION_RATE_PRIOR else "WR"


def scheme_defense_adjustment(
    cover_base: str | None,
    man_zone_lean: str | None,
    pressure_lean: str | None,
    position: str,
) -> float:
    """Small bounded scheme factor by position (0.9–1.15)."""
    pos = _pos(position)
    cover = (cover_base or "cover_3").lower().replace("-", "_")
    mz = (man_zone_lean or "zone").lower()
    pressure = (pressure_lean or "medium").lower()

    adj = 1.0
    adj *= _COVER_ADJ.get(cover, _COVER_ADJ["cover_3"]).get(pos, 1.0)
    adj *= _MAN_ZONE_ADJ.get(mz, _MAN_ZONE_ADJ["zone"]).get(pos, 1.0)
    adj *= _PRESSURE_ADJ.get(pressure, _PRESSURE_ADJ["medium"]).get(pos, 1.0)
    return _clamp(adj, 0.9, 1.15)


def defense_multiplier(
    scheme: dict[str, Any] | None,
    tds_allowed_vs_pos: float,
    league_avg: float,
) -> float:
    """Aggregate TDs allowed vs position scaled by curated scheme tags."""
    if league_avg <= 0:
        league_avg = 0.5
    aggregate = _clamp(tds_allowed_vs_pos / league_avg, 0.85, 1.15)
    if not scheme:
        return aggregate
    scheme_adj = scheme_defense_adjustment(
        scheme.get("cover_base"),
        scheme.get("man_zone_lean"),
        scheme.get("pressure_lean"),
        scheme.get("position", "WR"),
    )
    return _clamp(aggregate * scheme_adj, 0.85, 1.25)


def weather_multiplier(
    *,
    outdoor: bool,
    wind_mph: float | None,
    precip: bool,
) -> float:
    """Outdoor wind/precip nudge for GL / short-yardage scoring."""
    if not outdoor:
        return 1.0
    mult = 1.0
    if wind_mph is not None and wind_mph > 15:
        mult *= _clamp(1.0 - (wind_mph - 15) * 0.004, 0.88, 1.0)
    if precip:
        mult *= 0.95
    return _clamp(mult, 0.85, 1.0)


def script_multiplier(*, implied_team_total: float | None) -> float:
    """Scoring script from implied team total vs league average."""
    total = (
        implied_team_total if implied_team_total is not None else _LEAGUE_AVG_TEAM_TOTAL
    )
    return _clamp(total / _LEAGUE_AVG_TEAM_TOTAL, 0.85, 1.15)


def build_player_feature_row(
    *,
    player_id: str,
    player_name: str,
    position: str,
    team_name: str,
    opponent_team_name: str,
    season: int,
    week: int,
    player_stats: dict[str, Any] | None = None,
    team_stats: dict[str, Any] | None = None,
    opponent_defense: dict[str, Any] | None = None,
    scheme: dict[str, Any] | None = None,
    weather: dict[str, Any] | None = None,
    game_env: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a feature dict for the anytime-TD projector (injected data only)."""
    pos = _pos(position)
    player_stats = player_stats or {}
    team_stats = team_stats or {}
    opponent_defense = opponent_defense or {}
    weather = weather or {}
    game_env = game_env or {}

    team = normalize_team_name(team_name)
    opponent = normalize_team_name(opponent_team_name)

    team_rz_trips = float(team_stats.get("team_rz_trips", _TEAM_RZ_TRIPS_PRIOR))
    player_rz_share = float(
        player_stats.get("player_rz_share", _PLAYER_RZ_SHARE_PRIOR.get(pos, 0.18))
    )
    conversion_rate = float(
        player_stats.get("conversion_rate", _CONVERSION_RATE_PRIOR.get(pos, 0.22))
    )

    tds_allowed = float(
        opponent_defense.get("tds_allowed_vs_pos", _TDS_ALLOWED_PRIOR.get(pos, 0.45))
    )
    league_avg_tds = _TDS_ALLOWED_PRIOR.get(pos, 0.45)
    scheme_for_def = dict(scheme) if scheme else {}
    scheme_for_def["position"] = pos
    defense_mult = defense_multiplier(scheme_for_def, tds_allowed, league_avg_tds)

    outdoor = bool(weather.get("outdoor", False))
    wind_mph = weather.get("wind_mph")
    wind_val = float(wind_mph) if wind_mph is not None else None
    precip = bool(weather.get("precip", False))
    weather_mult = weather_multiplier(outdoor=outdoor, wind_mph=wind_val, precip=precip)

    implied_team_total = game_env.get("implied_team_total")
    implied_team_total_f = (
        float(implied_team_total) if implied_team_total is not None else None
    )
    script_mult = script_multiplier(implied_team_total=implied_team_total_f)

    cover_base = (scheme or {}).get("cover_base")
    man_zone_lean = (scheme or {}).get("man_zone_lean")
    pressure_lean = (scheme or {}).get("pressure_lean")
    scheme_adj = scheme_defense_adjustment(
        cover_base, man_zone_lean, pressure_lean, pos
    )

    spread = game_env.get("spread")
    implied_total = game_env.get("implied_total")
    implied_margin = float(spread) if spread is not None else None

    return {
        # metadata
        "player_id": player_id,
        "player_name": player_name,
        "position": pos,
        "team_name": team,
        "opponent_team_name": opponent,
        "season": season,
        "week": week,
        # projector inputs
        "team_rz_trips": team_rz_trips,
        "player_rz_share": player_rz_share,
        "conversion_rate": conversion_rate,
        "defense_mult": defense_mult,
        "weather_mult": weather_mult,
        "script_mult": script_mult,
        # usage
        "snap_pct": player_stats.get("snap_pct", _SNAP_PCT_PRIOR),
        "targets_l3": player_stats.get("targets_l3"),
        "carries_l3": player_stats.get("carries_l3"),
        "routes_l3": player_stats.get("routes_l3"),
        "td_l3": player_stats.get("td_l3"),
        "td_l5": player_stats.get("td_l5"),
        "td_season": player_stats.get("td_season"),
        # red zone / goal line
        "gl_carries": player_stats.get("gl_carries"),
        "rz_targets": player_stats.get("rz_targets"),
        "team_rz_pass_rate": float(
            team_stats.get("team_rz_pass_rate", _TEAM_RZ_PASS_RATE_PRIOR)
        ),
        # offense tendencies
        "early_down_pass_pct": float(
            team_stats.get("early_down_pass_pct", _EARLY_DOWN_PASS_PRIOR)
        ),
        "implied_margin": implied_margin,
        # opponent defense aggregates
        "tds_allowed_vs_pos": tds_allowed,
        "rz_td_rate_allowed": float(
            opponent_defense.get("rz_td_rate_allowed", _RZ_TD_RATE_ALLOWED_PRIOR)
        ),
        "def_epa": float(opponent_defense.get("def_epa", _DEF_EPA_PRIOR)),
        # scheme tags
        "cover_base": cover_base,
        "man_zone_lean": man_zone_lean,
        "pressure_lean": pressure_lean,
        "scheme_adj": scheme_adj,
        # weather
        "outdoor": outdoor,
        "wind_mph": wind_val,
        "precip": precip,
        # game environment
        "implied_total": float(implied_total) if implied_total is not None else None,
        "spread": implied_margin,
        "implied_team_total": implied_team_total_f,
    }


def fetch_player_usage_nflverse(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Optional nflverse hook; override/mock in ETL tests."""
    raise NotImplementedError(
        "fetch_player_usage_nflverse requires nflverse ETL wiring"
    )


def fetch_team_rz_nflverse(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Optional nflverse hook; override/mock in ETL tests."""
    raise NotImplementedError("fetch_team_rz_nflverse requires nflverse ETL wiring")
