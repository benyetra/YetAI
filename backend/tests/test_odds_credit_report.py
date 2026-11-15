"""Credit report: bill-based rate, counter fallback, run-out vs reset, reset dates."""

from datetime import date

import pytest

from app.services import odds_api_budget as budget
from app.services import odds_credit_report as rep

TODAY = date(2026, 11, 15)


class FakeRedis:
    def __init__(self):
        self.d = {}

    def set(self, k, v, ex=None, nx=False):
        if nx and k in self.d:
            return None
        self.d[k] = str(v)
        return True

    def get(self, k):
        return self.d.get(k)

    def hgetall(self, k):
        return self.d.get(k, {})


@pytest.fixture
def r(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(budget, "_sync_redis", lambda: fake)
    monkeypatch.setenv("ODDS_API_CYCLE_START", "2026-11-14")
    monkeypatch.delenv("ODDS_API_CYCLE_CREDITS", raising=False)
    return fake


def _first(r, day, val):
    r.d[f"odds:quota:remaining_first:{day}"] = str(val)


def test_snapshot_keeps_first_and_latest(r):
    rep.snapshot_quota({"remaining": 900}, "2026-11-15")
    rep.snapshot_quota({"remaining": 850}, "2026-11-15")
    assert r.d["odds:quota:remaining:2026-11-15"] == "850"
    assert r.d["odds:quota:remaining_first:2026-11-15"] == "900"


def test_rate_from_bill_and_runout_before_reset(r):
    _first(r, "2026-11-12", 98000)
    _first(r, "2026-11-14", 96000)
    _first(r, "2026-11-15", 94000)  # 4000 over 3 days (from 11-12) -> 1333/day
    r.d["odds:budget:credits:2026-11-14"] = "300"
    r.d["odds:budget:callers:2026-11-14"] = {"etl.nba": 100, "api.odds": 200}
    s = rep.credits_summary(TODAY, {"remaining": 40000})
    assert s["rate_source"] == "bill" and round(s["rate_7d"]) == 1333
    assert s["yesterday_billed"] == 2000 and s["yesterday_unrecorded"] == 1700
    assert list(s["yesterday_by_group"]) == ["api.odds", "etl.nba"]
    assert s["projected_runout"] == "2026-12-15" and s["next_reset"] == "2026-12-14"
    assert s["runs_out_before_reset"] is False
    assert s["recommended_daily"] == (40000 - 5000) // 29


def test_runs_out_before_reset(r):
    _first(r, "2026-11-14", 5000)
    _first(r, "2026-11-15", 3000)
    s = rep.credits_summary(TODAY, {"remaining": 2000})
    assert s["projected_runout"] == "2026-11-16" and s["runs_out_before_reset"]
    assert s["recommended_daily"] == 0


def test_fallback_to_counter(r):
    for d, n in (("2026-11-14", 700), ("2026-11-13", 700)):
        r.d[f"odds:budget:credits:{d}"] = str(n)
    s = rep.credits_summary(TODAY, {"remaining": 1000})
    assert s["rate_source"] == "counter" and s["rate_7d"] == 200
    assert s["yesterday_billed"] is None and s["yesterday_unrecorded"] is None
    assert s["projected_runout"] == "2026-11-20"


def test_no_quota_no_projection(r):
    s = rep.credits_summary(TODAY, None)
    assert s["remaining"] is None and s["projected_runout"] is None
    assert s["runs_out_before_reset"] is False and s["recommended_daily"] is None


@pytest.mark.parametrize(
    "start,today,expected",
    [
        ("2026-11-14", "2026-12-14", "2027-01-14"),  # reset day itself -> next month
        ("2026-12-31", "2027-01-05", "2027-01-31"),
        ("2026-12-31", "2027-02-01", "2027-02-28"),  # month-end clamp
        ("2026-12-31", "2027-03-01", "2027-03-31"),  # no clamp drift
        ("2026-11-14", "2026-11-01", "2026-11-14"),
    ],
)
def test_next_reset(start, today, expected):
    got = rep.next_reset(date.fromisoformat(today), date.fromisoformat(start))
    assert got.isoformat() == expected


def test_unrecorded_uses_the_same_window_as_the_bill(r):
    # Readings at ~14:40Z: the bill covers yesterday 14:40Z -> today 14:40Z.
    _first(r, "2026-11-14", 96000)
    _first(r, "2026-11-15", 94000)
    r.d["odds:quota:counter_at_first:2026-11-14"] = "100"  # recorded before 14:40Z
    r.d["odds:quota:counter_at_first:2026-11-15"] = "50"
    r.d["odds:budget:credits:2026-11-14"] = "300"
    s = rep.credits_summary(TODAY, {"remaining": 94000})
    assert s["yesterday_billed"] == 2000
    assert s["yesterday_unrecorded"] == 2000 - (300 - 100 + 50)


def test_first_snapshot_stores_counter_at_that_moment(r):
    r.d["odds:budget:credits:2026-11-15"] = "42"
    rep.snapshot_quota({"remaining": 900}, "2026-11-15")
    r.d["odds:budget:credits:2026-11-15"] = "60"
    rep.snapshot_quota({"remaining": 880}, "2026-11-15")
    assert r.d["odds:quota:counter_at_first:2026-11-15"] == "42"
