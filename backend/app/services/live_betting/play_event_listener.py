"""
PlayEventListener: evaluates each MLB play-by-play event against the prop
watchlist and emits PropEvents when a play affects a tracked player prop.
"""

import logging
from typing import Dict, List, Set, Tuple

from app.services.live_betting.prop_events import (
    STAT_MATCHERS,
    PropEvent,
    _event_type,
    _batter_id,
    _pitcher_id,
)
from app.services.live_betting.prop_watchlist import PropWatchlist, PickInfo

logger = logging.getLogger("play_event_listener")


class PlayEventListener:
    """
    Maintains running stat counts per (game_pk, player_id, stat_key)
    and evaluates each play against the watchlist.
    """

    def __init__(self, watchlist: PropWatchlist):
        self.watchlist = watchlist
        # {(game_pk, player_id, stat_key) -> running_total}
        self._counts: Dict[Tuple[int, int, str], int] = {}
        # {(game_pk, atBatIndex)} -> set of already-processed combos
        self._processed_plays: Set[Tuple[int, str]] = set()

    def reset_game(self, game_pk: int) -> None:
        """Clear counts for a game (e.g., on poller restart)."""
        keys_to_remove = [k for k in self._counts if k[0] == game_pk]
        for k in keys_to_remove:
            del self._counts[k]
        plays_to_remove = {p for p in self._processed_plays if p[0] == game_pk}
        self._processed_plays -= plays_to_remove

    def on_play(self, game_pk: int, play: dict) -> List[PropEvent]:
        """
        Evaluate a single play from the MLB live feed.
        Returns a list of PropEvents to be sent as alerts.

        Only processes complete at-bats (about.isComplete == True).
        """
        about = play.get("about", {})
        if not about.get("isComplete", False):
            return []

        play_id = str(about.get("atBatIndex", ""))
        if not play_id:
            return []

        # Skip if already processed (handles replay on restart)
        dedup_key = (game_pk, play_id)
        if dedup_key in self._processed_plays:
            return []
        self._processed_plays.add(dedup_key)

        events = []
        event_type = _event_type(play)

        # Collect all player IDs involved in this play
        batter = _batter_id(play)
        pitcher = _pitcher_id(play)
        runner_ids = set()
        for runner in play.get("runners", []):
            rid = runner.get("details", {}).get("runner", {}).get("id", 0)
            if rid:
                runner_ids.add(rid)

        # All player IDs to check
        player_ids = {batter, pitcher} | runner_ids
        player_ids.discard(0)

        for stat_key, matcher in STAT_MATCHERS.items():
            for pid in player_ids:
                # Check watchlist
                picks = self.watchlist.lookup(game_pk, pid, stat_key)
                if not picks:
                    continue

                # Run matcher
                delta = matcher(play, pid)
                if delta <= 0:
                    continue

                # Update running count
                count_key = (game_pk, pid, stat_key)
                old_total = self._counts.get(count_key, 0)
                new_total = old_total + delta
                self._counts[count_key] = new_total

                # Generate events for each matching pick
                for pick in picks:
                    alert_type = self._determine_alert_type(
                        pick.side, pick.line, old_total, new_total
                    )
                    if alert_type is None:
                        continue

                    play_desc = self._describe_play(
                        event_type, pick.player_name, stat_key, delta
                    )

                    event = PropEvent(
                        pick_id=pick.pick_id,
                        game_pk=game_pk,
                        play_id=play_id,
                        player_id=pid,
                        player_name=pick.player_name,
                        stat_key=stat_key,
                        stat_delta=delta,
                        new_total=new_total,
                        line=pick.line,
                        side=pick.side,
                        alert_type=alert_type,
                        bet_type=pick.bet_type,
                        bet_stake=pick.stake,
                        bet_odds=pick.odds,
                        bet_payout=pick.potential_payout,
                        leg_index=pick.leg_index,
                        total_legs=pick.total_legs,
                        play_description=play_desc,
                    )
                    events.append(event)
                    logger.info(
                        f"PropEvent: {alert_type} for {pick.player_name} "
                        f"{stat_key}={new_total} (line {pick.side} {pick.line})"
                    )

        return events

    @staticmethod
    def _determine_alert_type(side: str, line: float, old_total: int, new_total: int):
        """
        Determine the alert type based on side, line, and count change.
        Returns None if no alert should fire.
        """
        threshold = int(line)  # e.g., 0.5 -> 0, 1.5 -> 1

        if side == "over":
            if old_total <= threshold < new_total:
                return "threshold_cleared"
            elif new_total <= threshold and line > 0.5:
                return "progress"
            # Already cleared or Over 0.5 progress — no alert
            return None

        elif side == "under":
            if old_total <= threshold < new_total:
                return "under_killed"
            # Under: silence is good news
            return None

        return None

    @staticmethod
    def _describe_play(
        event_type: str, player_name: str, stat_key: str, delta: int
    ) -> str:
        """Generate a human-readable play description for the alert headline."""
        from app.services.live_betting.prop_events import EVENT_DESCRIPTIONS

        verb = EVENT_DESCRIPTIONS.get(event_type, event_type.replace("_", " "))

        if stat_key == "home_runs":
            return f"{player_name} just homered!"
        elif stat_key == "hits":
            return f"{player_name} {verb}!"
        elif stat_key == "strikeouts_pitching":
            return f"{player_name}'s strikeout"
        elif stat_key == "rbis":
            return f"{player_name} drove in {delta} run{'s' if delta > 1 else ''}!"
        elif stat_key == "runs":
            return f"{player_name} scored!"
        elif stat_key == "stolen_bases":
            return f"{player_name} stole a base!"
        elif stat_key == "walks":
            return f"{player_name} drew a walk"
        elif stat_key == "total_bases":
            return f"{player_name} {verb} (+{delta} TB)!"
        elif stat_key == "earned_runs":
            return f"{player_name} gave up {delta} earned run{'s' if delta > 1 else ''}"
        elif stat_key == "hits_allowed":
            return f"Hit allowed by {player_name}"
        elif stat_key == "outs_recorded":
            return f"{player_name} recorded {delta} out{'s' if delta > 1 else ''}"
        else:
            return f"{player_name}: {stat_key} +{delta}"

    def get_count(self, game_pk: int, player_id: int, stat_key: str) -> int:
        """Get the current running count for a player stat in a game."""
        return self._counts.get((game_pk, player_id, stat_key), 0)
