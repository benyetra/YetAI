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

from dataclasses import asdict, dataclass, field
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


@dataclass
class AccuracyOverviewItem:
    """One row in the cross-league accuracy overview (Stat Projections hub)."""

    sport: str
    label: str
    primary: str
    secondary: str
    tone: Tone
    has_data: bool
    graded_count: int = 0
    markets: list[dict[str, Any]] = field(default_factory=list)

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
# Row-level results: the single grading definition. Every bucket / count
# builder below derives from these so a tile and a row can never disagree.
# ---------------------------------------------------------------------------

RowResult = Literal["hit", "miss", "push", "no_play", "dnp", "ungraded"]
OVERVIEW_MIN_GRADED = 30


def _missing_actual(actual_expected: bool) -> RowResult:
    return "dnp" if actual_expected else "ungraded"


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def ou_row_result(
    *, line: Any, pick: Any, actual: Any, actual_expected: bool = False
) -> RowResult:
    """Grade one sportsbook O/U row. Non over/under picks are not calls."""
    if str(pick or "").strip().lower() not in ("over", "o", "under", "u"):
        return "no_play"
    if line is None:
        return "no_play"
    if actual is None:
        return _missing_actual(actual_expected)
    line_f, actual_f = _to_float(line), _to_float(actual)
    if line_f is None or actual_f is None:
        return "ungraded"
    if actual_f == line_f:
        return "push"
    is_over = str(pick).strip().lower() in ("over", "o")
    return "hit" if (actual_f > line_f) == is_over else "miss"


def edge_row_result(
    *,
    pick: Any,
    correct_flag: Any,
    push: bool = False,
    actual_expected: bool = False,
) -> RowResult:
    """Grade one edge-play row from its stored correct flag."""
    if str(pick or "").strip().upper() in ("", "NO_PLAY", "NONE", "PASS"):
        return "no_play"
    if push:
        return "push"
    if correct_flag is None:
        return _missing_actual(actual_expected)
    return "hit" if correct_flag else "miss"


def hit_rate_row_result(
    *,
    projected: Any,
    actual: Any,
    threshold: float,
    actual_expected: bool = False,
) -> RowResult:
    """Grade one hit-rate prop: projected >= 1 is a prediction, hit = actual >= threshold."""
    projected_f = _to_float(projected)
    if projected_f is None or projected_f < 1:
        return "no_play"
    if actual is None:
        return _missing_actual(actual_expected)
    actual_f = _to_float(actual)
    if actual_f is None:
        return "ungraded"
    return "hit" if actual_f >= threshold else "miss"


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

    Counts rows graded "hit"/"miss" by ``ou_row_result`` (a real over/under pick
    with line + actual). Pushes drop out of the total; PASS/NO_PLAY are not calls.

    Reports primary = 'correct/total · NN%' and secondary = 'MAE X.XX
    · K push' where K is the push count (omitted if zero). MAE is over every
    row with a projection and an actual, regardless of pick.
    """
    total = 0
    correct = 0
    push = 0
    abs_errors: list[float] = []

    for row in rows:
        actual = row.get(actual_field)
        projected = row.get(projected_field)

        if actual is not None and projected is not None:
            try:
                abs_errors.append(abs(float(projected) - float(actual)))
            except (TypeError, ValueError):
                pass

        result = ou_row_result(
            line=row.get(line_field), pick=row.get(pick_field), actual=actual
        )
        if result == "push":
            push += 1
        elif result in ("hit", "miss"):
            total += 1
            correct += result == "hit"

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

    Rows where the actual is missing or unparseable are skipped from both
    numerator and denominator (an ungraded prop doesn't count for or
    against). Rows projected as 0 are not predictions at all.
    """
    total = 0
    hits = 0
    for row in rows:
        result = hit_rate_row_result(
            projected=row.get(projected_field),
            actual=row.get(actual_field),
            threshold=threshold,
        )
        if result in ("hit", "miss"):
            total += 1
            hits += result == "hit"
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
        result = edge_row_result(
            pick=row.get(pick_field), correct_flag=row.get(correct_field)
        )
        if result in ("hit", "miss"):
            total += 1
            correct += result == "hit"
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


def brier_bucket(
    rows: Iterable[dict[str, Any]],
    *,
    prob_field: str,
    actual_field: str,
    label: str,
    key: str,
) -> AccuracyBucket:
    """Mean Brier score for binary outcomes (lower is better).

    Skips rows missing probability or actual outcome.
    """
    scores: list[float] = []
    for row in rows:
        prob = row.get(prob_field)
        actual = row.get(actual_field)
        if prob is None or actual is None:
            continue
        try:
            p = float(prob)
            y = 1.0 if actual else 0.0
            scores.append((p - y) ** 2)
        except (TypeError, ValueError):
            continue

    if not scores:
        return AccuracyBucket(
            key=key,
            label=label,
            primary="—",
            secondary="No graded rows",
            tone="neutral",
        )
    brier = sum(scores) / len(scores)
    return AccuracyBucket(
        key=key,
        label=label,
        primary=f"Brier {brier:.3f}",
        secondary=f"Across {len(scores)} graded",
        tone="neutral",
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


# ---------------------------------------------------------------------------
# Season / overview aggregates (graded correct + total across row sets)
# ---------------------------------------------------------------------------


def ou_call_graded_breakdown(
    rows: Iterable[dict[str, Any]],
    *,
    line_field: str,
    pick_field: str,
    actual_field: str,
) -> dict[str, int]:
    """Per-row counters for sportsbook O/U grading (mirrors ``ou_call_graded_counts``).

    ``rows_scanned`` counts input rows; skip buckets are mutually exclusive in
    scan order; ``graded_total`` / ``graded_correct`` match the overview numerator
    and denominator.
    """
    rows_scanned = 0
    missing_line = 0
    missing_pick = 0
    missing_actual = 0
    non_decision_pick = 0
    invalid_numeric = 0
    push = 0
    graded_total = 0
    graded_correct = 0
    for row in rows:
        rows_scanned += 1
        line = row.get(line_field)
        pick = (row.get(pick_field) or "").strip().lower()
        actual = row.get(actual_field)
        result = ou_row_result(line=line, pick=pick, actual=actual)
        if result == "no_play":
            if line is None:
                missing_line += 1
            elif not pick:
                missing_pick += 1
            else:
                non_decision_pick += 1
        elif result == "ungraded":
            if actual is None:
                missing_actual += 1
            else:
                invalid_numeric += 1
        elif result == "push":
            push += 1
        else:
            graded_total += 1
            graded_correct += result == "hit"
    return {
        "rows_scanned": rows_scanned,
        "missing_line": missing_line,
        "missing_pick": missing_pick,
        "missing_actual": missing_actual,
        "non_decision_pick": non_decision_pick,
        "invalid_numeric": invalid_numeric,
        "push": push,
        "graded_total": graded_total,
        "graded_correct": graded_correct,
    }


def ou_call_graded_counts(
    rows: Iterable[dict[str, Any]],
    *,
    line_field: str,
    pick_field: str,
    actual_field: str,
) -> tuple[int, int]:
    """Return (correct, total) for sportsbook O/U calls; pushes excluded from total."""
    b = ou_call_graded_breakdown(
        rows,
        line_field=line_field,
        pick_field=pick_field,
        actual_field=actual_field,
    )
    return b["graded_correct"], b["graded_total"]


def hit_rate_graded_breakdown(
    rows: Iterable[dict[str, Any]],
    *,
    actual_field: str,
    projected_field: str,
    threshold: float,
) -> dict[str, int]:
    """Counters for hit-rate props (mirrors ``hit_rate_graded_counts``)."""
    rows_scanned = 0
    skip_low_or_bad_projection = 0
    skip_missing_actual = 0
    graded_total = 0
    graded_hits = 0
    graded_actual_parse_fail = 0
    for row in rows:
        rows_scanned += 1
        actual = row.get(actual_field)
        result = hit_rate_row_result(
            projected=row.get(projected_field), actual=actual, threshold=threshold
        )
        if result == "no_play":
            skip_low_or_bad_projection += 1
        elif result == "ungraded":
            if actual is None:
                skip_missing_actual += 1
            else:
                graded_actual_parse_fail += 1
        else:
            graded_total += 1
            graded_hits += result == "hit"
    return {
        "rows_scanned": rows_scanned,
        "skip_low_or_bad_projection": skip_low_or_bad_projection,
        "skip_missing_actual": skip_missing_actual,
        "graded_total": graded_total,
        "graded_hits": graded_hits,
        "graded_actual_parse_fail": graded_actual_parse_fail,
    }


def hit_rate_graded_counts(
    rows: Iterable[dict[str, Any]],
    *,
    actual_field: str,
    projected_field: str,
    threshold: float,
) -> tuple[int, int]:
    """Return (hits, total) for hit-rate style props (same rules as hit_rate_bucket)."""
    b = hit_rate_graded_breakdown(
        rows,
        actual_field=actual_field,
        projected_field=projected_field,
        threshold=threshold,
    )
    return b["graded_hits"], b["graded_total"]


def edge_play_graded_breakdown(
    rows: Iterable[dict[str, Any]],
    *,
    pick_field: str,
    correct_field: str,
) -> dict[str, int]:
    """Counters for edge-play grading (mirrors ``edge_play_graded_counts``)."""
    rows_scanned = 0
    empty_pick = 0
    no_play_pick = 0
    pass_pick = 0
    missing_grade = 0
    graded_total = 0
    graded_correct = 0
    for row in rows:
        rows_scanned += 1
        pick = (row.get(pick_field) or "").strip().upper()
        result = edge_row_result(pick=pick, correct_flag=row.get(correct_field))
        if result == "no_play":
            if pick == "":
                empty_pick += 1
            elif pick == "PASS":
                pass_pick += 1
            else:
                no_play_pick += 1
        elif result == "ungraded":
            missing_grade += 1
        else:
            graded_total += 1
            graded_correct += result == "hit"
    return {
        "rows_scanned": rows_scanned,
        "empty_pick": empty_pick,
        "no_play_pick": no_play_pick,
        "pass_pick": pass_pick,
        "missing_grade": missing_grade,
        "graded_total": graded_total,
        "graded_correct": graded_correct,
    }


def edge_play_graded_counts(
    rows: Iterable[dict[str, Any]],
    *,
    pick_field: str,
    correct_field: str,
) -> tuple[int, int]:
    """Return (correct, total) for edge plays with a stored correct flag."""
    b = edge_play_graded_breakdown(
        rows, pick_field=pick_field, correct_field=correct_field
    )
    return b["graded_correct"], b["graded_total"]


def overview_item_from_markets(
    *,
    sport: str,
    label: str,
    markets: dict[str, tuple[int, int]],
) -> dict[str, Any]:
    """Build one overview dict from per-market (correct, graded_total) pairs.

    Carries the population (``markets`` + ``graded_count``) so the tile says what
    it is made of. Below ``OVERVIEW_MIN_GRADED`` the primary is a count, not a
    bare percentage, and the tone stays neutral.
    """
    listed = [
        {"market": name, "correct": c, "graded": t}
        for name, (c, t) in markets.items()
        if t > 0
    ]
    total = sum(m["graded"] for m in listed)
    correct = sum(m["correct"] for m in listed)
    has_data = total > 0
    small = has_data and total < OVERVIEW_MIN_GRADED
    rate = correct / total if has_data else None
    if not has_data:
        primary, secondary = "No graded projections yet", "Season to date"
    else:
        primary = f"{correct}/{total}" if small else pct(rate)
        secondary = f"{total} graded calls" + (" · small sample" if small else "")
    tone: Tone = tone_for_rate(rate) if has_data and not small else "neutral"
    return AccuracyOverviewItem(
        sport=sport,
        label=label,
        primary=primary,
        secondary=secondary,
        tone=tone,
        has_data=has_data,
        graded_count=total,
        markets=listed,
    ).to_dict()


def overview_item_from_totals(
    *,
    sport: str,
    label: str,
    correct: int,
    total: int,
) -> dict[str, Any]:
    """Thin wrapper over ``overview_item_from_markets`` for single-population callers."""
    return overview_item_from_markets(
        sport=sport, label=label, markets={label: (correct, total)}
    )
