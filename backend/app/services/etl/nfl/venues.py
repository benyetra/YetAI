"""Roof and playing surface for NFL stadiums, by ESPN venue name.

ESPN's schedule payload only names the venue. The kicker pipeline used to
guess from the name itself ("dome" in the name -> indoors, "turf" -> turf),
which called every retractable-roof and sponsor-named dome an outdoor grass
field: weather penalties were applied to kicks at AT&T Stadium or Ford Field.
Unknown venues (international sites, new buildings) default to outdoor grass.
"""

from __future__ import annotations

import re

# Fixed domes and retractable roofs (treated as indoors: when the roof is open
# conditions are mild by design).
_INDOOR = (
    "allegiant stadium",
    "at&t stadium",
    "caesars superdome",
    "ford field",
    "lucas oil stadium",
    "mercedes-benz stadium",
    "nrg stadium",
    "sofi stadium",
    "state farm stadium",
    "u.s. bank stadium",
)

_TURF = (
    "at&t stadium",
    "bank of america stadium",
    "caesars superdome",
    "ford field",
    "gillette stadium",
    "highmark stadium",
    "lucas oil stadium",
    "lumen field",
    "mercedes-benz stadium",
    "metlife stadium",
    "nissan stadium",
    "nrg stadium",
    "paycor stadium",
    "sofi stadium",
    "tottenham hotspur stadium",
    "u.s. bank stadium",
)


def _key(venue_name: str | None) -> str:
    return re.sub(r"\s+", " ", (venue_name or "").strip().lower())


def venue_type(venue_name: str | None) -> str:
    """'dome' for fixed and retractable roofs, else 'outdoor'."""
    key = _key(venue_name)
    if key in _INDOOR or "dome" in key:
        return "dome"
    return "outdoor"


def surface_type(venue_name: str | None) -> str:
    """'turf' for artificial surfaces, else 'grass'."""
    key = _key(venue_name)
    if key in _TURF or "turf" in key:
        return "turf"
    return "grass"
