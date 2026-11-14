from unittest.mock import MagicMock, patch

from app.services.etl.nba import calculate_prediction_accuracy as cpa


def _run(monkeypatch, env=None, **kwargs):
    if env is None:
        monkeypatch.delenv("NBA_ACCURACY_BACKFILL_DAYS", raising=False)
    else:
        monkeypatch.setenv("NBA_ACCURACY_BACKFILL_DAYS", env)
    with (
        patch.object(cpa, "SessionLocal", return_value=MagicMock()),
        patch.object(cpa, "calculate_accuracy_for_date") as grade,
        patch.object(cpa, "generate_accuracy_report", return_value={}) as report,
    ):
        cpa.run(**kwargs)
    return grade.call_count, report.call_args.kwargs["days_back"]


def test_default_grades_yesterday_and_one_more_day(monkeypatch):
    assert _run(monkeypatch) == (2, 7)


def test_env_widens_backfill(monkeypatch):
    assert _run(monkeypatch, env="10") == (10, 10)


def test_bad_env_falls_back_to_default(monkeypatch):
    assert _run(monkeypatch, env="abc") == (2, 7)


def test_explicit_argument_wins(monkeypatch):
    assert _run(monkeypatch, env="10", backfill_days=3) == (3, 7)


# --- H-8: every NBA grader re-grades grading_dates("nba"), not only yesterday ---
from datetime import date  # noqa: E402

from app.services.etl.grading_window import grading_dates  # noqa: E402


def _expected_dates(monkeypatch, n="3"):
    monkeypatch.setenv("NBA_GRADING_LOOKBACK_DAYS", n)
    return grading_dates("nba")


def test_store_spread_actuals_regrades_lookback(monkeypatch):
    from app.services.etl.nba import store_spread_actuals as ssa

    want = _expected_dates(monkeypatch)
    seen = []
    monkeypatch.setattr(ssa, "fetch_final_scores", lambda d: seen.append(d) or [])
    monkeypatch.setattr(ssa, "SessionLocal", lambda: MagicMock())
    ssa.run()
    assert seen == want and len(want) == 3


def test_store_actuals_regrades_lookback(monkeypatch):
    from app.services.etl.nba import store_actuals as sa

    want = _expected_dates(monkeypatch)
    seen = []
    monkeypatch.setattr(sa, "SessionLocal", lambda: MagicMock())
    monkeypatch.setattr(
        sa, "_store_stat", lambda db, k, cfg, d: seen.append(d) or {"written": 0}
    )
    monkeypatch.setattr(sa, "_store_pra", lambda db, d: {"written": 0})
    out = sa.run()
    assert sorted(set(seen)) == want
    assert out["date"] == want[-1].isoformat()


def test_totals_tracker_regrades_lookback(monkeypatch):
    from app.services.etl.nba import totals_accuracy_tracker as tt

    want = _expected_dates(monkeypatch)
    seen = []
    fake_db = MagicMock()
    fake_db.query.return_value.filter_by.side_effect = lambda **kw: (
        seen.append(kw["game_date"]) or MagicMock(all=lambda: [])
    )
    monkeypatch.setattr(tt, "db", fake_db)
    monkeypatch.setattr(
        tt, "_today", lambda: want[-1] + __import__("datetime").timedelta(days=1)
    )
    tt.update_yesterdays_results()
    assert seen == want


def test_prop_grader_env_falls_back_to_grading_lookback(monkeypatch):
    monkeypatch.delenv("NBA_ACCURACY_BACKFILL_DAYS", raising=False)
    monkeypatch.setenv("NBA_GRADING_LOOKBACK_DAYS", "5")
    assert cpa._backfill_days() == 5
    monkeypatch.setenv("NBA_ACCURACY_BACKFILL_DAYS", "4")
    assert cpa._backfill_days() == 4
