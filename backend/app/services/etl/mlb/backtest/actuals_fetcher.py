"""Actuals Fetcher for Backtesting.

Pulls actual game results from MLB-StatsAPI boxscores for comparison
against predictions.

REQ-BT-031 through REQ-BT-034.
"""

import logging

import statsapi as mlbstatsapi

from app.services.etl.mlb.backtest.cache import cached_api_call

logger = logging.getLogger(__name__)


class BacktestActualsFetcher:
    """Fetches actual game outcomes for backtest comparison.

    REQ-BT-031: Final scores from boxscore.
    REQ-BT-032: Pitcher strikeouts and IP.
    REQ-BT-033: Batter hits and at-bats.
    REQ-BT-034: Home runs from boxscore.
    """

    def __init__(self, cache_only=False):
        self.cache_only = cache_only

    def fetch_game_actuals(self, game):
        """Fetch complete actuals for a game (REQ-BT-031).

        Args:
            game: BacktestGame dataclass (already has home_score/away_score)

        Returns:
            dict with actual outcomes
        """
        result = {
            "home_score": game.home_score,
            "away_score": game.away_score,
            "actual_total": game.home_score + game.away_score,
            "actual_winner": "home" if game.home_score > game.away_score else "away",
            "run_margin": abs(game.home_score - game.away_score),
        }

        # Fetch detailed boxscore for K/hit/HR data
        boxscore = self._fetch_boxscore(game.game_id)
        if boxscore:
            result.update(self._extract_pitcher_actuals(boxscore, game))
            result.update(self._extract_batter_actuals(boxscore, game))
            result.update(self._extract_hr_actuals(boxscore, game))

        return result

    def _fetch_boxscore(self, game_id):
        """Fetch boxscore data with caching."""

        def _fetch():
            return mlbstatsapi.boxscore_data(game_id)

        return cached_api_call(
            "boxscore", {"game_id": game_id}, _fetch, cache_only=self.cache_only
        )

    def _extract_pitcher_actuals(self, boxscore, game):
        """Extract starting pitcher K and IP from boxscore (REQ-BT-032)."""
        result = {}

        for side in ("home", "away"):
            try:
                pitchers_key = f"{side}Pitchers"
                pitchers = boxscore.get(pitchers_key, [])

                if not pitchers:
                    continue

                # First pitcher entry is typically the starter
                # Skip non-numeric entries (headers, totals)
                starter_found = False
                for entry in pitchers:
                    if isinstance(entry, dict):
                        stats = entry
                    elif isinstance(entry, int) or (
                        isinstance(entry, str) and entry.isdigit()
                    ):
                        pid = int(entry) if isinstance(entry, str) else entry
                        # Look up in player stats
                        player_key = f"ID{pid}"
                        stats = boxscore.get(player_key, {})
                    else:
                        continue

                    if not stats or not isinstance(stats, dict):
                        continue

                    # Get pitcher stats from the boxscore
                    ip_str = stats.get("ip", "0") or "0"
                    k = stats.get("k", 0) or stats.get("so", 0) or 0

                    try:
                        ip = float(ip_str)
                    except (ValueError, TypeError):
                        ip = 0.0

                    if ip > 0 and not starter_found:
                        result[f"{side}_actual_k"] = int(k)
                        result[f"{side}_actual_ip"] = ip
                        starter_found = True
                        break
            except Exception as e:
                logger.debug(f"Error extracting {side} pitcher actuals: {e}")

        return result

    def _extract_batter_actuals(self, boxscore, game):
        """Extract batter hits from boxscore (REQ-BT-033)."""
        result = {}

        for side in ("home", "away"):
            total_hits = 0
            total_ab = 0
            try:
                batters_key = f"{side}Batters"
                batters = boxscore.get(batters_key, [])

                for entry in batters:
                    if isinstance(entry, dict):
                        h = int(entry.get("h", 0) or 0)
                        ab = int(entry.get("ab", 0) or 0)
                        total_hits += h
                        total_ab += ab
                    elif isinstance(entry, int) or (
                        isinstance(entry, str) and entry.isdigit()
                    ):
                        pid = int(entry) if isinstance(entry, str) else entry
                        player_key = f"ID{pid}"
                        stats = boxscore.get(player_key, {})
                        if isinstance(stats, dict):
                            total_hits += int(stats.get("h", 0) or 0)
                            total_ab += int(stats.get("ab", 0) or 0)
            except Exception:
                pass

            result[f"{side}_actual_hits"] = total_hits
            result[f"{side}_actual_ab"] = total_ab

        return result

    def _extract_hr_actuals(self, boxscore, game):
        """Extract home runs from boxscore (REQ-BT-034)."""
        result = {}

        for side in ("home", "away"):
            total_hr = 0
            hr_batters = []
            try:
                batters_key = f"{side}Batters"
                batters = boxscore.get(batters_key, [])

                for entry in batters:
                    if isinstance(entry, dict):
                        hr = int(entry.get("hr", 0) or 0)
                        total_hr += hr
                        if hr > 0:
                            hr_batters.append(
                                {
                                    "name": entry.get("name", ""),
                                    "hr": hr,
                                }
                            )
                    elif isinstance(entry, int) or (
                        isinstance(entry, str) and entry.isdigit()
                    ):
                        pid = int(entry) if isinstance(entry, str) else entry
                        player_key = f"ID{pid}"
                        stats = boxscore.get(player_key, {})
                        if isinstance(stats, dict):
                            hr = int(stats.get("hr", 0) or 0)
                            total_hr += hr
                            if hr > 0:
                                hr_batters.append(
                                    {
                                        "id": pid,
                                        "name": stats.get("name", ""),
                                        "hr": hr,
                                    }
                                )
            except Exception:
                pass

            result[f"{side}_actual_hr"] = total_hr
            result[f"{side}_hr_batters"] = hr_batters

        result["total_actual_hr"] = result.get("home_actual_hr", 0) + result.get(
            "away_actual_hr", 0
        )

        return result
