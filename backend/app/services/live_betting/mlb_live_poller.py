"""
MLBLivePoller: fetches MLB live game feeds and dispatches plays to the
PlayEventListener.

Originally an asyncio loop driven by a Discord bot (YetiBets). Ported to YetAI
in Development-9gk: the continuous polling loop is gone — a Celery Beat schedule
calls `tick()` every 20s instead. State that previously lived in the loop
(last_play_index per game, today's schedule cache) is held on the singleton
instance, which the worker process keeps alive between ticks.
"""

import asyncio
import logging
from datetime import date
from typing import Dict, Optional

import aiohttp
import pytz

from app.services.live_betting.play_event_listener import PlayEventListener
from app.services.live_betting.prop_watchlist import PropWatchlist

logger = logging.getLogger('mlb_live_poller')

ET = pytz.timezone('US/Eastern')

MLB_SCHEDULE_URL = 'https://statsapi.mlb.com/api/v1/schedule'
MLB_LIVE_FEED_URL = 'https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live'


class MLBLivePoller:
    """
    Polls MLB Stats API for live game data and feeds plays to the listener.

    Usage from a Celery task:
        poller = get_poller()       # module-level singleton
        asyncio.run(poller.tick())  # one polling cycle
    """

    def __init__(self, watchlist: PropWatchlist, listener: PlayEventListener,
                 alert_callback=None):
        self.watchlist = watchlist
        self.listener = listener
        self.alert_callback = alert_callback  # async fn(List[PropEvent])
        # Track last-seen play index per game to avoid re-processing
        self._last_play_index: Dict[int, int] = {}
        # Cache today's schedule
        self._todays_games: Dict[int, dict] = {}
        self._schedule_date: Optional[date] = None

    async def tick(self):
        """Single polling cycle. Called by the Celery beat schedule every 20s.
        Creates a fresh aiohttp session per tick (sessions don't survive between
        Celery tasks reliably)."""
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            self._session = session
            try:
                await self._poll_cycle()
            except Exception:
                logger.exception("Error in poll cycle")
            finally:
                self._session = None

    async def _poll_cycle(self):
        """Single poll cycle: refresh schedule if needed, poll active games."""
        today = date.today()

        # Refresh schedule once per day or on first run
        if self._schedule_date != today:
            await self._fetch_schedule(today)
            self._schedule_date = today

        # Only poll games that have active prop bets
        active_game_pks = self.watchlist.active_game_pks
        if not active_game_pks:
            return

        # Poll each active game concurrently
        tasks = []
        for game_pk in active_game_pks:
            tasks.append(self._poll_game(game_pk))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _fetch_schedule(self, game_date: date):
        """Fetch today's MLB schedule for reference."""
        try:
            params = {
                'sportId': 1,
                'date': game_date.strftime('%Y-%m-%d'),
            }
            async with self._session.get(MLB_SCHEDULE_URL, params=params) as resp:
                if resp.status != 200:
                    logger.warning(f"Schedule fetch failed: HTTP {resp.status}")
                    return
                data = await resp.json()

            self._todays_games.clear()
            for game_date_info in data.get('dates', []):
                for game in game_date_info.get('games', []):
                    gpk = game.get('gamePk')
                    if gpk:
                        self._todays_games[gpk] = {
                            'status': game.get('status', {}).get('abstractGameState', ''),
                            'away': game.get('teams', {}).get('away', {}).get('team', {}).get('name', ''),
                            'home': game.get('teams', {}).get('home', {}).get('team', {}).get('name', ''),
                        }
            logger.info(f"Loaded {len(self._todays_games)} games for {game_date}")
        except Exception:
            logger.exception("Failed to fetch MLB schedule")

    async def _poll_game(self, game_pk: int):
        """Fetch live feed for a single game and process new plays."""
        try:
            url = MLB_LIVE_FEED_URL.format(game_pk=game_pk)
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Game {game_pk} feed failed: HTTP {resp.status}")
                    return
                data = await resp.json()

            game_data = data.get('gameData', {})
            status = game_data.get('status', {}).get('abstractGameState', '')

            # Skip games that haven't started or are already final
            if status == 'Preview':
                return
            if status == 'Final':
                # Process any remaining plays, then clean up
                pass

            # Get all plays
            live_data = data.get('liveData', {})
            plays = live_data.get('plays', {})
            all_plays = plays.get('allPlays', [])

            if not all_plays:
                return

            # Only process plays we haven't seen
            last_index = self._last_play_index.get(game_pk, -1)
            new_plays = [p for p in all_plays
                         if p.get('about', {}).get('atBatIndex', -1) > last_index]

            all_events = []
            for play in new_plays:
                events = self.listener.on_play(game_pk, play)
                all_events.extend(events)
                play_idx = play.get('about', {}).get('atBatIndex', -1)
                if play_idx > last_index:
                    last_index = play_idx

            self._last_play_index[game_pk] = last_index

            # Send alerts
            if all_events and self.alert_callback:
                await self.alert_callback(all_events)

            # Clean up finished games
            if status == 'Final':
                self._last_play_index.pop(game_pk, None)
                logger.info(f"Game {game_pk} final, cleaned up tracking state")

        except asyncio.TimeoutError:
            logger.warning(f"Timeout polling game {game_pk}")
        except Exception:
            logger.exception(f"Error polling game {game_pk}")
