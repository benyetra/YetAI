"""Pick the line to grade against, and the best book per side, for one
player's over/under prop across sportsbooks."""

from __future__ import annotations

from statistics import median_low
from typing import Any


def _side(lines: dict[str, Any], side: str) -> dict[str, Any] | None:
    entry = lines.get(side)
    if not isinstance(entry, dict):
        return None
    try:
        line = float(entry["line"])
    except (KeyError, TypeError, ValueError):
        return None
    if line <= 0:
        return None
    return {"line": line, "odds": entry.get("odds", -110)}


def best_lines(player_lines: dict[str, dict]) -> dict[str, Any]:
    """``{"over", "under", "consensus"}`` for ``{book: {"over"/"under": ...}}``.

    * ``consensus`` is the middle line the books offer (the lower of the two
      middle ones for an even count, so it is always a real line). Model edge
      is measured against it, not against the most extreme book.
    * ``over`` is the best book to bet the over at: the **lowest** line, then
      the best price. ``under`` is the **highest** line, then the best price.
      (The earlier version had these reversed and reported the worst book.)

    Sides nobody offers keep the legacy placeholders (line 0 / 999, -110).
    """
    best_over = {"line": 0, "odds": -110, "book": "N/A"}
    best_under = {"line": 999, "odds": -110, "book": "N/A"}
    points: list[float] = []
    for bookmaker, lines in (player_lines or {}).items():
        over = _side(lines, "over")
        under = _side(lines, "under")
        if over is not None:
            points.append(over["line"])
            current = best_over
            if current["book"] == "N/A" or (over["line"], -over["odds"]) < (
                current["line"],
                -current["odds"],
            ):
                best_over = {**over, "book": bookmaker}
        elif under is not None:
            points.append(under["line"])
        if under is not None:
            current = best_under
            if current["book"] == "N/A" or (-under["line"], -under["odds"]) < (
                -current["line"],
                -current["odds"],
            ):
                best_under = {**under, "book": bookmaker}
    consensus = median_low(points) if points else 0.0
    return {"over": best_over, "under": best_under, "consensus": consensus}
