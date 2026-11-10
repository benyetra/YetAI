"""One spelling-insensitive key for matching player names across feeds.

Sportsbooks, nflverse and ESPN disagree on punctuation and suffixes
("A.J. Brown" / "AJ Brown", "Brian Thomas Jr" / "Brian Thomas Jr.",
"Kenneth Walker III" / "Kenneth Walker"). Comparing these keys instead of raw
or substring names keeps a line from attaching to the wrong player and stops
real lines from being dropped over a period.
"""

from __future__ import annotations

import re
import unicodedata

_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})


def player_name_key(name: str | None) -> str:
    """'A.J. Brown Jr.' -> 'aj brown'. Empty string for a blank name."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = text.replace("-", " ")
    text = re.sub(r"[^a-z0-9 ]", "", text)
    tokens = [t for t in text.split() if t]
    while len(tokens) > 1 and tokens[-1] in _SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def find_by_player_name(name: str | None, by_name: dict):
    """Value from ``by_name`` (keyed by any spelling) whose key matches ``name``."""
    wanted = player_name_key(name)
    if not wanted:
        return None
    for candidate, value in by_name.items():
        if player_name_key(candidate) == wanted:
            return value
    return None
