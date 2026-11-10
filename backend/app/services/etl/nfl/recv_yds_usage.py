"""Usage priors for lined receivers, from their nflverse game logs.

For every lined RB / WR / TE this builds the three inputs of the yards model
from games already played (this season, plus last season at a discount):

* ``target_share``       recency-weighted targets / team pass attempts
* ``team_pass_attempts`` the player's current team's recent attempts per game
* ``yards_per_target``   his yards per target, shrunk to the position average

The first version read all three off the player's single most recent game and
multiplied targets by yards per *reception*. One game is mostly noise, and
yards per reception ignores incompletions, so it over-projected by about 28
yards a player (walk-forward on 2025 + 2026: MAE 43.2 / 44.6). The same
backtest puts this version at 23.5 / 24.2 with the bias near +2, against 24.8 /
26.8 for a plain season average.

Nothing here reads the sportsbook line: targets are never inferred from it.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable

from app.services.etl.nfl.nfl_common import (
    get_current_nfl_week,
    get_nfl_season,
    has_kicked_off,
)
from app.services.etl.nfl.player_names import player_name_key
from app.services.etl.nfl.recv_yds_features import SKILL_POSITIONS

# A game's weight halves every this many games back.
RECENCY_HALF_LIFE_GAMES = 6.0
# Last season's games count this much of a current-season game (role, QB and
# scheme changes), on top of the recency decay.
PREV_SEASON_WEIGHT = 0.35

# League yards per target by position (nflverse REG 2024-2026) and how many
# targets of it the player's own rate is blended with.
YARDS_PER_TARGET_PRIOR = {"WR": 8.0, "TE": 7.3, "RB": 5.9}
YARDS_PER_TARGET_PRIOR_TARGETS = 40.0
CATCH_RATE_PRIOR = {"WR": 0.63, "TE": 0.72, "RB": 0.79}

LEAGUE_PASS_ATTEMPTS = 32.5
TEAM_ATTEMPT_GAMES = 6  # recent team games averaged for pass volume
TEAM_ATTEMPT_PRIOR_GAMES = 3.0  # league-average games blended in

UNKNOWN_OPPONENT = "TBD"


def _name_key(name: str) -> str:
    return player_name_key(name)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # NaN -> None


def _team_abbr(row: dict[str, Any]) -> str:
    return str(row.get("recent_team") or row.get("team") or "").strip().upper()


def _team_label(raw: Any) -> str | None:
    """Expand nflverse abbrs when possible; keep full names as-is."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        from app.services.etl.nfl.anytime_td_features import _abbr_to_name

        return _abbr_to_name(text)
    except Exception:
        return text


def _row_name_keys(row: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for field in ("player_display_name", "player_name"):
        val = str(row.get(field) or "").strip()
        if val:
            keys.add(_name_key(val))
    return keys


def _row_display_name(row: dict[str, Any]) -> str:
    # nflverse weekly uses abbreviated player_name (S.Diggs); Odds uses full names.
    return str(row.get("player_display_name") or row.get("player_name") or "").strip()


def team_pass_attempts_by_game(
    weekly_rows: Iterable[dict[str, Any]],
) -> dict[tuple[int, int, str], float]:
    """(season, week, team) -> pass attempts, summed over everyone who threw."""
    totals: dict[tuple[int, int, str], float] = {}
    for row in weekly_rows:
        attempts = _num(row.get("attempts"))
        team = _team_abbr(row)
        if not attempts or attempts <= 0 or not team:
            continue
        key = (int(_num(row.get("season")) or 0), int(_num(row.get("week")) or 0), team)
        totals[key] = totals.get(key, 0.0) + attempts
    return totals


def _game_team_attempts(
    row: dict[str, Any],
    targets: float,
    team_attempts: dict[tuple[int, int, str], float],
    season: int,
) -> float | None:
    """Team pass attempts in this row's game: summed passers, else the row's
    own ``team_pass_attempts``, else targets / target_share."""
    key = (
        int(_num(row.get("season")) or season),
        int(_num(row.get("week")) or 0),
        _team_abbr(row),
    )
    attempts = team_attempts.get(key) or _num(row.get("team_pass_attempts"))
    if not attempts:
        share = _num(row.get("target_share"))
        if share and share > 0 and targets > 0:
            attempts = targets / share
    return attempts if attempts and attempts > 0 else None


def projected_team_pass_attempts(
    team: str,
    team_attempts: dict[tuple[int, int, str], float],
    *,
    season: int,
    week: int,
) -> float:
    """The team's last ``TEAM_ATTEMPT_GAMES`` games this season, blended with
    ``TEAM_ATTEMPT_PRIOR_GAMES`` league-average games."""
    games = sorted(
        (wk, att)
        for (yr, wk, tm), att in team_attempts.items()
        if tm == team and yr == season and 0 < wk < week
    )[-TEAM_ATTEMPT_GAMES:]
    total = sum(att for _, att in games) + TEAM_ATTEMPT_PRIOR_GAMES * (
        LEAGUE_PASS_ATTEMPTS
    )
    return total / (len(games) + TEAM_ATTEMPT_PRIOR_GAMES)


def usage_from_games(
    games: list[dict[str, Any]],
    *,
    season: int,
    position: str,
) -> dict[str, float] | None:
    """Weighted usage rates from one player's prior games (oldest first).

    Each game needs ``season``, ``targets``, ``receptions``, ``receiving_yards``
    and ``team_attempts``. None when there are no targets to learn from."""
    w_targets = w_attempts = w_yards = w_receptions = 0.0
    current_games = 0
    n = len(games)
    for idx, game in enumerate(games):
        weight = 0.5 ** ((n - 1 - idx) / RECENCY_HALF_LIFE_GAMES)
        if int(game["season"]) == season:
            current_games += 1
        else:
            weight *= PREV_SEASON_WEIGHT
        w_targets += weight * game["targets"]
        w_attempts += weight * game["team_attempts"]
        w_yards += weight * game["receiving_yards"]
        w_receptions += weight * game["receptions"]
    if w_attempts <= 0 or w_targets <= 0:
        return None
    prior_ypt = YARDS_PER_TARGET_PRIOR.get(position, 7.5)
    yards_per_target = (w_yards + YARDS_PER_TARGET_PRIOR_TARGETS * prior_ypt) / (
        w_targets + YARDS_PER_TARGET_PRIOR_TARGETS
    )
    catch_rate = min(1.0, w_receptions / w_targets)
    return {
        "target_share": w_targets / w_attempts,
        "yards_per_target": yards_per_target,
        "catch_rate": catch_rate,
        "ypr": (w_yards / w_receptions) if w_receptions > 0 else 0.0,
        "games": float(n),
        "current_season_games": float(current_games),
    }


def select_usage_priors_for_names(
    player_names: list[str],
    weekly_rows: list[dict[str, Any]],
    *,
    season: int,
    week: int,
    game_date: date | str,
    schedule_by_team: dict[str, dict[str, Any]] | None = None,
    game_env_by_team: dict[str, dict[str, Any]] | None = None,
    defense_by_team: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Usage dicts for the lined names, from games before ``(season, week)``.

    ``schedule_by_team`` maps a team (nflverse abbr or full name) to this
    week's ``opponent_team_name`` / ``game_date``. When it is given, a player
    whose team is not in it (bye, or a game already kicked off) is skipped;
    when it is not, the opponent is published as "TBD" rather than guessed
    from last week's game.
    """
    wanted = {_name_key(n) for n in player_names}
    wanted.discard("")
    game_env_by_team = game_env_by_team or {}
    defense_by_team = defense_by_team or {}
    team_attempts = team_pass_attempts_by_game(weekly_rows)

    by_player: dict[str, list[tuple[int, int, dict[str, Any]]]] = {}
    for row in weekly_rows:
        pos = str(row.get("position") or "").upper()
        if pos not in SKILL_POSITIONS:
            continue
        if not _row_name_keys(row).intersection(wanted):
            continue
        pname = _row_display_name(row)
        if not pname:
            continue
        row_season = int(_num(row.get("season")) or season)
        row_week = int(_num(row.get("week")) or 0)
        # Only games already played: earlier weeks this season, or last season.
        if row_season == season:
            if row_week >= week:
                continue
        elif row_season != season - 1:
            continue
        player_id = str(row.get("player_id") or row.get("gsis_id") or pname)
        by_player.setdefault(player_id, []).append((row_season, row_week, row))

    out: list[dict[str, Any]] = []
    for player_id, entries in by_player.items():
        entries.sort(key=lambda e: (e[0], e[1]))
        latest = entries[-1][2]
        pos = str(latest.get("position") or "").upper()
        games: list[dict[str, Any]] = []
        for row_season, _, row in entries:
            targets = _num(row.get("targets"))
            if targets is None:
                share = _num(row.get("target_share"))
                attempts = _num(row.get("team_pass_attempts"))
                targets = share * attempts if share and attempts else None
            if targets is None:
                continue
            attempts = _game_team_attempts(row, targets, team_attempts, season)
            if attempts is None:
                continue
            games.append(
                {
                    "season": row_season,
                    "targets": targets,
                    "receptions": _num(row.get("receptions")) or 0.0,
                    "receiving_yards": _num(row.get("receiving_yards")) or 0.0,
                    "team_attempts": attempts,
                }
            )
        usage = usage_from_games(games, season=season, position=pos)
        if usage is None:
            continue

        team_abbr = _team_abbr(latest)
        team_raw = latest.get("team_name") or team_abbr
        team = _team_label(team_raw)
        if not team:
            continue
        sched: dict[str, Any] | None = None
        if schedule_by_team is not None:
            sched = (
                schedule_by_team.get(team_abbr)
                or schedule_by_team.get(str(team))
                or schedule_by_team.get(str(team_raw))
            )
            if sched is None:
                continue  # bye week, or the game has already kicked off
        sched = sched or {}
        opponent = (
            _team_label(sched.get("opponent_team_name") or sched.get("opponent_abbr"))
            or UNKNOWN_OPPONENT
        )
        attempts_proj = (
            projected_team_pass_attempts(
                team_abbr, team_attempts, season=season, week=week
            )
            if any(tm == team_abbr for _, _, tm in team_attempts)
            else games[-1]["team_attempts"]
        )
        out.append(
            {
                "player_id": player_id,
                "player_name": _row_display_name(latest),
                "position": pos,
                "team_name": team,
                "opponent_team_name": opponent,
                "game_date": sched.get("game_date") or game_date,
                "season": season,
                "week": week,
                "target_share": usage["target_share"],
                "team_pass_attempts": float(attempts_proj),
                "yards_per_target": usage["yards_per_target"],
                "catch_rate": usage["catch_rate"],
                "ypr": usage["ypr"],
                "games": usage["games"],
                "current_season_games": usage["current_season_games"],
                "adot": None,
                "snap_pct": latest.get("snap_pct") or latest.get("offense_pct"),
                "game_env": game_env_by_team.get(str(team))
                or game_env_by_team.get(team_abbr),
                "opponent_defense": defense_by_team.get(str(opponent)),
            }
        )
    return out


def load_weekly_receiver_rows(season: int) -> list[dict[str, Any]]:
    """Regular-season nflverse weekly rows for this season and last."""
    from app.services.etl.nfl.nflverse_weekly import load_weekly_frame

    rows: list[dict[str, Any]] = []
    for year in (int(season) - 1, int(season)):
        frame = load_weekly_frame(year)
        if frame is None:
            continue
        if "season_type" in frame.columns:
            frame = frame[frame["season_type"] == "REG"]
        rows.extend(frame.to_dict(orient="records"))
    return rows


def schedule_by_team_for_week(
    schedule_rows: Iterable[dict[str, Any]],
    *,
    week: int,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """team abbr -> this week's opponent / game date, for REG games that have
    not kicked off (a started game's board row is final)."""
    out: dict[str, dict[str, Any]] = {}
    for game in schedule_rows:
        if int(_num(game.get("week")) or -1) != week:
            continue
        if str(game.get("game_type") or "REG").upper() != "REG":
            continue
        home = str(game.get("home_team") or "").upper()
        away = str(game.get("away_team") or "").upper()
        gameday = str(game.get("gameday") or "")[:10]
        if not home or not away or not gameday:
            continue
        try:
            game_day = date.fromisoformat(gameday)
        except ValueError:
            continue
        kickoff: datetime | date = game_day
        gametime = str(game.get("gametime") or "").strip()
        if gametime and gametime.lower() != "nan":
            try:
                kickoff = datetime.strptime(
                    f"{gameday} {gametime[:5]}", "%Y-%m-%d %H:%M"
                )
            except ValueError:
                kickoff = game_day
        if has_kicked_off(kickoff, now=now):
            continue
        out[home] = {"opponent_abbr": away, "game_date": gameday, "home": True}
        out[away] = {"opponent_abbr": home, "game_date": gameday, "home": False}
    return out


def load_schedule_by_team(season: int, week: int) -> dict[str, dict[str, Any]] | None:
    """This week's matchups from nflverse, or None when the schedule is down."""
    try:
        import nfl_data_py as nfl

        frame = nfl.import_schedules([int(season)])
        return schedule_by_team_for_week(frame.to_dict(orient="records"), week=week)
    except Exception:
        return None


def load_usage_priors_for_names(player_names: list[str]) -> list[dict[str, Any]]:
    """Return skill-position usage dicts for soft-name matches in ``player_names``."""
    season = int(get_nfl_season())
    week = int(get_current_nfl_week())
    weekly = load_weekly_receiver_rows(season)
    return select_usage_priors_for_names(
        player_names,
        weekly,
        season=season,
        week=week,
        game_date=date.today().isoformat(),
        schedule_by_team=load_schedule_by_team(season, week),
    )
