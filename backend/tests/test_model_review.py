"""Daily model review: sections render from fixture data, API is admin-only, task emails."""

from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth import get_current_user, require_admin
from app.core.database import get_db
from app.models.database_models import BetSource, BetType, YetAIBet
from app.models.predictions_models import PointsActuals, PointsProjections
from app.services import model_review_service as ms
from tests.auto_pick.conftest import sqlite_db  # noqa: F401  (fixture)

TODAY = date(2026, 11, 13)
YESTERDAY = TODAY - timedelta(days=1)
SETTLED = datetime(2026, 11, 12, 20, 0)  # naive UTC, yesterday evening ET


def _bet(db, id, status, ref_player=None, **kw):
    pf = {"grading": {"league": "NBA", "market": "player_prop", "stat": "points"}}
    if ref_player is not None:
        pf["projection_ref"] = {
            "table": PointsProjections.__tablename__,
            "id": 999,  # id is gone: the key columns must still find the row
            "date": YESTERDAY.isoformat(),
            "player_id": ref_player,
            "stat": "points",
        }
    db.add(
        YetAIBet(
            id=id,
            title=f"Bet {id}",
            bet_type=BetType.PROP,
            selection="s",
            odds=-110,
            confidence=70,
            status=status,
            source=BetSource.AUTO,
            sport="basketball_nba",
            settled_at=SETTLED,
            created_at=SETTLED,
            commence_time=SETTLED,
            prediction_factors=pf,
            model_version="v-test",
            **kw,
        )
    )


def _fake_other_sports(db, start, end):
    row = lambda p, l, a, who: ms._row(p, l, a, "over", ("t", who), who)  # noqa: E731
    return {
        ("NHL", "player_prop", "saves"): ("ou", [row(30.0, 25.5, 24.0, "G. Goalie")]),
        ("NFL", "player_prop", "passing_yards"): (
            "ou",
            [row(280.0, 250.5, 300.0, "QB Smith")],
        ),
    }


@pytest.fixture
def review_db(sqlite_db, monkeypatch):  # noqa: F811
    db = sqlite_db
    # 40 NBA points calls yesterday: players 0-9 hit (actual 25), 10-39 miss (actual 10).
    for i in range(40):
        extra = {"player_name": f"P{i}", "projected_points": 30.0}
        db.add(
            PointsProjections(
                date=YESTERDAY,
                player_id=i,
                fanduel_line=20.5,
                fanduel_over_under="over",
                **extra,
            )
        )
        db.add(
            PointsActuals(
                date=YESTERDAY,
                player_id=i,
                actual_points=25.0 if i < 10 else 10.0,
                **extra,
            )
        )
    _bet(db, "w1", "won")
    _bet(db, "w2", "won")
    _bet(db, "w3", "won", ref_player=20)  # bet won, projection (over, actual 10) lost
    _bet(db, "l1", "lost", ref_player=21)  # both lost: agrees
    _bet(db, "v1", "void", result="postponed")
    db.commit()
    monkeypatch.setattr(ms, "LOADERS", (ms._nba_props, _fake_other_sports))
    return db


def test_review_text_has_every_section_and_fixture_numbers(review_db):
    review = ms.build_review(review_db, TODAY)
    text = ms.render_text(review)

    for header in (
        "== YetAI Bets record ==",
        "== Projection accuracy",
        "== Record gate ==",
        "== Biggest misses 2026-11-12 ==",
        "== Bet vs projection disagreements",
        "== Model versions",
        "== CLV ==",
    ):
        assert header in text, header
    # 3-1 at -110: 3*(100/110) - 1 = +1.73u
    assert "last 7d (straight bets): 4 picks, 3-1-0, +1.73u" in text
    assert "voids (30d): 1" in text and "postponed" in text
    # NBA points: 10/40 calls; proj 30 vs mean actual 13.75 -> bias +16.25; line 20.5 MAE 9.00
    assert "NBA/player_prop/points: 10/40 calls 25.0% (below breakeven)" in text
    assert "bias +16.25, MAE 16.25, line MAE 9.00 (n=40)" in text
    assert "NHL/player_prop/saves" in text and "NFL/player_prop/passing_yards" in text
    # withheld key named with why
    assert "WITHHELD NBA/player_prop/points" in text and "shrunk ROI" in text
    # disagreement listed: the bet that won on a projection that lost
    d = review["disagreements"]
    assert d["disagreements"] == 1 and d["rows"][0]["bet_id"] == "w3"
    assert d["checked"] == 2 and d["without_projection_ref"] == 2
    assert "w3 Bet w3: bet won, projection lost" in text
    # misses: ranked by error vs the key's MAE; a 20-point miss leads, saves miss is small
    top = review["misses"]["rows"][0]
    assert (top["key"], top["error"], top["actual"]) == (
        "NBA/player_prop/points",
        20.0,
        10.0,
    )
    assert len(review["misses"]["rows"]) == 10
    assert "v-test" in text
    assert "not stored" not in text


def test_section_failure_is_isolated(review_db, monkeypatch):
    def boom(*a):
        raise RuntimeError("no table")

    monkeypatch.setattr(ms, "_versions_section", boom)
    review = ms.build_review(review_db, TODAY)
    assert review["model_versions"] == {"unavailable": "RuntimeError: no table"}
    text = ms.render_text(review)
    assert "unavailable: RuntimeError: no table" in text
    assert "last 7d" in text  # the other sections still render


def test_html_is_escaped(review_db):
    review = ms.build_review(review_db, TODAY)
    review["bets"]["voids_30d"]["rows"] = [{"id": "x", "title": "<b>", "result": "&"}]
    out = ms.render_html(review)
    assert "<b>" not in out and "&lt;b&gt;" in out


def _client(db, admin: bool):
    from app.api.admin_model_review import router

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    if admin:
        app.dependency_overrides[require_admin] = lambda: {"id": 1, "is_admin": True}
    else:
        app.dependency_overrides[get_current_user] = lambda: {"id": 2}
    return TestClient(app)


def test_api_admin_200_and_non_admin_403(review_db):
    r = _client(review_db, admin=True).get("/api/admin/model-review?date=2026-11-13")
    assert r.status_code == 200
    body = r.json()
    assert body["date"] == "2026-11-13" and "== CLV ==" in body["text"]
    assert (
        _client(review_db, admin=False).get("/api/admin/model-review").status_code
        == 403
    )
    assert (
        _client(review_db, admin=True)
        .get("/api/admin/model-review?date=nope")
        .status_code
        == 422
    )


class _FakeEmail:
    sent: list = []

    def send_email(self, to, subject, html_body, text_body=None):
        _FakeEmail.sent.append((to, subject, html_body))
        return True


def _run_task(db, monkeypatch):
    from app.tasks import model_review as task

    _FakeEmail.sent = []
    monkeypatch.setattr(task, "SessionLocal", lambda: db)
    monkeypatch.setattr(task, "EmailService", _FakeEmail)
    monkeypatch.setattr(db, "close", lambda: None)
    return task.model_review_daily()


def test_task_emails_configured_recipient_once(review_db, monkeypatch):
    monkeypatch.setenv("MODEL_REVIEW_EMAIL_TO", "owner@example.com")
    monkeypatch.delenv("MODEL_REVIEW_EMAIL_ENABLED", raising=False)
    result = _run_task(review_db, monkeypatch)
    assert result["sent"] == 1
    ((to, subject, body),) = _FakeEmail.sent
    assert to == "owner@example.com" and "model review" in subject and "<pre" in body


def test_task_kill_switch_sends_nothing(review_db, monkeypatch):
    monkeypatch.setenv("MODEL_REVIEW_EMAIL_TO", "owner@example.com")
    monkeypatch.setenv("MODEL_REVIEW_EMAIL_ENABLED", "false")
    assert _run_task(review_db, monkeypatch)["sent"] == 0
    assert _FakeEmail.sent == []


def test_beat_entry_runs_after_scorecard():
    from app.celery_app import celery_app

    entry = celery_app.conf.beat_schedule["model_review_daily"]
    assert entry["task"] == "model_review.daily"
    assert (entry["schedule"].hour, entry["schedule"].minute) == ({9}, {45})


def test_lookup_matches_json_round_tripped_datetime_ref():
    # projection_ref lives in a JSON column: a QB row's datetime game_date comes back
    # as an ISO string with a time, and must still hit the date-keyed index.
    import json

    ident = ("pred_nfl_qb", ms._norm(datetime(2026, 11, 9)), 42)
    index = {tuple(str(i) for i in ident): ("ou", {"label": "QB 42"})}
    ref = json.loads(
        json.dumps(
            {
                "table": "pred_nfl_qb",
                "game_date": datetime(2026, 11, 9),
                "qb_player_id": 42,
            },
            default=lambda d: d.isoformat(),
        )
    )
    assert ref["game_date"] == "2026-11-09T00:00:00"
    assert ms._lookup(index, ref) == ("ou", {"label": "QB 42"})


def test_nba_totals_and_spread_report_each_model_version_as_its_own_row(
    sqlite_db,
):  # noqa: F811
    from app.models.predictions_models import (
        NBASpreadActuals,
        NBASpreadProjections,
        NBATotalsActuals,
        NBATotalsProjections,
    )

    for i, version in enumerate(["totals-anchor-v1", None]):
        names = dict(home_team_name=f"H{i}", away_team_name=f"A{i}")
        sqlite_db.add(
            NBATotalsProjections(
                game_date=YESTERDAY,
                projected_total=230.0,
                market_total=225.0,
                model_version=version,
                **names,
            )
        )
        sqlite_db.add(
            NBATotalsActuals(
                game_date=YESTERDAY,
                actual_total=228,
                projected_total=230.0,
                market_total=225.0,
                **names,
            )
        )
        sqlite_db.add(
            NBASpreadProjections(
                game_date=YESTERDAY,
                projected_margin=5.0,
                home_win_prob=0.6,
                market_spread_home=-3.0,
                recommendation="HOME",
                model_version="spread-anchor-v1" if version else "elo-pace-v1",
                **names,
            )
        )
        sqlite_db.add(
            NBASpreadActuals(
                game_date=YESTERDAY,
                home_score=110,
                away_score=100,
                actual_margin=10,
                home_won=True,
                **names,
            )
        )
    sqlite_db.commit()

    tot = ms._nba_totals(sqlite_db, YESTERDAY, YESTERDAY)
    spr = ms._nba_spread(sqlite_db, YESTERDAY, YESTERDAY)
    assert set(tot) == {
        ("NBA", "total", "version totals-anchor-v1"),
        ("NBA", "total", "version none"),
    }
    assert set(spr) == {
        ("NBA", "spread", "version spread-anchor-v1"),
        ("NBA", "spread", "version elo-pace-v1"),
    }
    assert all(len(rows) == 1 for _, rows in tot.values())

    from app.services.auto_pick import record_gate

    assert record_gate.key_label(("NBA", "total", "version none")) == (
        "NBA/total/version none"
    )
    # sections still run over these keys
    cur = ms.load_rows(sqlite_db, YESTERDAY, YESTERDAY)
    assert ms._misses_section(sqlite_db, TODAY, cur)["rows"]
    ms._disagreements_section(sqlite_db, TODAY, cur)


def test_gate_section_reports_version_records_and_anchor_fit(sqlite_db):  # noqa: F811
    gate = ms._gate_section(sqlite_db, TODAY)
    for k in ("nba_totals", "nba_spread"):
        assert gate[k]["picks"] == 0 and gate[k]["calls_published"] is False
    assert "nba_totals_bias" not in gate
    assert set(gate["nba_totals_anchor"]) == {"k", "a", "n"}
    assert set(gate["nba_spread_anchor"]) == {"k", "a", "n"}
