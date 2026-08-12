"""In-memory preload for WNBA prop training (avoids N+1 DB round-trips)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta

from app.models.predictions_models import (
    WNBAGameLines,
    WNBARecentGames,
    WNBATeamDefenseStats,
    WNBATeamOffenseStats,
    WNBATeamRoster,
)
from app.services.etl.wnba._expected_minutes import LOOKBACK_GAMES

logger = logging.getLogger(__name__)

LOOKBACK_BUFFER_DAYS = 400


@dataclass
class TrainingContext:
    roster_by_player: dict[int, WNBATeamRoster]
    offense_by_team: dict[int, WNBATeamOffenseStats]
    defense_by_team: dict[int, WNBATeamDefenseStats]
    team_name_by_player: dict[int, str]
    games_by_player: dict[int, list[WNBARecentGames]]
    game_lines_by_date: dict[date, list[WNBAGameLines]]
    players_by_team: dict[int, list[int]]

    def player_team_name(self, player_id: int) -> str:
        return self.team_name_by_player.get(player_id, "")

    def recent_games_before(
        self, player_id: int, game_date: date, *, limit: int = LOOKBACK_GAMES
    ) -> list[WNBARecentGames]:
        games = self.games_by_player.get(player_id, [])
        prior = [g for g in games if g.game_date < game_date]
        if not prior:
            return []
        return list(reversed(prior[-limit:]))

    def opponent_defense(self, team_id: int) -> WNBATeamDefenseStats | None:
        return self.defense_by_team.get(team_id)

    def opponent_offense(self, team_id: int) -> WNBATeamOffenseStats | None:
        return self.offense_by_team.get(team_id)

    def game_line_for_team(
        self, game_date: date, opponent_team_id: int, team_name: str
    ) -> WNBAGameLines | None:
        for line in self.game_lines_by_date.get(game_date, ()):
            if (
                line.home_team_id == opponent_team_id
                or line.away_team_id == opponent_team_id
            ):
                return line
            if team_name:
                if (
                    line.home_team_name
                    and team_name.lower() in line.home_team_name.lower()
                ):
                    return line
                if (
                    line.away_team_name
                    and team_name.lower() in line.away_team_name.lower()
                ):
                    return line
        return None

    def teammate_out_boost_inputs(
        self, player_id: int, game_date: date
    ) -> tuple[float, float]:
        """
        Historical freed minutes + active pool for teammate-out boost.

        Infers absences from missing box scores on ``game_date`` for rotation
        teammates (aligns training with live ``_teammate_out_boost``).
        """
        from app.services.etl.wnba._expected_minutes import (
            ROTATION_MINUTES_L5,
            apply_context_adjustments,
            calc_metrics,
            infer_historical_freed_minutes,
        )

        roster = self.roster_by_player.get(player_id)
        if roster is None:
            return 0.0, 0.0
        teammates = self.players_by_team.get(roster.team_id, [])
        if not teammates:
            return 0.0, 0.0

        teammate_avg: dict[int, float] = {}
        teammate_played: dict[int, bool] = {}
        baselines: dict[int, float] = {}

        for tid in teammates:
            prior = self.recent_games_before(tid, game_date, limit=LOOKBACK_GAMES)
            metrics = calc_metrics(prior)
            if metrics is None:
                continue
            # L5 average for rotation threshold
            l5 = [
                float(g.minutes)
                for g in prior
                if getattr(g, "minutes", None) not in (None, 0)
            ][:5]
            if len(l5) < 3:
                continue
            avg_l5 = sum(l5) / len(l5)
            teammate_avg[tid] = avg_l5

            games_on_date = [
                g
                for g in self.games_by_player.get(tid, [])
                if g.game_date == game_date
                and getattr(g, "minutes", None) not in (None, 0)
            ]
            teammate_played[tid] = bool(games_on_date)

            home_game = None
            if games_on_date:
                home_game = games_on_date[0].home_game
            baselines[tid] = apply_context_adjustments(
                metrics, game_date=game_date, home_game=home_game
            )

        freed = infer_historical_freed_minutes(
            player_id=player_id,
            teammate_avg_minutes=teammate_avg,
            teammate_played=teammate_played,
        )
        # Pool = baselines of teammates who played (plus the player if present)
        pool_ids = [
            tid for tid, played in teammate_played.items() if played or tid == player_id
        ]
        if player_id in baselines and player_id not in pool_ids:
            pool_ids.append(player_id)
        pool = sum(baselines[tid] for tid in pool_ids if tid in baselines)
        return freed, pool


def load_training_context(db, season_start: date, season_end: date) -> TrainingContext:
    """Bulk-load tables used by build_features for one training window."""
    lookback_start = season_start - timedelta(days=LOOKBACK_BUFFER_DAYS)

    logger.info(
        "loading training context: games %s..%s, lines %s..%s",
        lookback_start,
        season_end,
        season_start,
        season_end,
    )

    all_games = (
        db.query(WNBARecentGames)
        .filter(WNBARecentGames.game_date >= lookback_start)
        .filter(WNBARecentGames.game_date <= season_end)
        .order_by(WNBARecentGames.game_date.asc())
        .all()
    )
    games_by_player: dict[int, list[WNBARecentGames]] = {}
    for g in all_games:
        games_by_player.setdefault(g.player_id, []).append(g)

    rosters = db.query(WNBATeamRoster).all()
    roster_by_player = {r.player_id: r for r in rosters}
    players_by_team: dict[int, list[int]] = {}
    for r in rosters:
        players_by_team.setdefault(r.team_id, []).append(r.player_id)

    offense_rows = db.query(WNBATeamOffenseStats).all()
    offense_by_team = {r.team_id: r for r in offense_rows}

    defense_rows = db.query(WNBATeamDefenseStats).all()
    defense_by_team = {r.team_id: r for r in defense_rows}

    team_name_by_player: dict[int, str] = {}
    for player_id, roster in roster_by_player.items():
        off = offense_by_team.get(roster.team_id)
        if off and off.team_name:
            team_name_by_player[player_id] = off.team_name

    lines = (
        db.query(WNBAGameLines)
        .filter(WNBAGameLines.game_date >= season_start)
        .filter(WNBAGameLines.game_date <= season_end)
        .all()
    )
    game_lines_by_date: dict[date, list[WNBAGameLines]] = {}
    for line in lines:
        game_lines_by_date.setdefault(line.game_date, []).append(line)

    logger.info(
        "training context ready: %d games, %d players, %d line dates",
        len(all_games),
        len(games_by_player),
        len(game_lines_by_date),
    )
    return TrainingContext(
        roster_by_player=roster_by_player,
        offense_by_team=offense_by_team,
        defense_by_team=defense_by_team,
        team_name_by_player=team_name_by_player,
        games_by_player=games_by_player,
        game_lines_by_date=game_lines_by_date,
        players_by_team=players_by_team,
    )
