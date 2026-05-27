"""Tests for accuracy_shared bucket builders.

Covers the three primitives used by every per-league accuracy service:
ou_call_bucket, hit_rate_bucket, mae_bucket. Each is a pure function
over row-dicts so we don't need a DB.
"""

from __future__ import annotations

from app.services import accuracy_shared as ash


# ---------------------------------------------------------------------------
# pct + tone_for_rate
# ---------------------------------------------------------------------------


def test_pct_formats_rate_as_rounded_percent():
    assert ash.pct(0.8) == "80%"
    assert ash.pct(0.666) == "67%"
    assert ash.pct(None) == "—"
    assert ash.pct(0) == "0%"


def test_tone_for_rate_good_at_60_plus():
    assert ash.tone_for_rate(0.6) == "good"
    assert ash.tone_for_rate(0.59) == "warn"
    assert ash.tone_for_rate(0.0) == "warn"
    assert ash.tone_for_rate(None) == "neutral"


# ---------------------------------------------------------------------------
# ou_call_bucket
# ---------------------------------------------------------------------------


def test_ou_call_bucket_counts_correct_over_picks():
    rows = [
        {"line": 5.5, "pick": "over", "actual": 7.0, "projected": 6.5},
    ]
    out = ash.ou_call_bucket(
        rows,
        line_field="line",
        pick_field="pick",
        actual_field="actual",
        projected_field="projected",
        label="Test O/U",
        key="t_ou",
    )
    assert out.key == "t_ou"
    assert out.label == "Test O/U"
    assert out.primary == "1/1 · 100%"
    assert out.tone == "good"


def test_ou_call_bucket_push_drops_from_total():
    rows = [
        {"line": 6.0, "pick": "over", "actual": 6.0, "projected": 6.0},
    ]
    out = ash.ou_call_bucket(
        rows,
        line_field="line",
        pick_field="pick",
        actual_field="actual",
        projected_field="projected",
        label="X",
        key="x",
    )
    assert "1 push" in out.secondary
    assert out.primary == "0/0 · —"


def test_ou_call_bucket_skips_rows_without_actuals():
    rows = [
        {"line": 5.5, "pick": "over", "actual": 7.0, "projected": 6.0},
        {"line": 5.5, "pick": "over", "actual": None, "projected": 6.0},
    ]
    out = ash.ou_call_bucket(
        rows,
        line_field="line",
        pick_field="pick",
        actual_field="actual",
        projected_field="projected",
        label="X",
        key="x",
    )
    assert out.primary == "1/1 · 100%"


def test_ou_call_bucket_computes_mae():
    rows = [
        {"line": 5.5, "pick": "over", "actual": 7.0, "projected": 6.0},  # |6-7|=1
        {"line": 5.5, "pick": "under", "actual": 4.0, "projected": 4.0},  # |4-4|=0
    ]
    out = ash.ou_call_bucket(
        rows,
        line_field="line",
        pick_field="pick",
        actual_field="actual",
        projected_field="projected",
        label="X",
        key="x",
    )
    assert "MAE 0.50" in out.secondary


def test_ou_call_bucket_accepts_short_o_u_picks():
    rows = [
        {"line": 5.5, "pick": "o", "actual": 7.0, "projected": 6.0},
        {"line": 5.5, "pick": "u", "actual": 4.0, "projected": 4.0},
    ]
    out = ash.ou_call_bucket(
        rows,
        line_field="line",
        pick_field="pick",
        actual_field="actual",
        projected_field="projected",
        label="X",
        key="x",
    )
    assert out.primary == "2/2 · 100%"


# ---------------------------------------------------------------------------
# hit_rate_bucket
# ---------------------------------------------------------------------------


def test_hit_rate_bucket_basic():
    rows = [
        {"projected": 1, "actual": 1},
        {"projected": 1, "actual": 0},
        {"projected": 2, "actual": 3},
    ]
    out = ash.hit_rate_bucket(
        rows,
        actual_field="actual",
        projected_field="projected",
        threshold=1,
        label="Hits",
        key="hits",
        secondary="Batters projected for ≥1 hit",
    )
    assert out.primary == "2/3 · 67%"
    assert out.tone == "good"


def test_hit_rate_bucket_ignores_zero_projected():
    rows = [
        {"projected": 0, "actual": 5},
        {"projected": 1, "actual": 1},
    ]
    out = ash.hit_rate_bucket(
        rows,
        actual_field="actual",
        projected_field="projected",
        threshold=1,
        label="X",
        key="x",
        secondary="",
    )
    assert out.primary == "1/1 · 100%"


def test_hit_rate_bucket_skips_missing_actuals():
    rows = [
        {"projected": 1, "actual": None},
        {"projected": 1, "actual": 1},
    ]
    out = ash.hit_rate_bucket(
        rows,
        actual_field="actual",
        projected_field="projected",
        threshold=1,
        label="X",
        key="x",
        secondary="",
    )
    assert out.primary == "1/1 · 100%"


# ---------------------------------------------------------------------------
# mae_bucket
# ---------------------------------------------------------------------------


def test_mae_bucket_basic():
    rows = [
        {"projected": 10, "actual": 12},  # |10-12|=2
        {"projected": 8, "actual": 8},  # 0
    ]
    out = ash.mae_bucket(
        rows,
        projected_field="projected",
        actual_field="actual",
        label="Test MAE",
        key="t_mae",
        unit_label="yards",
    )
    assert out.primary == "MAE 1.00 yards"
    assert out.secondary == "Across 2 graded"
    assert out.tone == "neutral"


def test_mae_bucket_handles_no_graded_rows():
    rows = [
        {"projected": 10, "actual": None},
    ]
    out = ash.mae_bucket(
        rows,
        projected_field="projected",
        actual_field="actual",
        label="X",
        key="x",
    )
    assert out.primary == "—"
    assert out.tone == "neutral"


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------


def test_ou_call_graded_counts_matches_bucket_numerator():
    rows = [
        {"line": 5.5, "pick": "over", "actual": 7.0, "projected": 6.5},
        {"line": 5.5, "pick": "under", "actual": 4.0, "projected": 4.0},
    ]
    c, t = ash.ou_call_graded_counts(
        rows,
        line_field="line",
        pick_field="pick",
        actual_field="actual",
    )
    assert (c, t) == (2, 2)


def test_ou_call_graded_counts_ignores_non_decision_picks():
    rows = [
        {"line": 5.5, "pick": "pass", "actual": 7.0, "projected": 6.5},
        {"line": 5.5, "pick": "lean_over", "actual": 7.0, "projected": 6.5},
        {"line": 5.5, "pick": "over", "actual": 7.0, "projected": 6.5},
    ]
    c, t = ash.ou_call_graded_counts(
        rows,
        line_field="line",
        pick_field="pick",
        actual_field="actual",
    )
    assert (c, t) == (1, 1)


def test_ou_call_graded_breakdown_aligns_with_counts():
    rows = [
        {"line": 5.5, "pick": "over", "actual": 7.0},
        {"line": 5.5, "pick": "pass", "actual": 7.0},
        {"line": 5.5, "pick": "under", "actual": 4.0},
        {"line": 6.0, "pick": "over", "actual": 6.0},
        {"line": None, "pick": "over", "actual": 7.0},
    ]
    bd = ash.ou_call_graded_breakdown(
        rows, line_field="line", pick_field="pick", actual_field="actual"
    )
    c, t = ash.ou_call_graded_counts(
        rows, line_field="line", pick_field="pick", actual_field="actual"
    )
    assert (bd["graded_correct"], bd["graded_total"]) == (c, t)
    assert bd["rows_scanned"] == 5
    assert bd["non_decision_pick"] == 1
    assert bd["push"] == 1
    assert bd["missing_line"] == 1


def test_edge_play_graded_counts_ignores_pass():
    rows = [
        {"pick": "PASS", "graded": True},
        {"pick": "HOME", "graded": True},
    ]
    c, t = ash.edge_play_graded_counts(
        rows,
        pick_field="pick",
        correct_field="graded",
    )
    assert (c, t) == (1, 1)


def test_overview_item_from_totals_no_data():
    out = ash.overview_item_from_totals(sport="mlb", label="MLB", correct=0, total=0)
    assert out["sport"] == "mlb"
    assert out["has_data"] is False
    assert out["primary"] == "No graded projections yet"
    assert out["tone"] == "neutral"


def test_overview_item_from_totals_with_data():
    out = ash.overview_item_from_totals(sport="nba", label="NBA", correct=3, total=4)
    assert out["has_data"] is True
    assert out["graded_count"] == 4
    assert out["primary"] == "75%"
    assert "4 graded picks" in out["secondary"]


def test_assemble_returns_standard_shape():
    bucket = ash.AccuracyBucket(
        key="k",
        label="L",
        primary="1/1 · 100%",
        secondary="",
        tone="good",
    )
    out = ash.assemble(date_str="2026-05-23", buckets=[bucket], available=True)
    assert out == {
        "date": "2026-05-23",
        "available": True,
        "buckets": [
            {
                "key": "k",
                "label": "L",
                "primary": "1/1 · 100%",
                "secondary": "",
                "tone": "good",
            }
        ],
    }
