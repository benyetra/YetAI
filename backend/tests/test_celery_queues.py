"""Queue routing, the worker role command, and the single-beat guard."""

from datetime import datetime, timedelta

import pytest

from app import worker_role
from app.celery_app import BETS_QUEUE, BETS_QUEUE_TASKS, DEFAULT_QUEUE, celery_app

# Importing the include list registers every task.
celery_app.loader.import_default_modules()


def _queue(name: str) -> str:
    return celery_app.amqp.router.route({}, name)["queue"].name


def _app_tasks():
    return sorted(n for n in celery_app.tasks if not n.startswith("celery."))


def test_time_critical_tasks_route_to_bets_queue():
    for name in BETS_QUEUE_TASKS:
        assert name in celery_app.tasks, f"routed task {name} is not registered"
        assert _queue(name) == BETS_QUEUE


def test_everything_else_routes_to_default_queue():
    others = [n for n in _app_tasks() if n not in BETS_QUEUE_TASKS]
    assert len(others) > 50
    assert {_queue(n) for n in others} == {DEFAULT_QUEUE}


def test_guard_yetai_bets_and_auto_pick_namespaces_are_routed():
    """A new yetai_bets.* / auto_pick.* task must be added to BETS_QUEUE_TASKS."""
    missing = [
        n
        for n in _app_tasks()
        if n.startswith(("yetai_bets.", "auto_pick.")) and _queue(n) != BETS_QUEUE
    ]
    assert not missing, f"add to BETS_QUEUE_TASKS in celery_app.py: {missing}"


def test_guard_short_expiry_beat_entries_are_routed():
    """A beat entry that expires within 15 min is time-critical by construction:
    behind an hour-long ETL task it would never run. It must go to the bets queue
    (the queue watch is the one deliberate exception: it watches that queue)."""
    exempt = {"app.tasks.health.bets_queue_watch"}
    late = [
        (key, e["task"])
        for key, e in celery_app.conf.beat_schedule.items()
        if (e.get("options") or {}).get("expires", 10**9) <= 900
        and e["task"] not in exempt
        and _queue(e["task"]) != BETS_QUEUE
    ]
    assert not late, f"short-expiry beat entries off the bets queue: {late}"


def test_queue_watch_runs_on_default_queue():
    assert _queue("app.tasks.health.bets_queue_watch") == DEFAULT_QUEUE


def test_worker_without_Q_consumes_both_queues():
    """Rollout step 1: today's start command (no -Q) must keep consuming the bets
    queue, or bets stop settling the moment the routes deploy."""
    assert {q.name for q in celery_app.conf.task_queues} == {DEFAULT_QUEUE, BETS_QUEUE}


def test_queues_have_distinct_routing_keys():
    """Queue(name) alone binds both queues to the "celery" key, so a message
    published by routing key would be delivered to both: a duplicate run."""
    keys = {q.name: q.routing_key for q in celery_app.conf.task_queues}
    assert keys == {DEFAULT_QUEUE: DEFAULT_QUEUE, BETS_QUEUE: BETS_QUEUE}


def test_time_critical_beat_entries_expire():
    sched = celery_app.conf.beat_schedule
    for key in (
        "auto_pick_yetai_bets_daily",
        "auto_pick_yetai_bets_topup",
        "expire_pending_yetai_picks",
        "settle-yetai-bets",
        "yetai-settlement-alert",
        "nba-close-capture",
        "fair-price-shadow-flag",
    ):
        expires = sched[key]["options"]["expires"]
        # Well under the 24h visibility_timeout redelivery of a killed run.
        assert 0 < expires < 86400 / 2, key


# --- worker role --------------------------------------------------------------

PROD_BEFORE = (
    "celery -A app.celery_app worker --beat --loglevel=info --concurrency=1 "
    "--max-memory-per-child=800000 --max-tasks-per-child=8"
).split()


def test_role_constants_match_celery_app():
    assert worker_role.DEFAULT_QUEUE == DEFAULT_QUEUE
    assert worker_role.BETS_QUEUE == BETS_QUEUE


@pytest.mark.parametrize("role", [None, "", "  ", "all", "ALL"])
def test_unset_role_keeps_todays_command(role):
    assert worker_role.build_argv(role) == PROD_BEFORE


def test_etl_role_beat_and_default_queue_only():
    argv = worker_role.build_argv("etl")
    assert argv[: len(PROD_BEFORE)] == PROD_BEFORE
    assert argv[argv.index("-Q") + 1] == DEFAULT_QUEUE
    assert argv.count("-Q") == 1


def test_bets_role_bets_queue_only_never_beat():
    argv = worker_role.build_argv("bets")
    assert argv[:4] == ["celery", "-A", "app.celery_app", "worker"]
    assert argv[argv.index("-Q") + 1] == BETS_QUEUE
    assert "--beat" not in argv and "-B" not in argv
    assert "--concurrency=1" in argv
    for flag in ("--beat", "-B"):
        with pytest.raises(SystemExit):
            worker_role.build_argv("bets", [flag])


def test_extra_args_appended_and_unknown_role_rejected():
    assert worker_role.build_argv("etl", ["--pool=solo"])[-1] == "--pool=solo"
    with pytest.raises(SystemExit):
        worker_role.build_argv("bet")


# --- single beat --------------------------------------------------------------


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    def get(self, k):
        return self.store.get(k)

    def expire(self, k, ttl):
        return k in self.store

    def delete(self, k):
        self.store.pop(k, None)


def _scheduler(fake, token):
    from app.core.db_scheduler import DatabaseScheduler

    s = DatabaseScheduler.__new__(DatabaseScheduler)  # no beat store / DB
    s._leader_client = fake
    s._leader_token = token
    s._leader = True
    return s


def test_only_one_beat_sends(monkeypatch):
    from celery.beat import PersistentScheduler

    sent = []
    monkeypatch.setattr(PersistentScheduler, "tick", lambda self, *a, **k: 300)
    monkeypatch.setattr(
        PersistentScheduler,
        "apply_entry",
        lambda self, entry, producer=None: sent.append(self._leader_token),
    )
    monkeypatch.setattr(PersistentScheduler, "close", lambda self: None)
    fake = _FakeRedis()
    a, b = _scheduler(fake, "a"), _scheduler(fake, "b")
    entry = type("E", (), {"name": "settle-yetai-bets", "task": "yetai_bets.settle"})
    for s in (a, b):
        assert s.tick() <= 30  # wakes often enough to refresh the TTL
        s.apply_entry(entry)
    assert sent == ["a"]
    a.close()  # clean stop hands over
    b.tick()
    b.apply_entry(entry)
    assert sent == ["a", "b"]


def test_beat_fails_open_when_redis_errors():
    class Broken:
        def set(self, *a, **k):
            raise ConnectionError("down")

    s = _scheduler(Broken(), "a")
    assert s._claim_leadership() is True


def test_queue_watch_alerts_once_per_window(monkeypatch):
    from app.tasks import health

    sent = []
    monkeypatch.setattr(health, "bets_queue_depth", lambda: 30)

    class Row:
        created_at = None

    last = {"row": None}

    class DB:
        def close(self):
            pass

    import app.core.database as database
    import app.tasks.yetai_settlement_alert as alert

    monkeypatch.setattr(database, "SessionLocal", lambda: DB())
    monkeypatch.setattr(alert, "_last_alert", lambda db, name: last["row"])
    monkeypatch.setattr(alert, "_send", lambda db, msg, sig, **kw: sent.append(kw))

    assert health.bets_queue_watch()["sent"] is True
    Row.created_at = datetime.utcnow() - timedelta(hours=1)
    last["row"] = Row()
    assert health.bets_queue_watch()["sent"] is False
    monkeypatch.setattr(health, "bets_queue_depth", lambda: 0)
    assert health.bets_queue_watch() == {"queue": BETS_QUEUE, "depth": 0, "sent": False}
    assert sent == [
        {"task_name": health.WATCH_TASK_NAME, "label": "YetAI bets queue watch"}
    ]
