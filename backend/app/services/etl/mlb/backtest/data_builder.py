"""Point-in-Time Historical Data Reconstructor.

Reconstructs the pre-game data snapshot for each backtest game, ensuring
no future leakage. All stats are computed from game logs up to (not
including) the game date.

REQ-BT-006 through REQ-BT-023.
"""
import logging
import math
from datetime import date, datetime, timedelta

import statsapi as mlbstatsapi

from app.services.etl.mlb.backtest.cache import cached_api_call
from app.services.etl.mlb.weather_enhanced import (
    compute_weather_run_adjustment, get_dynamic_park_factor,
    DOMED_STADIUMS, STADIUM_ALTITUDE
)
from app.services.etl.mlb.ttop import compute_ttop_adjustment
from app.services.etl.mlb.umpire_effects import get_umpire_run_adjustment, UMPIRE_RUN_ADJUSTMENTS
from app.services.etl.mlb.travel_fatigue import compute_timezone_crossing, TEAM_TIMEZONE

logger = logging.getLogger(__name__)

# Monthly average temperatures (°F) for outdoor estimation (REQ-BT-015)
MONTHLY_AVG_TEMP = {
    3: 55, 4: 62, 5: 70, 6: 78, 7: 84, 8: 82, 9: 75, 10: 65,
}

# League-average defaults (REQ-BT-008)
DEFAULT_PITCHER = {'era': 4.50, 'k9': 8.0, 'whip': 1.35, 'ip': 0, 'k': 0, 'bb': 0, 'h': 0}
DEFAULT_TEAM_HITTING = {'ops': 0.720, 'runs_per_game': 4.5}
DEFAULT_TEAM_PITCHING = {'runs_allowed_per_game': 4.5}

# Park factor map (venue name -> approximate factor)
VENUE_PARK_FACTORS = {
    'Chase Field': 1.04, 'Truist Park': 1.01, 'Oriole Park at Camden Yards': 1.05,
    'Fenway Park': 1.08, 'Wrigley Field': 1.05, 'Guaranteed Rate Field': 1.06,
    'Great American Ball Park': 1.10, 'Progressive Field': 0.98,
    'Coors Field': 1.28, 'Comerica Park': 0.97, 'Minute Maid Park': 1.02,
    'Kauffman Stadium': 0.98, 'Angel Stadium': 0.99, 'Dodger Stadium': 0.96,
    'loanDepot park': 0.96, 'American Family Field': 1.02, 'Target Field': 1.01,
    'Citi Field': 0.95, 'Yankee Stadium': 1.10, 'Oakland Coliseum': 0.93,
    'Citizens Bank Park': 1.06, 'PNC Park': 0.96, 'Petco Park': 0.94,
    'Oracle Park': 0.93, 'T-Mobile Park': 0.96, 'Busch Stadium': 0.98,
    'Tropicana Field': 0.95, 'Globe Life Field': 1.03, 'Rogers Centre': 1.01,
    'Nationals Park': 1.00,
}


class HistoricalDataBuilder:
    """Reconstructs point-in-time data for backtesting.

    All data is reconstructed from game logs and boxscores to ensure
    no future leakage (REQ-BT-006 through REQ-BT-023).
    """

    def __init__(self, cache_only=False, skip_weather=False, skip_odds=False):
        self.cache_only = cache_only
        self.skip_weather = skip_weather
        self.skip_odds = skip_odds

    def build_features(self, game):
        """Build complete feature dict for a backtest game.

        Args:
            game: BacktestGame dataclass

        Returns:
            dict matching FEATURE_COLS format, plus metadata
        """
        game_date = date.fromisoformat(game.game_date)
        season = game_date.year

        # Data quality tracking (REQ-BT-059)
        quality = {
            'pitcher_stats': False,
            'lineup': False,
            'weather': False,
            'odds': False,
        }

        # Pitcher stats reconstruction (REQ-BT-006/007/008)
        home_p = self._reconstruct_pitcher_stats(
            game.home_pitcher_id, season, game_date
        )
        away_p = self._reconstruct_pitcher_stats(
            game.away_pitcher_id, season, game_date
        )
        if home_p['ip'] > 0 or away_p['ip'] > 0:
            quality['pitcher_stats'] = True

        # Team stats reconstruction (REQ-BT-009/010)
        home_hit = self._reconstruct_team_hitting(game.home_id, season, game_date)
        away_hit = self._reconstruct_team_hitting(game.away_id, season, game_date)
        home_ra = self._reconstruct_team_pitching(game.home_id, season, game_date)
        away_ra = self._reconstruct_team_pitching(game.away_id, season, game_date)

        # Lineup reconstruction (REQ-BT-011/012)
        lineup_data = self._reconstruct_lineup(game.game_id)
        if lineup_data.get('home_lineup'):
            quality['lineup'] = True
            home_ops = lineup_data.get('home_ops', home_hit['ops'])
            away_ops = lineup_data.get('away_ops', away_hit['ops'])
        else:
            home_ops = home_hit['ops']
            away_ops = away_hit['ops']

        # Bullpen fatigue reconstruction (REQ-BT-013)
        home_fatigue = self._reconstruct_bullpen_fatigue(game.home_id, game_date)
        away_fatigue = self._reconstruct_bullpen_fatigue(game.away_id, game_date)

        # Weather reconstruction (REQ-BT-014/015/016)
        weather = self._reconstruct_weather(game.venue_name, game_date)
        quality['weather'] = not weather.get('estimated', True)

        # Park factor (REQ-BT-017)
        pf = VENUE_PARK_FACTORS.get(game.venue_name, 1.0)

        # Weather run adjustment (REQ-BT-016)
        try:
            weather_result = compute_weather_run_adjustment(
                temperature_f=weather['temperature'],
                wind_speed_mph=weather['wind_speed'],
                wind_direction_deg=weather.get('wind_direction', 225),
                humidity_pct=weather.get('humidity', 50),
                venue_name=game.venue_name,
            )
            weather_run_adj = weather_result['total_adjustment']
            dynamic_pf = get_dynamic_park_factor(game.venue_name, pf, weather_run_adj)
        except Exception:
            weather_run_adj = 0.0
            dynamic_pf = pf

        # TTOP adjustment (REQ-BT-020)
        try:
            home_ttop = compute_ttop_adjustment(game.home_pitcher_id)
            away_ttop = compute_ttop_adjustment(game.away_pitcher_id)
        except Exception:
            home_ttop = {'run_adjustment': 0.0}
            away_ttop = {'run_adjustment': 0.0}

        # Umpire adjustment (REQ-BT-021)
        umpire_adj = self._reconstruct_umpire(game.game_id)

        # Travel fatigue (REQ-BT-022)
        home_travel = self._reconstruct_travel(
            game.home_id, game.home_name, game.away_name, True, game_date
        )
        away_travel = self._reconstruct_travel(
            game.away_id, game.away_name, game.home_name, False, game_date
        )

        # Pitcher quality (REQ-BT-023)
        home_pq = self._compute_pitcher_quality(home_p)
        away_pq = self._compute_pitcher_quality(away_p)

        # Historical odds (REQ-BT-018/019)
        odds_data = {}
        if not self.skip_odds:
            odds_data = self._fetch_historical_odds(game, game_date)
            if odds_data:
                quality['odds'] = True

        # Compute data quality score (REQ-BT-059)
        quality_score = sum(0.25 for v in quality.values() if v)

        features = {
            'home_starter_era': home_p['era'],
            'away_starter_era': away_p['era'],
            'home_starter_k9': home_p['k9'],
            'away_starter_k9': away_p['k9'],
            'home_starter_whip': home_p['whip'],
            'away_starter_whip': away_p['whip'],
            'home_lineup_ops': home_ops,
            'away_lineup_ops': away_ops,
            'home_bullpen_fatigue': home_fatigue,
            'away_bullpen_fatigue': away_fatigue,
            'park_factor': dynamic_pf,
            'temperature': weather['temperature'],
            'wind_speed': weather['wind_speed'],
            'home_recent_runs_avg': home_hit['runs_per_game'],
            'away_recent_runs_avg': away_hit['runs_per_game'],
            'home_recent_runs_allowed_avg': home_ra,
            'away_recent_runs_allowed_avg': away_ra,
            'rest_differential': 0.0,
            'home_field': 1.0,
            'injury_impact_home': 0.0,
            'injury_impact_away': 0.0,
            'weather_run_adj': weather_run_adj,
            'home_ttop_adj': home_ttop['run_adjustment'],
            'away_ttop_adj': away_ttop['run_adjustment'],
            'umpire_run_adj': umpire_adj,
            'home_travel_adj': home_travel,
            'away_travel_adj': away_travel,
            'home_pitcher_quality': home_pq,
            'away_pitcher_quality': away_pq,
        }

        metadata = {
            'data_quality_score': quality_score,
            'used_estimated_weather': weather.get('estimated', True),
            'had_historical_odds': bool(odds_data),
            'pitcher_stats_available': quality['pitcher_stats'],
            'odds_data': odds_data,
            'home_pitcher_stats': home_p,
            'away_pitcher_stats': away_p,
            'lineup_data': lineup_data,
        }

        return features, metadata

    def _reconstruct_pitcher_stats(self, pitcher_id, season, game_date):
        """Reconstruct pitcher stats from game logs up to game_date (REQ-BT-006/007)."""
        if not pitcher_id:
            return dict(DEFAULT_PITCHER)

        def _fetch():
            return mlbstatsapi.player_stat_data(
                pitcher_id, group='pitching', type='gameLog',
                season=str(season)
            )

        data = cached_api_call(
            'player_game_log', {'id': pitcher_id, 'season': season, 'group': 'pitching'},
            _fetch, cache_only=self.cache_only
        )

        if not data:
            return dict(DEFAULT_PITCHER)

        # Parse game logs and filter to pre-game-date
        logs = []
        if isinstance(data, dict):
            stats_list = data.get('stats', [])
            if isinstance(stats_list, list):
                for entry in stats_list:
                    s = entry.get('stats', {}) if isinstance(entry, dict) else {}
                    log_date = entry.get('date', '')
                    if not log_date or log_date >= game_date.isoformat():
                        continue  # Skip future games (point-in-time correctness)
                    ip_str = s.get('inningsPitched', '0') or '0'
                    ip = float(ip_str)
                    if ip <= 0:
                        continue
                    logs.append({
                        'date': log_date,
                        'ip': ip,
                        'er': int(s.get('earnedRuns', 0) or 0),
                        'k': int(s.get('strikeOuts', 0) or 0),
                        'bb': int(s.get('baseOnBalls', 0) or 0),
                        'h': int(s.get('hits', 0) or 0),
                    })

        if not logs:
            # No prior starts this season — try prior season (REQ-BT-007)
            if season > 2020:
                prior = self._reconstruct_pitcher_stats(pitcher_id, season - 1, date(season, 1, 1))
                # Apply Bayesian shrinkage toward league average (τ=3)
                tau = 3.0
                n = len(logs) if logs else 0
                w = n / (n + tau)
                prior['era'] = w * prior['era'] + (1 - w) * 4.50
                prior['k9'] = w * prior['k9'] + (1 - w) * 8.0
                prior['whip'] = w * prior['whip'] + (1 - w) * 1.35
                return prior
            return dict(DEFAULT_PITCHER)

        # Compute aggregates from game logs
        total_ip = sum(l['ip'] for l in logs)
        total_er = sum(l['er'] for l in logs)
        total_k = sum(l['k'] for l in logs)
        total_bb = sum(l['bb'] for l in logs)
        total_h = sum(l['h'] for l in logs)

        era = (total_er / max(total_ip, 0.1)) * 9.0
        k9 = (total_k / max(total_ip, 0.1)) * 9.0
        whip = (total_bb + total_h) / max(total_ip, 0.1)

        # Last-5-starts K/9 (REQ-BT-006)
        last5 = sorted(logs, key=lambda x: x['date'], reverse=True)[:5]
        last5_ip = sum(l['ip'] for l in last5)
        last5_k = sum(l['k'] for l in last5)
        last5_k9 = (last5_k / max(last5_ip, 0.1)) * 9.0

        # Bayesian shrinkage for pitchers with < 3 starts (REQ-BT-007)
        if len(logs) < 3:
            tau = 3.0
            w = len(logs) / (len(logs) + tau)
            era = w * era + (1 - w) * 4.50
            k9 = w * k9 + (1 - w) * 8.0
            whip = w * whip + (1 - w) * 1.35

        return {
            'era': round(era, 2),
            'k9': round(k9, 2),
            'whip': round(whip, 3),
            'ip': round(total_ip, 1),
            'k': total_k,
            'bb': total_bb,
            'h': total_h,
            'n_starts': len(logs),
            'last5_k9': round(last5_k9, 2),
        }

    def _reconstruct_team_hitting(self, team_id, season, game_date):
        """Reconstruct team hitting stats as of game_date (REQ-BT-009/010)."""
        def _fetch():
            return mlbstatsapi.schedule(
                start_date=f'{season}-03-20',
                end_date=(game_date - timedelta(days=1)).strftime('%Y-%m-%d'),
                team=team_id
            )

        games = cached_api_call(
            'team_schedule', {'team': team_id, 'season': season, 'before': game_date.isoformat()},
            _fetch, cache_only=self.cache_only
        )

        if not games:
            return dict(DEFAULT_TEAM_HITTING)

        # Sum runs scored from completed games
        total_runs = 0
        n_games = 0
        for g in games:
            if g.get('status') not in ('Final', 'Game Over', 'Completed Early'):
                continue
            gd = g.get('game_date', '')[:10]
            if gd >= game_date.isoformat():
                continue  # Point-in-time filter
            if g.get('home_id') == team_id:
                total_runs += int(g.get('home_score', 0) or 0)
            else:
                total_runs += int(g.get('away_score', 0) or 0)
            n_games += 1

        if n_games == 0:
            return dict(DEFAULT_TEAM_HITTING)

        runs_pg = total_runs / n_games

        # Estimate OPS from runs/game (rough correlation)
        ops_est = 0.650 + (runs_pg - 3.5) * 0.025
        ops_est = max(0.600, min(0.850, ops_est))

        # Early-season blending (REQ-BT-010)
        if n_games < 10:
            prior_rpg = 4.5
            prior_ops = 0.720
            blended_rpg = (runs_pg * n_games + prior_rpg * 20) / (n_games + 20)
            blended_ops = (ops_est * n_games + prior_ops * 20) / (n_games + 20)
            return {'ops': round(blended_ops, 3), 'runs_per_game': round(blended_rpg, 2)}

        return {'ops': round(ops_est, 3), 'runs_per_game': round(runs_pg, 2)}

    def _reconstruct_team_pitching(self, team_id, season, game_date):
        """Reconstruct team pitching stats (runs allowed/game) as of game_date (REQ-BT-009)."""
        def _fetch():
            return mlbstatsapi.schedule(
                start_date=f'{season}-03-20',
                end_date=(game_date - timedelta(days=1)).strftime('%Y-%m-%d'),
                team=team_id
            )

        games = cached_api_call(
            'team_schedule', {'team': team_id, 'season': season, 'before': game_date.isoformat()},
            _fetch, cache_only=self.cache_only
        )

        if not games:
            return DEFAULT_TEAM_PITCHING['runs_allowed_per_game']

        total_ra = 0
        n_games = 0
        for g in games:
            if g.get('status') not in ('Final', 'Game Over', 'Completed Early'):
                continue
            gd = g.get('game_date', '')[:10]
            if gd >= game_date.isoformat():
                continue
            if g.get('home_id') == team_id:
                total_ra += int(g.get('away_score', 0) or 0)
            else:
                total_ra += int(g.get('home_score', 0) or 0)
            n_games += 1

        if n_games == 0:
            return DEFAULT_TEAM_PITCHING['runs_allowed_per_game']

        ra_pg = total_ra / n_games

        # Early-season blending
        if n_games < 10:
            ra_pg = (ra_pg * n_games + 4.5 * 20) / (n_games + 20)

        return round(ra_pg, 2)

    def _reconstruct_lineup(self, game_id):
        """Reconstruct actual lineup from boxscore (REQ-BT-011/012)."""
        def _fetch():
            return mlbstatsapi.boxscore_data(game_id)

        data = cached_api_call(
            'boxscore', {'game_id': game_id},
            _fetch, cache_only=self.cache_only
        )

        if not data:
            return {}

        result = {'home_lineup': [], 'away_lineup': []}

        try:
            for side in ('home', 'away'):
                key = f'{side}Batters'
                batters = data.get(key, [])
                lineup = []
                for batter_id in batters:
                    if isinstance(batter_id, int):
                        lineup.append(batter_id)
                    elif isinstance(batter_id, str) and batter_id.isdigit():
                        lineup.append(int(batter_id))
                result[f'{side}_lineup'] = lineup[:9]  # Top 9 batters
        except Exception:
            pass

        return result

    def _reconstruct_bullpen_fatigue(self, team_id, game_date):
        """Reconstruct bullpen fatigue from prior 7 days (REQ-BT-013)."""
        # Simplified: estimate from game schedule density
        start = game_date - timedelta(days=7)

        def _fetch():
            return mlbstatsapi.schedule(
                start_date=start.strftime('%Y-%m-%d'),
                end_date=(game_date - timedelta(days=1)).strftime('%Y-%m-%d'),
                team=team_id
            )

        games = cached_api_call(
            'team_7day', {'team': team_id, 'before': game_date.isoformat()},
            _fetch, cache_only=self.cache_only
        )

        if not games:
            return 0.5  # League average

        # Count games in last 3, 5, 7 days
        n3 = n5 = n7 = 0
        for g in games:
            if g.get('status') not in ('Final', 'Game Over', 'Completed Early'):
                continue
            gd = g.get('game_date', '')[:10]
            if gd >= game_date.isoformat():
                continue
            gd_date = date.fromisoformat(gd)
            days_ago = (game_date - gd_date).days
            if days_ago <= 3:
                n3 += 1
            if days_ago <= 5:
                n5 += 1
            if days_ago <= 7:
                n7 += 1

        # Estimate bullpen IP from games (avg ~3 IP relief per game)
        ip3 = n3 * 3.0
        ip5 = n5 * 3.0
        ip7 = n7 * 3.0

        # Same formula as bullpen_fatigue.py
        from app.services.etl.mlb.bullpen_fatigue import W_3DAY, W_5DAY, W_7DAY, AVG_BP_IP_3DAY, AVG_BP_IP_5DAY, AVG_BP_IP_7DAY
        weighted = (
            W_3DAY * (ip3 / (AVG_BP_IP_3DAY * 2.0)) +
            W_5DAY * (ip5 / (AVG_BP_IP_5DAY * 2.0)) +
            W_7DAY * (ip7 / (AVG_BP_IP_7DAY * 2.0))
        )
        fatigue = max(0.0, min(1.0, weighted))
        return round(fatigue, 3)

    def _reconstruct_weather(self, venue_name, game_date):
        """Reconstruct weather data (REQ-BT-014/015)."""
        # Domed stadiums get neutral defaults (REQ-BT-014)
        if venue_name in DOMED_STADIUMS:
            return {
                'temperature': 72.0,
                'wind_speed': 0.0,
                'wind_direction': 0,
                'humidity': 50,
                'estimated': False,  # Known controlled environment
            }

        if self.skip_weather:
            month = game_date.month
            return {
                'temperature': float(MONTHLY_AVG_TEMP.get(month, 72)),
                'wind_speed': 8.0,
                'humidity': 55,
                'wind_direction': 225,
                'estimated': True,
            }

        # For outdoor stadiums, use monthly average estimation (REQ-BT-015)
        month = game_date.month
        return {
            'temperature': float(MONTHLY_AVG_TEMP.get(month, 72)),
            'wind_speed': 8.0,
            'humidity': 55,
            'wind_direction': 225,
            'estimated': True,
        }

    def _reconstruct_umpire(self, game_id):
        """Reconstruct umpire run adjustment from boxscore (REQ-BT-021)."""
        def _fetch():
            try:
                return mlbstatsapi.get('game', {'gamePk': game_id})
            except Exception:
                return None

        data = cached_api_call(
            'game_data', {'game_id': game_id},
            _fetch, cache_only=self.cache_only
        )

        if not data:
            return 0.0

        try:
            officials = data.get('liveData', {}).get('boxscore', {}).get('officials', [])
            for official in officials:
                if official.get('officialType') == 'Home Plate':
                    name = official.get('official', {}).get('fullName', '')
                    if name:
                        return get_umpire_run_adjustment(umpire_name=name)
        except Exception:
            pass

        return 0.0

    def _reconstruct_travel(self, team_id, team_name, opponent_name, is_home, game_date):
        """Reconstruct travel fatigue (REQ-BT-022)."""
        # Get schedule for prior 3 days to determine travel
        start = game_date - timedelta(days=5)

        def _fetch():
            return mlbstatsapi.schedule(
                start_date=start.strftime('%Y-%m-%d'),
                end_date=(game_date - timedelta(days=1)).strftime('%Y-%m-%d'),
                team=team_id
            )

        games = cached_api_call(
            'team_travel', {'team': team_id, 'before': game_date.isoformat()},
            _fetch, cache_only=self.cache_only
        )

        if not games:
            return 0.0

        # Find most recent game before this one
        prev_game = None
        for g in sorted(games, key=lambda x: x.get('game_date', ''), reverse=True):
            gd = g.get('game_date', '')[:10]
            if gd < game_date.isoformat():
                prev_game = g
                break

        if not prev_game:
            return 0.0

        # Determine previous game location
        prev_was_home = (prev_game.get('home_id') == team_id)
        prev_city_team = team_name if prev_was_home else prev_game.get('home_name', '')
        current_city_team = team_name if is_home else opponent_name

        tz_diff = compute_timezone_crossing(prev_city_team, current_city_team)

        # Only eastward travel of 2+ zones matters (per research)
        if tz_diff >= 2:
            return round(min(tz_diff * 0.10, 0.30), 3)
        return 0.0

    def _compute_pitcher_quality(self, pitcher_stats):
        """Compute pitcher quality score from reconstructed stats (REQ-BT-023)."""
        k9 = pitcher_stats.get('k9', 8.0)
        # K/9-based proxy: quality = min(100, max(0, (k9 - 5.0) * 12.5))
        quality = min(100, max(0, (k9 - 5.0) * 12.5))
        return round(quality, 1)

    def _fetch_historical_odds(self, game, game_date):
        """Fetch historical odds from The Odds API (REQ-BT-018/019)."""
        import os
        api_key = os.getenv('ODDS_API_KEY')
        if not api_key or self.skip_odds:
            return {}

        import requests

        def _fetch():
            try:
                url = f"https://api.the-odds-api.com/v4/historical/sports/baseball_mlb/odds/"
                params = {
                    'apiKey': api_key,
                    'regions': 'us',
                    'markets': 'h2h,totals',
                    'bookmakers': 'fanduel',
                    'date': f'{game_date.isoformat()}T12:00:00Z',
                }
                resp = requests.get(url, params=params, timeout=15)
                if resp.status_code == 200:
                    return resp.json()
            except Exception:
                pass
            return None

        data = cached_api_call(
            'historical_odds', {'date': game_date.isoformat()},
            _fetch, cache_only=self.cache_only
        )

        if not data:
            return {}

        # Find matching game in odds data
        events = data.get('data', []) if isinstance(data, dict) else data
        if not isinstance(events, list):
            return {}

        for event in events:
            home = event.get('home_team', '')
            away = event.get('away_team', '')
            if (game.home_name in home or home in game.home_name) and \
               (game.away_name in away or away in game.away_name):
                odds_result = {'h2h': {}, 'totals': {}}
                for bm in event.get('bookmakers', []):
                    for market in bm.get('markets', []):
                        if market.get('key') == 'h2h':
                            for o in market.get('outcomes', []):
                                odds_result['h2h'][o['name']] = o['price']
                        elif market.get('key') == 'totals':
                            for o in market.get('outcomes', []):
                                if o['name'] == 'Over':
                                    odds_result['totals']['point'] = o.get('point')
                                    odds_result['totals']['over'] = o['price']
                                elif o['name'] == 'Under':
                                    odds_result['totals']['under'] = o['price']
                return odds_result

        return {}
