"""Shared building blocks for per-league daily accuracy summaries.

Every sport's accuracy endpoint returns the same wire shape so the
frontend can render any league's summary with a single component:

    {
      "date": "2026-05-23",
      "available": true,
      "buckets": [
        {"key": "ks_ou", "label": "Pitcher Ks O/U",
         "primary": "8/12 · 67%", "secondary": "K MAE 1.3", "tone": "good"},
        ...
      ]
    }

`AccuracyBucket` is the only dataclass clients see. Per-league services
build buckets by calling the helpers in this module
(`ou_call_bucket`, `hit_rate_bucket`, etc.) over their projection rows.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Literal, Optional

Tone = Literal["good", "warn", "neutral"]


@dataclass
class AccuracyBucket:
    """One tile rendered by the frontend AccuracySummary component."""

    key: str
    label: str
    primary: str
    secondary: str
    tone: Tone

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------


def pct(rate: Optional[float]) -> str:
    """Format a 0..1 rate as 'NN%', or '—' when None."""
    if rate is None:
        return "—"
    return f"{round(rate * 100)}%"


def tone_for_rate(rate: Optional[float]) -> Tone:
    """Color tier for an accuracy rate. >=0.6 good, in [0.4, 0.6) warn,
    <0.4 also warn (we don't surface 'bad' as red — keeps the dashboard
    from looking alarmist on a single off day).
    """
    if rate is None:
        return "neutral"
    if rate >= 0.6:
        return "good"
    return "warn"


# ---------------------------------------------------------------------------
# Bucket builders
# ---------------------------------------------------------------------------


def ou_call_bucket(
    rows: Iterable[dict[str, Any]],
    *,
    line_field: str,
    pick_field: str,
    actual_field: str,
    projected_field: str,
    label: str,
    key: str,
) -> AccuracyBucket:
    """O/U call accuracy across rows that carry a sportsbook line.

    Counts each row where line + pick + actual are all present.
    actual == line is a push and drops out of the total.

    Reports primary = 'correct/total · NN%' and secondary = 'MAE X.XX
    · K push' where K is the push count (omitted if zero).
    """
    total = 0
    correct = 0
    push = 0
    abs_errors: list[float] = []

    for row in rows:
        line = row.get(line_field)
        pick = (row.get(pick_field) or "").strip().lower()
        actual = row.get(actual_field)
        projected = row.get(projected_field)

        if actual is not None and projected is not None:
            try:
                abs_errors.append(abs(float(projected) - float(actual)))
            except (TypeError, ValueError):
                pass

        if line is None or not pick or actual is None:
            continue
        try:
            line_f = float(line)
            actual_f = float(actual)
        except (TypeError, ValueError):
            continue

        if actual_f == line_f:
            push += 1
            continue

        won_over = pick in ("over", "o") and actual_f > line_f
        won_under = pick in ("under", "u") and actual_f < line_f
        total += 1
        if won_over or won_under:
            correct += 1

    accuracy = correct / total if total else None
    mae = sum(abs_errors) / len(abs_errors) if abs_errors else None

    secondary_bits: list[str] = []
    if mae is not None:
        secondary_bits.append(f"MAE {mae:.2f}")
    if push:
        secondary_bits.append(f"{push} push")
    secondary = " · ".join(secondary_bits) if secondary_bits else "No graded calls"

    return AccuracyBucket(
        key=key,
        label=label,
        primary=f"{correct}/{total} · {pct(accuracy)}",
        secondary=secondary,
        tone=tone_for_rate(accuracy),
    )


def hit_rate_bucket(
    rows: Iterable[dict[str, Any]],
    *,
    actual_field: str,
    projected_field: str,
    threshold: float,
    label: str,
    key: str,
    secondary: str,
) -> AccuracyBucket:
    """Hit rate across rows where projected >= 1: success = actual >= threshold.

    Rows where the actual hasn't been written yet are skipped from both
    numerator and denominator (an ungraded prop doesn't count for or
    against). Rows projected as 0 are not predictions at all.
    """
    total = 0
    hits = 0
    for row in rows:
        projected = row.get(projected_field)
        actual = row.get(actual_field)
        if not projected or float(projected) < 1:
            continue
        if actual is None:
            continue
        total += 1
        try:
            if float(actual) >= threshold:
                hits += 1
        except (TypeError, ValueError):
            continue
    rate = hits / total if total else None
    return AccuracyBucket(
        key=key,
        label=label,
        primary=f"{hits}/{total} · {pct(rate)}",
        secondary=secondary,
        tone=tone_for_rate(rate),
    )


def edge_play_bucket(
    rows: Iterable[dict[str, Any]],
    *,
    pick_field: str,
    correct_field: str,
    label: str,
    key: str,
    secondary: str = "Graded edge plays only",
) -> AccuracyBucket:
    """Accuracy for rows with an edge play and a stored correct/incorrect flag."""
    total = 0
    correct = 0
    for row in rows:
        pick = (row.get(pick_field) or "").strip().upper()
        if pick in ("", "NO_PLAY", "NONE"):
            continue
        graded = row.get(correct_field)
        if graded is None:
            continue
        total += 1
        if graded:
            correct += 1
    accuracy = correct / total if total else None
    return AccuracyBucket(
        key=key,
        label=label,
        primary=f"{correct}/{total} · {pct(accuracy)}",
        secondary=secondary if total else "No graded calls",
        tone=tone_for_rate(accuracy),
    )


def recommendation_side_bucket(
    rows: Iterable[dict[str, Any]],
    *,
    pick_field: str,
    winner_field: str,
    label: str,
    key: str,
    secondary: str = "Graded edge plays only",
) -> AccuracyBucket:
    """Accuracy for HOME/AWAY recommendation picks vs actual winner.

    Rows without a HOME/AWAY pick or without a recorded winner are skipped.
    """
    total = 0
    correct = 0
    for row in rows:
        pick = (row.get(pick_field) or "").strip().upper()
        winner = (row.get(winner_field) or "").strip().lower()
        if pick not in ("HOME", "AWAY") or winner not in ("home", "away"):
            continue
        total += 1
        if pick == winner.upper():
            correct += 1
    accuracy = correct / total if total else None
    return AccuracyBucket(
        key=key,
        label=label,
        primary=f"{correct}/{total} · {pct(accuracy)}",
        secondary=secondary if total else "No graded calls",
        tone=tone_for_rate(accuracy),
    )


def mae_bucket(
    rows: Iterable[dict[str, Any]],
    *,
    projected_field: str,
    actual_field: str,
    label: str,
    key: str,
    unit_label: str = "",
) -> AccuracyBucket:
    """MAE-only bucket for stats without a sportsbook line.

    Primary line is `MAE X.XX <unit>` over the N rows that had an actual.
    Tone is always 'neutral' since MAE has no universal good/bad threshold.
    """
    abs_errors: list[float] = []
    for row in rows:
        projected = row.get(projected_field)
        actual = row.get(actual_field)
        if projected is None or actual is None:
            continue
        try:
            abs_errors.append(abs(float(projected) - float(actual)))
        except (TypeError, ValueError):
            continue

    if not abs_errors:
        return AccuracyBucket(
            key=key,
            label=label,
            primary="—",
            secondary="No graded rows",
            tone="neutral",
        )
    mae = sum(abs_errors) / len(abs_errors)
    return AccuracyBucket(
        key=key,
        label=label,
        primary=f"MAE {mae:.2f}{(' ' + unit_label) if unit_label else ''}",
        secondary=f"Across {len(abs_errors)} graded",
        tone="neutral",
    )


# ---------------------------------------------------------------------------
# Response assembly
# ---------------------------------------------------------------------------


def assemble(
    *,
    date_str: str,
    buckets: list[AccuracyBucket],
    available: bool,
) -> dict[str, Any]:
    """Wrap buckets in the standard accuracy response shape."""
    return {
        "date": date_str,
        "available": available,
        "buckets": [b.to_dict() for b in buckets],
    }
