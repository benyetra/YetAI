"""Game Sampler for Backtesting.

Selects random historical games from MLB-StatsAPI schedules with filtering,
seeded RNG for reproducibility, and multiple sampling modes.

REQ-BT-001 through REQ-BT-005.
"""
import logging
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

import statsapi as mlbstatsapi

from app.services.etl.mlb.backtest.cache import cached_api_call

logger = logging.getLogger(__name__)

# Games to exclude from backtesting
EXCLUDED_GAME_TYPES = {'S', 'E', 'A'}  # Spring Training, Exhibition, All-Star


@dataclass
class BacktestGame:
    """Represents a single game selected for backtesting (REQ-BT-004)."""
    game_id: int
    game_date: str  # YYYY-MM-DD
    home_name: str
    away_name: str
    home_id: int
    away_id: int
    home_pitcher_name: str = ''
    home_pitcher_id: Optional[int] = None
    away_pitcher_name: str = ''
    away_pitcher_id: Optional[int] = None
    venue_name: str = ''
    home_score: int = 0
    away_score: int = 0
    game_type: str = 'R'  # R=Regular, P=Postseason


class BacktestSampler:
    """Samples random games from historical MLB schedules.

    REQ-BT-001: Accepts date range, sample size, seed, and filters.
    REQ-BT-002: Fetches schedule, filters to Final games, excludes ASG/ST.
    REQ-BT-003: Seeded random sampling for reproducibility.
    """

    def __init__(self, start_date, end_date, n_games=100, seed=42,
                 team=None, month=None, venue=None, day_of_week=None,
                 include_postseason=False, cache_only=False):
        self.start_date = start_date
        self.end_date = end_date
        self.n_games = n_games
        self.seed = seed
        self.team = team
        self.month = month
        self.venue = venue
        self.day_of_week = day_of_week
        self.include_postseason = include_postseason
        self.cache_only = cache_only
        self.rng = random.Random(seed)

    def fetch_schedule(self) -> List[dict]:
        """Fetch all games in the date range from MLB-StatsAPI (REQ-BT-002)."""
        all_games = []

        # Fetch in monthly chunks to avoid API timeouts
        current = self.start_date
        while current <= self.end_date:
            chunk_end = min(
                date(current.year, current.month + 1, 1) - timedelta(days=1)
                if current.month < 12 else date(current.year, 12, 31),
                self.end_date
            )

            start_str = current.strftime('%Y-%m-%d')
            end_str = chunk_end.strftime('%Y-%m-%d')

            def _fetch(s=start_str, e=end_str):
                return mlbstatsapi.schedule(start_date=s, end_date=e)

            games = cached_api_call(
                'schedule', {'start': start_str, 'end': end_str},
                _fetch, cache_only=self.cache_only
            )

            if games:
                all_games.extend(games)

            # Move to next month
            if current.month < 12:
                current = date(current.year, current.month + 1, 1)
            else:
                current = date(current.year + 1, 1, 1)

        logger.info(f"Fetched {len(all_games)} total games from schedule")
        return all_games

    def filter_games(self, games) -> List[dict]:
        """Apply filters to the game list (REQ-BT-002)."""
        filtered = []

        for g in games:
            # Must be Final
            if g.get('status') not in ('Final', 'Game Over', 'Completed Early'):
                continue

            # Exclude spring training, exhibitions, all-star
            game_type = g.get('game_type', 'R')
            if game_type in EXCLUDED_GAME_TYPES:
                continue

            # Exclude postseason unless flag set
            if game_type in ('D', 'L', 'W', 'F') and not self.include_postseason:
                continue

            # Team filter
            if self.team:
                team_lower = self.team.lower()
                if (team_lower not in g.get('home_name', '').lower() and
                        team_lower not in g.get('away_name', '').lower()):
                    continue

            # Month filter
            if self.month:
                game_date = g.get('game_date', '')[:10]
                if game_date:
                    gm = int(game_date[5:7])
                    if gm != self.month:
                        continue

            # Day of week filter
            if self.day_of_week is not None:
                game_date = g.get('game_date', '')[:10]
                if game_date:
                    from datetime import datetime
                    gd = datetime.strptime(game_date, '%Y-%m-%d')
                    if gd.weekday() != self.day_of_week:
                        continue

            # Venue filter
            if self.venue:
                venue_lower = self.venue.lower()
                venue_name = g.get('venue_name', '') or ''
                if venue_lower not in venue_name.lower():
                    continue

            filtered.append(g)

        logger.info(f"Filtered to {len(filtered)} eligible games")
        return filtered

    def _game_to_backtest_game(self, g) -> BacktestGame:
        """Convert a schedule dict to a BacktestGame dataclass (REQ-BT-004)."""
        return BacktestGame(
            game_id=g['game_id'],
            game_date=g.get('game_date', '')[:10],
            home_name=g.get('home_name', ''),
            away_name=g.get('away_name', ''),
            home_id=g.get('home_id', 0),
            away_id=g.get('away_id', 0),
            home_pitcher_name=g.get('home_probable_pitcher', ''),
            home_pitcher_id=g.get('home_probable_pitcher_id'),
            away_pitcher_name=g.get('away_probable_pitcher', ''),
            away_pitcher_id=g.get('away_probable_pitcher_id'),
            venue_name=g.get('venue_name', ''),
            home_score=int(g.get('home_score', 0) or 0),
            away_score=int(g.get('away_score', 0) or 0),
            game_type=g.get('game_type', 'R'),
        )

    def sample_games(self) -> List[BacktestGame]:
        """Sample random games (REQ-BT-003)."""
        games = self.fetch_schedule()
        filtered = self.filter_games(games)

        if not filtered:
            logger.warning("No games match the specified filters")
            return []

        # Sample with seeded RNG
        if self.n_games >= len(filtered):
            logger.warning(
                f"Requested {self.n_games} games but only {len(filtered)} available. "
                f"Using all {len(filtered)} games."
            )
            sampled = filtered
        else:
            sampled = self.rng.sample(filtered, self.n_games)

        result = [self._game_to_backtest_game(g) for g in sampled]
        logger.info(f"Sampled {len(result)} games for backtesting")
        return result

    def sample_full_season(self) -> List[BacktestGame]:
        """Backtest every game in the range (REQ-BT-005 --full-season)."""
        games = self.fetch_schedule()
        filtered = self.filter_games(games)
        result = [self._game_to_backtest_game(g) for g in filtered]
        logger.info(f"Full season: {len(result)} games for backtesting")
        return result

    def sample_random_dates(self, n_dates=10) -> List[BacktestGame]:
        """Pick N random dates, backtest all games on each (REQ-BT-005 --random-dates)."""
        games = self.fetch_schedule()
        filtered = self.filter_games(games)

        # Group by date
        by_date = {}
        for g in filtered:
            gd = g.get('game_date', '')[:10]
            if gd:
                by_date.setdefault(gd, []).append(g)

        available_dates = list(by_date.keys())
        if n_dates >= len(available_dates):
            selected_dates = available_dates
        else:
            selected_dates = self.rng.sample(available_dates, n_dates)

        result = []
        for d in sorted(selected_dates):
            for g in by_date[d]:
                result.append(self._game_to_backtest_game(g))

        logger.info(f"Random dates: {len(selected_dates)} dates, {len(result)} games")
        return result
