"""One guarded, recording path for every Odds API call (credit counter)."""

import asyncio
import logging
from unittest.mock import patch

import pytest

from app.services import odds_api_budget as b
from app.services import odds_api_sync as s


class FakeRedis:
    def __init__(self):
        self.kv, self.h = {}, {}

    def get(self, k):
        return self.kv.get(k)

    def hgetall(self, k):
        return {f: str(v) for f, v in self.h.get(k, {}).items()}

    def pipeline(self):
        return FakePipe(self)


class FakePipe:
    def __init__(self, r):
        self.r, self.ops = r, []

    def incrby(self, k, n):
        def op():
            self.r.kv[k] = int(self.r.kv.get(k, 0)) + n
            return self.r.kv[k]

        self.ops.append(op)

    def hincrby(self, k, f, n):
        h = self.r.h.setdefault(k, {})
        self.ops.append(lambda: h.__setitem__(f, h.get(f, 0) + n))

    def expire(self, k, t):
        self.ops.append(lambda: True)

    def execute(self):
        return [op() for op in self.ops]


@pytest.fixture
def redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(b, "_sync_redis", lambda: r)  # never the real Redis
    monkeypatch.setattr(b, "_logged_day", {})
    return r


@pytest.mark.parametrize(
    "caller,group",
    [
        ("etl.nba.fanduel_lines.odds." + "a1" * 16, "etl.nba"),
        (
            "etl.nfl.anytime_td_betting.americanfootball_nfl/events/"
            + "ab" * 12
            + "/odds",
            "etl.nfl",
        ),
        ("etl.nhl.event_odds." + "0f" * 12, "etl.nhl"),
        ("games_sync.sync_all_games", "games_sync"),
        ("api.odds.basketball_nba", "api.odds"),
        ("api.player_props.markets.basketball_nba", "api.player_props"),
        ("optimized_odds_api", "optimized_odds_api"),
        ("script.odds_history_backfill", "script"),
        ("quota.read", "quota"),
        ("unknown", "unknown"),
        ("", "unknown"),
    ],
)
def test_caller_group(caller, group):
    assert b.caller_group(caller) == group


def test_sync_and_async_share_one_counter(redis):
    b.record_sync(3, "etl.nba.x")
    asyncio.run(b.record_async(2, "api.odds.nba"))
    assert b.get_daily_usage_sync() == 5
    assert asyncio.run(b.get_daily_usage_async()) == 5
    day = b._today()
    assert b.get_usage_by_group_sync(day) == {"etl.nba": 3, "api.odds": 2}


def test_zero_and_garbage_cost_record_zero(redis):
    b.record_sync(0, "x")
    b.record_sync("junk", "x")
    b.record_sync(-4, "x")
    assert b.get_daily_usage_sync() == 0


class Resp:
    def __init__(self, status=200, last=None, body=None):
        self.status_code, self.ok = status, status < 400
        self.headers = {} if last is None else {"X-Requests-Last": str(last)}
        self._body = body if body is not None else []

    def json(self):
        return self._body

    def raise_for_status(self):
        raise RuntimeError("http")


def _get(redis, resp, **kw):
    with patch.object(s.requests, "get", return_value=resp) as g:
        out = s.sync_odds_get("https://x/odds", snapshot=False, **kw)
    return out, g


def test_free_call_records_zero_and_missing_header_records_estimate(redis):
    _get(redis, Resp(last=0))
    assert b.get_daily_usage_sync() == 0
    _get(redis, Resp(last=None), estimated_cost=3)
    assert b.get_daily_usage_sync() == 3
    # error without header costs nothing; error with header is billed
    _get(redis, Resp(500, last=None), estimated_cost=3, raise_for_status=False)
    assert b.get_daily_usage_sync() == 3
    _get(redis, Resp(422, last=2), raise_for_status=False)
    assert b.get_daily_usage_sync() == 5


def test_refusal_logs_once_per_day(redis, caplog, monkeypatch):
    monkeypatch.setattr(b, "DAILY_CREDIT_BUDGET", 10)
    redis.kv[b._budget_key()] = 9
    with caplog.at_level(logging.DEBUG, logger=b.logger.name):
        assert [b.guard_sync("c", 3) for _ in range(3)] == [False] * 3
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "budget reached" in warnings[0].getMessage()
    assert b.guard_sync("c", 1) is True  # 9 + 1 <= 10


def test_dead_counter_fails_open_and_warns_once(caplog, monkeypatch):
    monkeypatch.setattr(b, "_client", None)
    monkeypatch.setattr(b, "_logged_day", {})
    monkeypatch.setattr(b, "_sync_redis", lambda: None)
    with caplog.at_level(logging.WARNING, logger=b.logger.name):
        assert b.guard_sync("c") and b.guard_sync("c")
    assert len([r for r in caplog.records if "unreachable" in r.getMessage()]) == 1


def test_enforce_budget_false_records_but_never_refuses(redis, monkeypatch):
    monkeypatch.setattr(b, "DAILY_CREDIT_BUDGET", 1)
    redis.kv[b._budget_key()] = 1
    out, g = _get(redis, Resp(last=10), enforce_budget=False, estimated_cost=10)
    assert out is not None and g.called
    assert b.get_daily_usage_sync() == 11
    out, g = _get(redis, Resp(last=10), estimated_cost=10)
    assert out is None and not g.called  # default still refuses


class FakeAioResp:
    status = 200
    headers = {"x-requests-last": "3"}

    async def json(self, content_type=None):
        return [{"id": "g"}]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeSession:
    def __init__(self):
        self.calls = 0

    def get(self, url, **kw):
        self.calls += 1
        return FakeAioResp()


def test_async_odds_get_records_and_refuses(redis, monkeypatch):
    sess = FakeSession()
    status, headers, body = asyncio.run(
        s.async_odds_get(sess, "https://x", caller="api.odds.nba", estimated_cost=3)
    )
    assert (status, body) == (200, [{"id": "g"}])
    assert b.get_daily_usage_sync() == 3
    monkeypatch.setattr(b, "DAILY_CREDIT_BUDGET", 3)
    assert asyncio.run(s.async_odds_get(sess, "https://x")) is None
    assert sess.calls == 1  # refused call made no HTTP request


def test_odds_service_returns_empty_when_budget_refuses(redis, monkeypatch):
    from app.services.odds_api_service import OddsAPIService

    monkeypatch.setattr(b, "DAILY_CREDIT_BUDGET", 0)

    async def run():
        svc = OddsAPIService("k")
        svc.session = FakeSession()
        return await svc.get_odds("basketball_nba"), await svc.get_sports(), svc

    odds, sports, svc = asyncio.run(run())
    assert odds == [] and sports == [] and svc.session.calls == 0


def test_read_live_quota(redis):
    resp = Resp(last=0)
    resp.headers.update({"x-requests-remaining": "400", "x-requests-used": "100"})
    with patch.object(s.requests, "get", return_value=resp):
        q = s.read_live_quota()
    assert (q["remaining"], q["used"]) == (400, 100) and q["at"]
    assert b.get_daily_usage_sync() == 0
