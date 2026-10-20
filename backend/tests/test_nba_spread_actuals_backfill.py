"""ESPN final-score parsing and the spread actuals backfill."""

from __future__ import annotations

from datetime import date

from app.services.etl.nba._espn import parse_final_scores
from scripts.nba_backfill_spread_actuals import collect, season_counts


def _event(season_type, home, away, completed=True):
    return {
        "season": {"type": season_type},
        "competitions": [
            {
                "status": {"type": {"completed": completed}},
                "competitors": [
                    {"homeAway": "home", "team": {"id": home[0]}, "score": home[1]},
                    {"homeAway": "away", "team": {"id": away[0]}, "score": away[1]},
                ],
            }
        ],
    }


def test_parse_final_scores_filters_and_names():
    data = {
        "events": [
            _event(2, ("12", "110"), ("20", "104")),  # Clippers vs 76ers
            _event(1, ("2", "100"), ("18", "90")),  # preseason
            _event(3, ("2", "99"), ("18", "101"), completed=False),  # in progress
            _event(5, ("19", "120"), ("1", "95")),  # play-in
            _event(2, ("99", "80"), ("2", "70")),  # unmapped (exhibition)
        ]
    }
    assert parse_final_scores(data) == [
        {
            "home_team_name": "Los Angeles Clippers",
            "away_team_name": "Philadelphia 76ers",
            "home_score": 110,
            "away_score": 104,
        },
        {
            "home_team_name": "Orlando Magic",
            "away_team_name": "Atlanta Hawks",
            "home_score": 120,
            "away_score": 95,
        },
    ]


def test_collect_skips_offseason_and_reports_failures():
    calls = []

    def fetch(d):
        calls.append(d)
        if d == date(2025, 6, 20):
            raise RuntimeError("boom")
        return [
            {
                "home_team_name": "Boston Celtics",
                "away_team_name": "New York Knicks",
                "home_score": 100,
                "away_score": 103,
            }
        ]

    # 2025-06-20 (Finals) → 2025-07-02 (offseason).
    rows, failed = collect(date(2025, 6, 19), date(2025, 7, 2), fetch, pause=0)
    assert failed == [date(2025, 6, 20)]
    assert {d for d in calls} == {date(2025, 6, d) for d in range(19, 31)}
    assert all(r["actual_margin"] == -3 and r["home_won"] is False for r in rows)
    assert season_counts(rows) == {2024: len(rows)}


def test_store_spread_actuals_writes_every_espn_final(monkeypatch):
    from unittest.mock import MagicMock, patch

    from app.services.etl.nba import store_spread_actuals as ssa

    finals = [
        {
            "home_team_name": "Los Angeles Clippers",
            "away_team_name": "Utah Jazz",
            "home_score": 101,
            "away_score": 99,
        }
    ]
    monkeypatch.setattr(ssa, "fetch_final_scores", lambda d: finals)
    monkeypatch.setattr(ssa, "SessionLocal", lambda: MagicMock())
    with patch.object(ssa, "upsert_many") as um:
        out = ssa.run(date(2026, 10, 21))
    assert out["spreads_written"] == 1
    (row,) = um.call_args[0][2]
    assert row["actual_margin"] == 2 and row["home_won"] is True
    assert row["game_date"] == date(2026, 10, 21)
