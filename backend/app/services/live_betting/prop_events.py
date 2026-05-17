"""
PropEvent dataclass and stat matcher functions for MLB play-by-play events.

Each matcher is a pure function: (play_dict, player_id) -> stat_delta (int).
Matchers return 0 if the play doesn't affect the stat for that player.
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class PropEvent:
    """Represents a stat event that affects a player prop."""
    pick_id: str
    game_pk: int
    play_id: str          # atBatIndex from MLB Stats API
    player_id: int
    player_name: str
    stat_key: str
    stat_delta: int       # How much this play added (e.g., 1 HR, 2 total bases)
    new_total: int        # Running total after this play
    line: float           # The prop line (e.g., 0.5, 1.5)
    side: str             # 'over' or 'under'
    alert_type: str       # 'threshold_cleared', 'progress', 'under_killed'
    bet_type: str         # 'straight' or 'parlay'
    bet_stake: Optional[float] = None
    bet_odds: Optional[str] = None
    bet_payout: Optional[float] = None
    leg_index: Optional[int] = None    # e.g., 4 (leg 4)
    total_legs: Optional[int] = None   # e.g., 5 (of 5)
    play_description: str = ''


# --------------------------------------------------------------------------- #
# Hit-type helpers
# --------------------------------------------------------------------------- #

HIT_EVENTS = {'single', 'double', 'triple', 'home_run'}
TOTAL_BASE_MAP = {'single': 1, 'double': 2, 'triple': 3, 'home_run': 4}


def _event_type(play: dict) -> str:
    """Extract normalized eventType from a play object."""
    result = play.get('result', {})
    return (result.get('eventType') or result.get('event') or '').lower().replace(' ', '_')


def _batter_id(play: dict) -> int:
    return play.get('matchup', {}).get('batter', {}).get('id', 0)


def _pitcher_id(play: dict) -> int:
    return play.get('matchup', {}).get('pitcher', {}).get('id', 0)


# --------------------------------------------------------------------------- #
# Batter stat matchers
# --------------------------------------------------------------------------- #

def match_hits(play: dict, player_id: int) -> int:
    if _batter_id(play) != player_id:
        return 0
    return 1 if _event_type(play) in HIT_EVENTS else 0


def match_singles(play: dict, player_id: int) -> int:
    if _batter_id(play) != player_id:
        return 0
    return 1 if _event_type(play) == 'single' else 0


def match_doubles(play: dict, player_id: int) -> int:
    if _batter_id(play) != player_id:
        return 0
    return 1 if _event_type(play) == 'double' else 0


def match_triples(play: dict, player_id: int) -> int:
    if _batter_id(play) != player_id:
        return 0
    return 1 if _event_type(play) == 'triple' else 0


def match_home_runs(play: dict, player_id: int) -> int:
    if _batter_id(play) != player_id:
        return 0
    return 1 if _event_type(play) == 'home_run' else 0


def match_total_bases(play: dict, player_id: int) -> int:
    if _batter_id(play) != player_id:
        return 0
    return TOTAL_BASE_MAP.get(_event_type(play), 0)


def match_rbis(play: dict, player_id: int) -> int:
    if _batter_id(play) != player_id:
        return 0
    return play.get('result', {}).get('rbi', 0)


def match_runs_scored(play: dict, player_id: int) -> int:
    """Check if player scored on this play (appears in runners who scored)."""
    runners = play.get('runners', [])
    count = 0
    for runner in runners:
        details = runner.get('details', {})
        runner_id = details.get('runner', {}).get('id', 0)
        if runner_id == player_id and details.get('isScoringEvent', False):
            count += 1
    return count


def match_walks(play: dict, player_id: int) -> int:
    if _batter_id(play) != player_id:
        return 0
    et = _event_type(play)
    return 1 if et in ('walk', 'intent_walk') else 0


def match_stolen_bases(play: dict, player_id: int) -> int:
    """Check runners for stolen base events matching this player."""
    runners = play.get('runners', [])
    count = 0
    for runner in runners:
        details = runner.get('details', {})
        runner_id = details.get('runner', {}).get('id', 0)
        event = (details.get('event') or '').lower()
        if runner_id == player_id and 'stolen_base' in event.replace(' ', '_'):
            count += 1
    return count


# --------------------------------------------------------------------------- #
# Pitcher stat matchers
# --------------------------------------------------------------------------- #

def match_strikeouts_pitching(play: dict, player_id: int) -> int:
    if _pitcher_id(play) != player_id:
        return 0
    et = _event_type(play)
    return 1 if et in ('strikeout', 'strikeout_double_play') else 0


def match_hits_allowed(play: dict, player_id: int) -> int:
    if _pitcher_id(play) != player_id:
        return 0
    return 1 if _event_type(play) in HIT_EVENTS else 0


def match_earned_runs(play: dict, player_id: int) -> int:
    """Count earned runs on this play attributed to the current pitcher."""
    if _pitcher_id(play) != player_id:
        return 0
    runners = play.get('runners', [])
    count = 0
    for runner in runners:
        details = runner.get('details', {})
        if details.get('isScoringEvent', False) and details.get('earned', False):
            count += 1
    return count


def match_outs_recorded(play: dict, player_id: int) -> int:
    """Count outs recorded on this play by the current pitcher."""
    if _pitcher_id(play) != player_id:
        return 0
    count = play.get('count', {})
    return count.get('outs', 0) if 'outs' in count else 0


# --------------------------------------------------------------------------- #
# Registry: stat_key -> matcher function
# --------------------------------------------------------------------------- #

STAT_MATCHERS: Dict[str, Callable[[dict, int], int]] = {
    'hits': match_hits,
    'singles': match_singles,
    'doubles': match_doubles,
    'triples': match_triples,
    'home_runs': match_home_runs,
    'total_bases': match_total_bases,
    'rbis': match_rbis,
    'runs': match_runs_scored,
    'walks': match_walks,
    'stolen_bases': match_stolen_bases,
    'strikeouts_pitching': match_strikeouts_pitching,
    'hits_allowed': match_hits_allowed,
    'earned_runs': match_earned_runs,
    'outs_recorded': match_outs_recorded,
}


# Human-readable stat names for alert messages
STAT_DISPLAY_NAMES: Dict[str, str] = {
    'hits': 'Hits',
    'singles': 'Singles',
    'doubles': 'Doubles',
    'triples': 'Triples',
    'home_runs': 'HR',
    'total_bases': 'Total Bases',
    'rbis': 'RBIs',
    'runs': 'Runs',
    'walks': 'Walks',
    'stolen_bases': 'Stolen Bases',
    'strikeouts_pitching': 'K',
    'hits_allowed': 'Hits Allowed',
    'earned_runs': 'Earned Runs',
    'outs_recorded': 'Outs Recorded',
}


# Human-readable event descriptions for alert headlines
EVENT_DESCRIPTIONS: Dict[str, str] = {
    'single': 'singled',
    'double': 'doubled',
    'triple': 'tripled',
    'home_run': 'homered',
    'walk': 'walked',
    'intent_walk': 'was intentionally walked',
    'strikeout': 'struck out',
    'strikeout_double_play': 'struck out',
    'stolen_base': 'stole a base',
}
