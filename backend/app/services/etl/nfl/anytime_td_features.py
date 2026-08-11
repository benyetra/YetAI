"""Feature builders for NFL anytime-TD projections (pure + nflverse assembly)."""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Iterable, Sequence

from app.services.etl.nfl.team_names import _CANONICAL_BY_ABBR, normalize_team_name

logger = logging.getLogger(__name__)

SKILL_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
# Starters only: depth_team == 1 (exclude backups / depth 2+)
_STARTER_DEPTH_TEAM = 1
# Special-teams depth slots often tagged depth_team=1; exclude from TD board.
_SPECIAL_TEAMS_DEPTH_POSITIONS = frozenset(
    {"PR", "KR", "KOR", "PS", "H", "LS", "P", "K", "PK"}
)
# When depth charts are missing, keep top-N prior-usage players per team/pos.
_USAGE_STARTER_SLOTS: dict[str, int] = {"QB": 1, "RB": 1, "WR": 3, "TE": 1}
_MIN_PRIOR_TOUCHES = 3.0  # touches floor for usage-based starter fallback
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
    player_rz_share_raw = player_stats.get("player_rz_share")
    player_rz_share = float(
        player_rz_share_raw
        if player_rz_share_raw is not None
        else _PLAYER_RZ_SHARE_PRIOR.get(pos, 0.18)
    )
    conversion_raw = player_stats.get("conversion_rate")
    conversion_rate = float(
        conversion_raw
        if conversion_raw is not None
        else _CONVERSION_RATE_PRIOR.get(pos, 0.22)
    )

    tds_allowed_raw = opponent_defense.get("tds_allowed_vs_pos")
    tds_allowed = float(
        tds_allowed_raw
        if tds_allowed_raw is not None
        else _TDS_ALLOWED_PRIOR.get(pos, 0.45)
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


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(math.isnan(float(value)))
    except (TypeError, ValueError):
        return False


def _num(row: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key not in row:
            continue
        value = row.get(key)
        if _is_missing(value):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return default


def _str(row: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        if key not in row:
            continue
        value = row.get(key)
        if value is None or _is_missing(value):
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _anytime_tds(row: dict[str, Any]) -> float:
    return _num(row, "rushing_tds") + _num(row, "receiving_tds")


def _abbr_to_name(abbr: str) -> str:
    key = abbr.strip().upper()
    return _CANONICAL_BY_ABBR.get(key, normalize_team_name(abbr))


def records_from_dataframe(frame: Any) -> list[dict[str, Any]]:
    """Convert a pandas DataFrame (or list of dicts) to plain records."""
    if frame is None:
        return []
    if isinstance(frame, list):
        return [dict(r) for r in frame]
    if hasattr(frame, "to_dict"):
        return [dict(r) for r in frame.to_dict(orient="records")]
    return []


def aggregate_player_usage_from_weekly(
    weekly_records: Iterable[dict[str, Any]],
    *,
    as_of_week: int,
) -> dict[str, dict[str, Any]]:
    """Aggregate prior-week usage for each skill player (weeks < as_of_week)."""
    by_player: dict[str, list[dict[str, Any]]] = {}
    for raw in weekly_records:
        week = int(_num(raw, "week", default=0))
        if week <= 0 or week >= as_of_week:
            continue
        pos = _str(raw, "position").upper()
        if pos not in SKILL_POSITIONS:
            continue
        player_id = _str(raw, "player_id")
        if not player_id:
            continue
        by_player.setdefault(player_id, []).append(dict(raw))

    out: dict[str, dict[str, Any]] = {}
    for player_id, rows in by_player.items():
        rows.sort(key=lambda r: int(_num(r, "week", default=0)))
        last3 = rows[-3:]
        last5 = rows[-5:]
        targets_l3 = sum(_num(r, "targets") for r in last3) / max(len(last3), 1)
        carries_l3 = sum(_num(r, "carries") for r in last3) / max(len(last3), 1)
        td_l3 = sum(_anytime_tds(r) for r in last3)
        td_l5 = sum(_anytime_tds(r) for r in last5)
        td_season = sum(_anytime_tds(r) for r in rows)
        touches = sum(_num(r, "targets") + _num(r, "carries") for r in rows)
        conversion = (td_season / touches) if touches > 0 else None
        target_shares = [
            _num(r, "target_share")
            for r in last3
            if not _is_missing(r.get("target_share"))
        ]
        snap_pct = sum(target_shares) / len(target_shares) if target_shares else None
        # RZ share proxy: player's TD share of team TDs in prior weeks
        team = _str(rows[-1], "recent_team", "team")
        latest = rows[-1]
        out[player_id] = {
            "player_id": player_id,
            "player_name": _str(
                latest, "player_display_name", "player_name", "full_name"
            ),
            "position": _str(latest, "position").upper(),
            "team_abbr": team.upper(),
            "targets_l3": targets_l3,
            "carries_l3": carries_l3,
            "td_l3": td_l3,
            "td_l5": td_l5,
            "td_season": td_season,
            "conversion_rate": conversion,
            "snap_pct": snap_pct,
            "touches_season": touches,
            "games_count": len(rows),
        }
    return out


def aggregate_team_rz_from_weekly(
    weekly_records: Iterable[dict[str, Any]],
    *,
    as_of_week: int,
) -> dict[str, dict[str, Any]]:
    """Team opportunity proxies from prior weekly scoring (no PBP required)."""
    team_games: dict[str, set[int]] = {}
    team_tds: dict[str, float] = {}
    team_rec_tds: dict[str, float] = {}
    team_rush_tds: dict[str, float] = {}

    for raw in weekly_records:
        week = int(_num(raw, "week", default=0))
        if week <= 0 or week >= as_of_week:
            continue
        pos = _str(raw, "position").upper()
        if pos not in SKILL_POSITIONS:
            continue
        team = _str(raw, "recent_team", "team").upper()
        if not team:
            continue
        team_games.setdefault(team, set()).add(week)
        rush = _num(raw, "rushing_tds")
        rec = _num(raw, "receiving_tds")
        team_tds[team] = team_tds.get(team, 0.0) + rush + rec
        team_rec_tds[team] = team_rec_tds.get(team, 0.0) + rec
        team_rush_tds[team] = team_rush_tds.get(team, 0.0) + rush

    out: dict[str, dict[str, Any]] = {}
    for team, weeks in team_games.items():
        n = max(len(weeks), 1)
        tds_pg = team_tds.get(team, 0.0) / n
        # Approximate RZ trips from scoring rate (league ~3.2 trips → ~2.4 TDs).
        team_rz_trips = _clamp(tds_pg * 1.35, 2.0, 5.5)
        scored = team_tds.get(team, 0.0)
        pass_rate = (
            team_rec_tds.get(team, 0.0) / scored
            if scored > 0
            else _TEAM_RZ_PASS_RATE_PRIOR
        )
        out[team] = {
            "team_rz_trips": team_rz_trips,
            "team_rz_pass_rate": _clamp(pass_rate, 0.35, 0.75),
            "early_down_pass_pct": _EARLY_DOWN_PASS_PRIOR,
            "team_tds_per_game": tds_pg,
        }
    return out


def aggregate_defense_allowed_from_weekly(
    weekly_records: Iterable[dict[str, Any]],
    *,
    as_of_week: int,
) -> dict[str, dict[str, float]]:
    """TDs allowed by defense abbr vs position (per-game prior weeks)."""
    # defender -> pos -> (tds, game weeks)
    tds: dict[str, dict[str, float]] = {}
    weeks_seen: dict[str, set[int]] = {}

    for raw in weekly_records:
        week = int(_num(raw, "week", default=0))
        if week <= 0 or week >= as_of_week:
            continue
        pos = _str(raw, "position").upper()
        if pos not in SKILL_POSITIONS:
            continue
        defense = _str(raw, "opponent_team", "defteam").upper()
        if not defense:
            continue
        scored = _anytime_tds(raw)
        tds.setdefault(defense, {p: 0.0 for p in SKILL_POSITIONS})
        tds[defense][pos] = tds[defense].get(pos, 0.0) + scored
        weeks_seen.setdefault(defense, set()).add(week)

    out: dict[str, dict[str, float]] = {}
    for defense, by_pos in tds.items():
        n = max(len(weeks_seen.get(defense, set())), 1)
        out[defense] = {pos: by_pos.get(pos, 0.0) / n for pos in SKILL_POSITIONS}
        # RZ TD rate allowed proxy from scoring concentration
        out[defense]["rz_td_rate_allowed"] = _RZ_TD_RATE_ALLOWED_PRIOR
        out[defense]["def_epa"] = _DEF_EPA_PRIOR
    return out


def _player_rz_share_from_usage(
    usage: dict[str, Any],
    team_stats: dict[str, Any] | None,
    position: str,
) -> float | None:
    pos = _pos(position)
    prior = _PLAYER_RZ_SHARE_PRIOR.get(pos, 0.18)
    td_season = float(usage.get("td_season") or 0.0)
    team_tds_pg = float((team_stats or {}).get("team_tds_per_game") or 0.0)
    games = float(usage.get("games_count") or usage.get("game_count") or 0.0)
    team_tds = team_tds_pg * games
    if team_tds <= 0:
        return None
    share = td_season / team_tds
    return _clamp(0.55 * share + 0.45 * prior, 0.02, 0.55)


def _offensive_starter_depth_ok(raw: dict[str, Any]) -> bool:
    """True when depth chart row is an offensive starter (not ST/return)."""
    depth_team = int(_num(raw, "depth_team", "pos_rank", default=99))
    if depth_team != _STARTER_DEPTH_TEAM:
        return False
    depth_pos = _str(raw, "depth_position", "pos_abb", "position").upper()
    if depth_pos in _SPECIAL_TEAMS_DEPTH_POSITIONS:
        return False
    pos = _str(raw, "position", "pos_abb").upper()
    return pos in SKILL_POSITIONS


def starter_ids_from_usage(
    usage_by_player: dict[str, dict[str, Any]],
    *,
    slots: dict[str, int] | None = None,
) -> set[str]:
    """Top prior-usage players per team/position (depth-chart fallback / backtest)."""
    caps = slots or _USAGE_STARTER_SLOTS
    by_team_pos: dict[tuple[str, str], list[tuple[float, str]]] = {}
    for player_id, usage in usage_by_player.items():
        pos = str(usage.get("position") or "").upper()
        if pos not in SKILL_POSITIONS:
            continue
        team = str(usage.get("team_abbr") or "").upper()
        if not team:
            continue
        touches = float(usage.get("touches_season") or 0.0)
        if touches < _MIN_PRIOR_TOUCHES:
            continue
        # Prefer role-relevant volume when present.
        if pos == "RB":
            score = float(usage.get("carries_l3") or 0.0) * 10.0 + touches
        elif pos in {"WR", "TE"}:
            score = float(usage.get("targets_l3") or 0.0) * 10.0 + touches
        else:
            score = touches
        by_team_pos.setdefault((team, pos), []).append((score, player_id))

    out: set[str] = set()
    for (team, pos), ranked in by_team_pos.items():
        ranked.sort(key=lambda t: (-t[0], t[1]))
        for _, player_id in ranked[: caps.get(pos, 1)]:
            out.add(player_id)
    return out


def select_skill_universe(
    *,
    depth_records: Iterable[dict[str, Any]],
    usage_by_player: dict[str, dict[str, Any]],
    week: int,
) -> list[dict[str, Any]]:
    """Active QB/RB/WR/TE starters only (depth_team=1; usage top-N if no depth)."""
    universe: dict[str, dict[str, Any]] = {}

    # Depth chart starters for latest week <= target (all WR1/RB1/… rows, not ST).
    by_player_best: dict[str, dict[str, Any]] = {}
    for raw in depth_records:
        if not _offensive_starter_depth_ok(raw):
            continue
        team = _str(raw, "club_code", "team").upper()
        player_id = _str(raw, "gsis_id", "player_id")
        if not team or not player_id:
            continue
        depth_week = int(_num(raw, "week", default=week))
        if depth_week > week:
            continue
        pos = _str(raw, "position", "pos_abb").upper()
        candidate = {
            "player_id": player_id,
            "player_name": _str(raw, "full_name", "football_name", "player_name"),
            "position": pos,
            "team_abbr": team,
            "depth_team": _STARTER_DEPTH_TEAM,
            "depth_week": depth_week,
            "depth_position": _str(raw, "depth_position", default=pos),
        }
        prev = by_player_best.get(player_id)
        if prev is None or candidate["depth_week"] >= prev["depth_week"]:
            by_player_best[player_id] = candidate

    universe.update(by_player_best)

    if not universe:
        # No depth published yet — approximate starters from prior usage.
        for player_id in starter_ids_from_usage(usage_by_player):
            usage = usage_by_player[player_id]
            universe[player_id] = {
                "player_id": player_id,
                "player_name": usage.get("player_name") or player_id,
                "position": usage.get("position"),
                "team_abbr": usage.get("team_abbr"),
                "depth_team": _STARTER_DEPTH_TEAM,
                "depth_week": week,
            }
    else:
        # Enrich names/teams from usage; do not add non-starters.
        for player_id, player in list(universe.items()):
            usage = usage_by_player.get(player_id) or {}
            if usage.get("team_abbr"):
                player["team_abbr"] = usage["team_abbr"]
            if usage.get("player_name"):
                player["player_name"] = usage["player_name"]
            if usage.get("position"):
                player["position"] = usage["position"]

    return list(universe.values())


def _schedule_matchups(
    schedule_records: Iterable[dict[str, Any]], *, week: int
) -> dict[str, dict[str, Any]]:
    """Map team abbr → opponent, game_date, weather proxies."""
    out: dict[str, dict[str, Any]] = {}
    for raw in schedule_records:
        if int(_num(raw, "week", default=-1)) != week:
            continue
        game_type = _str(raw, "game_type", default="REG").upper()
        if game_type and game_type != "REG":
            continue
        home = _str(raw, "home_team").upper()
        away = _str(raw, "away_team").upper()
        if not home or not away:
            continue
        gameday = raw.get("gameday")
        game_date: date | None
        if isinstance(gameday, date):
            game_date = gameday
        elif gameday is not None and not _is_missing(gameday):
            try:
                game_date = date.fromisoformat(str(gameday)[:10])
            except ValueError:
                game_date = None
        else:
            game_date = None

        roof = _str(raw, "roof").lower()
        outdoor = roof not in ("dome", "closed", "indoor")
        wind = raw.get("wind")
        wind_mph = None if _is_missing(wind) else float(wind)

        home_entry = {
            "opponent_abbr": away,
            "game_date": game_date,
            "home": True,
            "outdoor": outdoor,
            "wind_mph": wind_mph,
            "precip": False,
        }
        away_entry = {
            "opponent_abbr": home,
            "game_date": game_date,
            "home": False,
            "outdoor": outdoor,
            "wind_mph": wind_mph,
            "precip": False,
        }
        out[home] = home_entry
        out[away] = away_entry
    return out


def _scheme_for_team(
    schemes: dict[str, dict[str, Any]] | None, team_abbr: str
) -> dict[str, Any] | None:
    if not schemes:
        return None
    if team_abbr in schemes:
        return schemes[team_abbr]
    full = _abbr_to_name(team_abbr)
    return schemes.get(full)


def build_weekly_feature_rows(
    season: int,
    week: int,
    *,
    weekly_records: list[dict[str, Any]] | None = None,
    schedule_records: list[dict[str, Any]] | None = None,
    depth_records: list[dict[str, Any]] | None = None,
    pbp_records: list[dict[str, Any]] | None = None,
    schemes: dict[str, dict[str, Any]] | None = None,
    game_lines_by_team: dict[str, dict[str, Any]] | None = None,
    usage_as_of_week: int | None = None,
    pbp_as_of_week: int | None = None,
) -> list[dict[str, Any]]:
    """Assemble projector feature rows for one REG week (injectable inputs).

    ``usage_as_of_week`` defaults to ``week`` (in-season lookback: weeks < week).
    Pass a large value (e.g. 99) when ``weekly_records`` are from a prior season
    so all prior-season weeks count as usage/defense priors.

    When ``pbp_records`` is provided, team RZ trips/pass rate and player
    RZ share / RZ targets / GL carries come from PBP (yardline ≤20 / ≤5);
    weekly scoring proxies remain the fallback. ``pbp_as_of_week`` defaults to
    ``usage_as_of_week`` / ``week``.
    """
    weekly_records = weekly_records if weekly_records is not None else []
    schedule_records = schedule_records if schedule_records is not None else []
    depth_records = depth_records if depth_records is not None else []
    if schemes is None:
        from app.services.etl.nfl.scheme_loader import load_schemes_from_yaml

        schemes = load_schemes_from_yaml()

    as_of = week if usage_as_of_week is None else usage_as_of_week
    pbp_as_of = as_of if pbp_as_of_week is None else pbp_as_of_week
    usage = aggregate_player_usage_from_weekly(weekly_records, as_of_week=as_of)
    team_rz = aggregate_team_rz_from_weekly(weekly_records, as_of_week=as_of)
    player_rz_pbp: dict[str, dict[str, Any]] = {}
    if pbp_records:
        from app.services.etl.nfl.anytime_td_pbp import (
            aggregate_player_rz_from_pbp,
            aggregate_team_rz_from_pbp,
        )

        pbp_team = aggregate_team_rz_from_pbp(pbp_records, as_of_week=pbp_as_of)
        for team, stats in pbp_team.items():
            merged = dict(team_rz.get(team) or {})
            # Prefer PBP trips/pass rate; keep weekly tds_pg for TD-share fallback.
            for key in ("team_rz_trips", "team_rz_pass_rate", "early_down_pass_pct"):
                if stats.get(key) is not None:
                    merged[key] = stats[key]
            team_rz[team] = merged
        player_rz_pbp = aggregate_player_rz_from_pbp(pbp_records, as_of_week=pbp_as_of)

    defense = aggregate_defense_allowed_from_weekly(weekly_records, as_of_week=as_of)
    matchups = _schedule_matchups(schedule_records, week=week)
    universe = select_skill_universe(
        depth_records=depth_records, usage_by_player=usage, week=week
    )

    rows: list[dict[str, Any]] = []
    for player in universe:
        team_abbr = str(player.get("team_abbr") or "").upper()
        if not team_abbr or team_abbr not in matchups:
            continue
        match = matchups[team_abbr]
        opp_abbr = match["opponent_abbr"]
        pos = str(player.get("position") or "WR").upper()
        player_id = str(player["player_id"])
        player_usage = usage.get(player_id, {})
        team_stats = team_rz.get(team_abbr, {})
        def_stats = defense.get(opp_abbr, {})
        pbp_player = player_rz_pbp.get(player_id, {})

        player_stats = {
            "targets_l3": player_usage.get("targets_l3"),
            "carries_l3": player_usage.get("carries_l3"),
            "td_l3": player_usage.get("td_l3"),
            "td_l5": player_usage.get("td_l5"),
            "td_season": player_usage.get("td_season"),
            "snap_pct": player_usage.get("snap_pct"),
            "conversion_rate": player_usage.get("conversion_rate"),
        }
        if pbp_player.get("rz_targets") is not None:
            player_stats["rz_targets"] = pbp_player["rz_targets"]
        if pbp_player.get("gl_carries") is not None:
            player_stats["gl_carries"] = pbp_player["gl_carries"]
        # Prefer PBP RZ share; fall back to TD-share proxy from weekly usage.
        if pbp_player.get("player_rz_share") is not None:
            player_stats["player_rz_share"] = pbp_player["player_rz_share"]
        else:
            rz_share = _player_rz_share_from_usage(player_usage, team_stats, pos)
            if rz_share is not None:
                player_stats["player_rz_share"] = rz_share

        tds_allowed = def_stats.get(pos)
        opponent_defense = {
            "tds_allowed_vs_pos": tds_allowed,
            "rz_td_rate_allowed": def_stats.get("rz_td_rate_allowed"),
            "def_epa": def_stats.get("def_epa"),
        }

        game_env: dict[str, Any] = {}
        if game_lines_by_team and team_abbr in game_lines_by_team:
            game_env.update(game_lines_by_team[team_abbr])

        weather = {
            "outdoor": bool(match.get("outdoor")),
            "wind_mph": match.get("wind_mph"),
            "precip": bool(match.get("precip")),
        }

        row = build_player_feature_row(
            player_id=player_id,
            player_name=str(player.get("player_name") or player_id),
            position=pos,
            team_name=_abbr_to_name(team_abbr),
            opponent_team_name=_abbr_to_name(opp_abbr),
            season=season,
            week=week,
            player_stats=player_stats,
            team_stats=team_stats,
            opponent_defense=opponent_defense,
            scheme=_scheme_for_team(schemes, opp_abbr),
            weather=weather,
            game_env=game_env,
        )
        if match.get("game_date") is not None:
            row["game_date"] = match["game_date"]
        rows.append(row)

    # Sort by opportunity proxy (λ inputs); projector re-ranks by P(TD).
    rows.sort(
        key=lambda r: (
            -float(r.get("player_rz_share") or 0) * float(r.get("team_rz_trips") or 0),
            r["player_name"],
        )
    )
    return rows


def _import_nfl():
    try:
        import nfl_data_py as nfl
    except ImportError as exc:
        raise RuntimeError(
            "nfl_data_py not installed. "
            "Run: pip install nfl-data-py==0.3.3 --no-deps && pip install appdirs fastparquet"
        ) from exc
    return nfl


def _is_missing_nflverse_data_error(exc: BaseException) -> bool:
    """True when nflverse parquet is not published yet (typical HTTP 404)."""
    from urllib.error import HTTPError, URLError

    if isinstance(exc, HTTPError) and getattr(exc, "code", None) == 404:
        return True
    if isinstance(exc, URLError):
        return True
    text = str(exc).lower()
    return "404" in text or "not found" in text


def _usage_as_of_week_for_priors(
    *,
    season: int,
    week: int,
    weekly_season: int | None,
) -> int:
    """When weekly rows are from a prior season, include all weeks as priors."""
    if weekly_season is not None and weekly_season < season:
        return 99
    return week


# nfl_data_py historically served player_stats_{season}.parquet; newer seasons
# publish under stats_player/stats_player_week_{season}.parquet (team vs recent_team).
_STATS_PLAYER_WEEK_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "stats_player/stats_player_week_{season}.parquet"
)


def normalize_weekly_record(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize nflverse weekly schemas (legacy + stats_player_week)."""
    out = dict(row)
    team = _str(out, "recent_team", "team")
    if team:
        out["recent_team"] = team
        out.setdefault("team", team)
    opp = _str(out, "opponent_team", "opponent", "defteam")
    if opp:
        out["opponent_team"] = opp
    return out


def _read_stats_player_week_parquet(season: int) -> Any:
    """Load ``stats_player_week_{season}.parquet`` (pandas DataFrame)."""
    import pandas as pd

    url = _STATS_PLAYER_WEEK_URL.format(season=int(season))
    return pd.read_parquet(url)


def load_weekly_records_for_season(season: int) -> list[dict[str, Any]]:
    """Load one season of weekly player rows (legacy import, then stats_player_week).

    Raises the last missing-data error when neither source is published yet.
    """
    nfl = _import_nfl()
    last_err: BaseException | None = None
    try:
        raw = records_from_dataframe(nfl.import_weekly_data([int(season)]))
        return [normalize_weekly_record(r) for r in raw]
    except Exception as exc:
        if not _is_missing_nflverse_data_error(exc):
            raise
        last_err = exc
        logger.info(
            "nflverse import_weekly_data missing for season=%s (%s); "
            "trying stats_player_week parquet",
            season,
            exc,
        )

    try:
        frame = _read_stats_player_week_parquet(int(season))
        raw = records_from_dataframe(frame)
        if not raw:
            raise FileNotFoundError(
                f"stats_player_week_{season}.parquet returned no rows"
            )
        logger.info(
            "loaded nflverse stats_player_week_%s.parquet (%s rows)",
            season,
            len(raw),
        )
        return [normalize_weekly_record(r) for r in raw]
    except Exception as exc:
        if last_err is not None and _is_missing_nflverse_data_error(exc):
            raise last_err from exc
        if _is_missing_nflverse_data_error(exc):
            raise
        # Non-404 errors from parquet path (e.g. missing pyarrow) should surface.
        if last_err is not None:
            raise exc from last_err
        raise


def load_weekly_records_with_fallback(
    season: int, *, max_lookback: int = 3
) -> tuple[list[dict[str, Any]], int | None]:
    """Load nflverse weekly player rows, falling back to recent prior seasons.

    Early-season / preseason often 404s for the current season parquet (and
    sometimes the previous season until nflverse publishes). Walk back up to
    ``max_lookback`` years and return ``(records, source_season)``.

    Prefers ``import_weekly_data``, then ``stats_player_week_{season}.parquet``.
    """
    last_err: BaseException | None = None
    for candidate in range(season, season - max_lookback - 1, -1):
        if candidate < 1999:
            break
        try:
            records = load_weekly_records_for_season(candidate)
        except Exception as exc:
            if not _is_missing_nflverse_data_error(exc):
                raise
            last_err = exc
            logger.info(
                "nflverse weekly data missing for season=%s (%s); trying prior",
                candidate,
                exc,
            )
            continue
        if candidate < season:
            logger.warning(
                "nflverse weekly data for %s unavailable; using %s for "
                "usage/defense priors",
                season,
                candidate,
            )
        return records, candidate
    if last_err is not None:
        logger.warning(
            "no nflverse weekly data found for seasons %s–%s: %s",
            season - max_lookback,
            season,
            last_err,
        )
    return [], None


def probe_weekly_season_available(season: int) -> bool:
    """True when weekly rows can be loaded for ``season`` (no prior-year fallback)."""
    try:
        records = load_weekly_records_for_season(int(season))
    except Exception as exc:
        if _is_missing_nflverse_data_error(exc):
            return False
        raise
    return bool(records)


def resolve_available_weekly_seasons(
    candidates: Sequence[int],
) -> tuple[int, ...]:
    """Filter ``candidates`` to seasons with published weekly data."""
    available: list[int] = []
    for season in candidates:
        if probe_weekly_season_available(int(season)):
            available.append(int(season))
        else:
            logger.info("walk-forward skip season=%s — weekly not published", season)
    return tuple(available)


def fetch_player_usage_nflverse(season: int, week: int) -> dict[str, dict[str, Any]]:
    """Load prior-week player usage from nflverse weekly data."""
    records, weekly_season = load_weekly_records_with_fallback(season)
    as_of = _usage_as_of_week_for_priors(
        season=season, week=week, weekly_season=weekly_season
    )
    return aggregate_player_usage_from_weekly(records, as_of_week=as_of)


def fetch_team_rz_nflverse(season: int, week: int) -> dict[str, dict[str, Any]]:
    """Load team RZ/opportunity proxies from nflverse weekly data."""
    records, weekly_season = load_weekly_records_with_fallback(season)
    as_of = _usage_as_of_week_for_priors(
        season=season, week=week, weekly_season=weekly_season
    )
    return aggregate_team_rz_from_weekly(records, as_of_week=as_of)


def load_game_lines_by_team(season: int, week: int) -> dict[str, dict[str, Any]]:
    """Optional game-env features from ``pred_nfl_game_lines`` (best-effort)."""
    try:
        from app.core.database import SessionLocal
        from app.models.predictions_models import NFLGameLines
    except Exception:
        return {}

    db = SessionLocal()
    try:
        lines = db.query(NFLGameLines).all()
    except Exception as exc:
        logger.info("game lines unavailable for anytime TD features: %s", exc)
        return {}
    finally:
        db.close()

    # Match by team name without requiring schedule join; use latest line per team pair.
    by_team: dict[str, dict[str, Any]] = {}
    for line in lines:
        total = line.total
        if total is None:
            continue
        home = normalize_team_name(line.home_team_name)
        away = normalize_team_name(line.away_team_name)
        spread_home = line.spread_home
        # implied team totals from market total + spread
        if spread_home is not None:
            home_implied = (float(total) - float(spread_home)) / 2.0
            away_implied = float(total) - home_implied
        else:
            home_implied = float(total) / 2.0
            away_implied = home_implied
        by_team[home] = {
            "implied_total": float(total),
            "spread": float(spread_home) if spread_home is not None else None,
            "implied_team_total": home_implied,
        }
        by_team[away] = {
            "implied_total": float(total),
            "spread": (-float(spread_home) if spread_home is not None else None),
            "implied_team_total": away_implied,
        }
        # also key by abbreviation when known
        for abbr, name in _CANONICAL_BY_ABBR.items():
            if name == home:
                by_team[abbr] = by_team[home]
            if name == away:
                by_team[abbr] = by_team[away]
    return by_team


def fetch_weekly_feature_inputs_nflverse(season: int, week: int) -> dict[str, Any]:
    """Fetch weekly / schedule / depth / PBP records from nflverse.

    ``week`` is unused here; lookback/`usage_as_of_week` is applied in
    ``build_feature_rows_from_nflverse``. Schedules/depth stay on ``season``.
    """
    _ = week
    from app.services.etl.nfl.anytime_td_pbp import load_pbp_records_with_fallback

    nfl = _import_nfl()
    weekly, weekly_season = load_weekly_records_with_fallback(season)
    schedules = records_from_dataframe(nfl.import_schedules([season]))
    try:
        depth = records_from_dataframe(nfl.import_depth_charts([season]))
    except Exception as exc:
        if _is_missing_nflverse_data_error(exc):
            logger.warning(
                "depth charts unavailable for %s (%s); using weekly universe only",
                season,
                exc,
            )
        else:
            logger.warning(
                "depth charts unavailable (%s); using weekly universe only", exc
            )
        depth = []
    pbp, pbp_season = load_pbp_records_with_fallback(season)
    return {
        "weekly_records": weekly,
        "weekly_season": weekly_season,
        "schedule_records": schedules,
        "depth_records": depth,
        "pbp_records": pbp,
        "pbp_season": pbp_season,
    }


def build_feature_rows_from_nflverse(season: int, week: int) -> list[dict[str, Any]]:
    """End-to-end: nflverse + YAML schemes (+ optional game lines) → feature rows."""
    inputs = fetch_weekly_feature_inputs_nflverse(season, week)
    try:
        game_lines = load_game_lines_by_team(season, week)
    except Exception as exc:
        logger.info("skipping game lines for anytime TD: %s", exc)
        game_lines = {}
    usage_as_of = _usage_as_of_week_for_priors(
        season=season,
        week=week,
        weekly_season=inputs.get("weekly_season"),
    )
    pbp_season = inputs.get("pbp_season")
    pbp_as_of = (
        99 if pbp_season is not None and int(pbp_season) < season else usage_as_of
    )
    return build_weekly_feature_rows(
        season,
        week,
        weekly_records=inputs["weekly_records"],
        schedule_records=inputs["schedule_records"],
        depth_records=inputs["depth_records"],
        pbp_records=inputs.get("pbp_records") or None,
        game_lines_by_team=game_lines,
        usage_as_of_week=usage_as_of,
        pbp_as_of_week=pbp_as_of,
    )
