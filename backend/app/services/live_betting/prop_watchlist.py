"""
PropWatchlist: in-memory index of active player prop picks keyed by
(game_pk, player_id, stat_key) for O(1) lookup on each play.

Populated from pikkit_bets/pikkit_picks tables on startup and
kept in sync via add_pick / remove_bet.
"""

import logging
import re
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger('prop_watchlist')

# Type alias for the watchlist key
WatchKey = Tuple[int, int, str]  # (game_pk, player_id, stat_key)


class PickInfo:
    """Lightweight struct holding everything the alerter needs about a pick."""
    __slots__ = (
        'pick_id', 'bet_id', 'player_id', 'player_name', 'game_pk',
        'stat_key', 'side', 'line', 'bet_type', 'stake', 'odds',
        'potential_payout', 'leg_index', 'total_legs',
    )

    def __init__(self, *, pick_id, bet_id, player_id, player_name, game_pk,
                 stat_key, side, line, bet_type='straight', stake=None,
                 odds=None, potential_payout=None, leg_index=None,
                 total_legs=None):
        self.pick_id = pick_id
        self.bet_id = bet_id
        self.player_id = player_id
        self.player_name = player_name
        self.game_pk = game_pk
        self.stat_key = stat_key
        self.side = side            # 'over' or 'under'
        self.line = line            # e.g. 0.5, 1.5
        self.bet_type = bet_type    # 'straight' or 'parlay'
        self.stake = stake
        self.odds = odds
        self.potential_payout = potential_payout
        self.leg_index = leg_index
        self.total_legs = total_legs

    def __repr__(self):
        return f"<PickInfo {self.pick_id} {self.player_name} {self.side} {self.line} {self.stat_key}>"


def _parse_line_and_side(pick_name: str) -> Tuple[Optional[str], Optional[float]]:
    """
    Parse 'Over 1.5' or 'Under 0.5' from a pick_name string.
    Returns (side, line) or (None, None) if unparseable.
    """
    match = re.search(r'(over|under)\s+(\d+\.?\d*)', pick_name, re.IGNORECASE)
    if match:
        return match.group(1).lower(), float(match.group(2))
    return None, None


class PropWatchlist:
    """Thread-safe in-memory index of active player-prop picks."""

    def __init__(self):
        # {(game_pk, player_id, stat_key) -> [PickInfo]}
        self._index: Dict[WatchKey, List[PickInfo]] = defaultdict(list)
        # {bet_id -> set of keys} for fast removal
        self._bet_keys: Dict[str, Set[WatchKey]] = defaultdict(set)
        # Set of all game_pks with active picks
        self._active_games: Set[int] = set()

    @property
    def size(self) -> int:
        return sum(len(v) for v in self._index.values())

    def __len__(self) -> int:
        return self.size

    @property
    def active_game_pks(self) -> Set[int]:
        return set(self._active_games)

    def load_from_db(self) -> int:
        """Convenience: open a YetAI session and rebuild the watchlist.

        Used by the Celery refresh task. Equivalent to `sync_from_db(session)`
        but the caller doesn't have to manage the session lifecycle.
        """
        from app.core.database import SessionLocal
        with SessionLocal() as session:
            return self.sync_from_db(session)

    def lookup(self, game_pk: int, player_id: int, stat_key: str) -> List[PickInfo]:
        """Return all picks matching this game/player/stat combination."""
        return self._index.get((game_pk, player_id, stat_key), [])

    def add_pick(self, pick: PickInfo) -> None:
        key = (pick.game_pk, pick.player_id, pick.stat_key)
        # Avoid duplicates
        existing_ids = {p.pick_id for p in self._index[key]}
        if pick.pick_id not in existing_ids:
            self._index[key].append(pick)
            self._bet_keys[pick.bet_id].add(key)
            self._active_games.add(pick.game_pk)
            logger.info(f"Watchlist added: {pick}")

    def remove_bet(self, bet_id: str) -> None:
        """Remove all picks for a bet (e.g., when bet settles)."""
        keys = self._bet_keys.pop(bet_id, set())
        for key in keys:
            picks = self._index.get(key, [])
            self._index[key] = [p for p in picks if p.bet_id != bet_id]
            if not self._index[key]:
                del self._index[key]
        # Rebuild active games
        self._active_games = {k[0] for k in self._index}
        logger.info(f"Watchlist removed bet {bet_id}, {len(keys)} keys cleared")

    def clear(self) -> None:
        self._index.clear()
        self._bet_keys.clear()
        self._active_games.clear()

    def sync_from_db(self, db_session) -> int:
        """
        Rebuild watchlist from pikkit_bets + pikkit_picks tables.
        Returns the number of picks loaded.
        """
        from app.models.predictions_models import PikkitBet, PikkitPick, PropMarketDefinition

        self.clear()

        # Load market definitions for stat_key lookup
        market_defs = {}
        for md in db_session.query(PropMarketDefinition).filter_by(active=True).all():
            market_defs[md.market_id] = md.stat_key

        # Load open bets with their picks
        open_bets = db_session.query(PikkitBet).filter(
            PikkitBet.status.in_(['open', 'active', 'pending'])
        ).all()

        count = 0
        for bet in open_bets:
            picks = db_session.query(PikkitPick).filter_by(bet_id=bet.pikkit_id).all()
            total_legs = len(picks)
            bet_type = 'parlay' if total_legs > 1 else 'straight'

            for idx, pick in enumerate(picks, 1):
                stat_key = market_defs.get(pick.market_id)
                if not stat_key:
                    logger.warning(f"Unknown market_id {pick.market_id} for pick {pick.pikkit_id}")
                    continue

                if not pick.game_pk or not pick.player_id:
                    logger.warning(f"Pick {pick.pikkit_id} missing game_pk or player_id")
                    continue

                side, line = _parse_line_and_side(pick.pick_name or '')
                if side is None:
                    logger.warning(f"Could not parse side/line from pick_name: {pick.pick_name}")
                    continue

                info = PickInfo(
                    pick_id=pick.pikkit_id,
                    bet_id=bet.pikkit_id,
                    player_id=pick.player_id,
                    player_name=pick.player_name or 'Unknown',
                    game_pk=pick.game_pk,
                    stat_key=stat_key,
                    side=side,
                    line=line,
                    bet_type=bet_type,
                    stake=bet.stake,
                    odds=bet.odds,
                    potential_payout=bet.potential_payout,
                    leg_index=idx,
                    total_legs=total_legs,
                )
                self.add_pick(info)
                count += 1

        logger.info(f"Watchlist synced: {count} picks across {len(self._active_games)} games")
        return count
