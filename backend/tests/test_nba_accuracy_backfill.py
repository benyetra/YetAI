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
