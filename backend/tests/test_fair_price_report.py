"""Fair-price shadow report (SQLite): hand-computed maths, sample rules, wiring, script."""

import importlib.util
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.predictions_models import FairPriceShadowFlag as F
from app.models.predictions_models import OddsLineSnapshot as S
from app.services import model_review_service as ms
from app.services.fair_price import report, shadow

TODAY = date(2026, 11, 15)
T0 = datetime(2026, 11, 14, 12, 0)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    S.__table__.create(engine)
    F.__table__.create(engine)
    s = sessionmaker(bind=engine)()
    s.add(  # fresh snapshot so the section is not stale
        S(
            sport="basketball_nba",
            event_id="e",
            market="player_rebounds",
            player_key="p",
            book="fanduel",
            first_seen_at=datetime(2026, 11, 15, 10),
            last_seen_at=datetime(2026, 11, 15, 10),
        )
    )
    s.commit()
    yield s
    s.close()


def flag(db, i, **kw):
    d = dict(
        rule_version=shadow.RULE_VERSION,
        engine_version="t",
        tier="primary",
        sport="basketball_nba",
        event_id=f"ev{i}",
        game_date=date(2026, 11, 14),
        market="player_rebounds",
        player_key=f"p{i}",
        side="o",
        book="fanduel",
        line=5.5,
        price=-110,
        observed_at=T0 + timedelta(minutes=i),
        flagged_at=T0 + timedelta(minutes=i),
        hours_before=2.0,
        fair_prob=0.55,
        ev=0.06,
        playable_to=-120,
        n_books=4,
        devig_method="power",
        weights_version="equal",
        last_qualified_at=T0,
        n_qualified=1,
        is_close=False,
        result="hit",
        clv=0.01,
        units=0.909,
    )
    d.update(kw)
    db.add(F(**d))


def test_hand_computed_maths(db):
    d1, d2 = date(2026, 11, 13), date(2026, 11, 14)
    flag(db, 1, game_date=d1, clv=0.04, price=-110, result="hit")
    flag(db, 2, game_date=d1, clv=0.02, price=100, result="miss")
    flag(db, 3, game_date=d2, clv=-0.01, price=-110, result="hit")
    flag(db, 4, game_date=d2, clv=0.03, price=100, result="push")
    db.commit()
    p = report.section(db, TODAY)["primary"]
    a = p["all"]
    assert a["n"] == 4 and a["clv_n"] == 4
    assert a["clv_mean"] == pytest.approx(0.02)
    assert (a["decided"], a["hits"]) == (3, 2)
    assert a["hit_rate"] == pytest.approx(2 / 3, abs=1e-6)
    units = 2 * (100 / 110) - 1
    assert a["roi"] == pytest.approx(units / 3, abs=1e-5)
    assert p["progress"] == "4/300 flags, 2/30 game dates"
    assert p["verdict"] == "pending (4/300 flags, 2/30 game dates)"
    sec = report.section(db, TODAY)
    imp = (0.04 * 1.909091 + 0.02 * 2 - 0.01 * 1.909091 + 0.03 * 2) / 4
    assert sec["clv_roi_check"]["implied_roi"] == pytest.approx(imp, abs=1e-5)
    assert any("ROI" in x for x in report.render(sec))


def test_decision_cap_and_pending(db):
    for i in range(305):
        flag(
            db,
            i,
            game_date=date(2026, 11, 1 + i % 30),
            clv=0.02 + (i % 7) * 0.001,
            result="hit" if i % 2 else "miss",
            baseline={"price": -110, "clv": 0.0, "win": i % 3 == 0},
        )
    db.commit()
    p = report.section(db, TODAY)["primary"]
    assert p["n"] == 305 and p["progress"] == "300/300 flags, 30/30 game dates"
    assert p["decision"]["n"] == 300
    assert p["verdict"] in ("GO", "NO GO", "INCONCLUSIVE", "INVALID")
    assert p["roi_stage"] == "pending (305/3000)"
    db.query(F).filter(F.event_id == "ev0").delete()
    db.commit()
    p = report.section(db, TODAY)["primary"]
    assert p["n"] == 304
    db.query(F).filter(F.event_id.in_(["ev1", "ev2", "ev3", "ev4", "ev5"])).delete()
    db.commit()
    assert (
        report.section(db, TODAY)["primary"]["verdict"]
        == "pending (299/300 flags, 30/30 game dates)"
    )


def test_decision_waits_for_30_game_dates():
    fs = [{"game_date": date(2026, 11, 1 + i % 5)} for i in range(400)]
    assert report._decision_size(fs) is None
    fs += [{"game_date": date(2026, 12, 1 + i)} for i in range(25)]
    assert report._decision_size(fs) == 425


def test_sample_membership(db):
    flag(db, 1)  # counts
    flag(db, 2, book="espnbet")  # primary yes, h2 no
    flag(db, 3, tier="secondary")
    flag(db, 4, is_close=True)
    flag(db, 5, result="dnp")
    flag(db, 6, result="ungraded")
    flag(db, 7, result=None)
    flag(db, 8, rule_version="fp-shadow-v0")
    db.commit()
    s = report.section(db, TODAY)
    assert s["primary"]["n"] == 2 and s["h2"]["n"] == 1
    assert s["close_flags"]["n"] == 1 and s["close_flags"]["clv_n"] == 0
    assert s["other_rule_versions"] == 1
    c = s["counts"]["to_date"]
    assert (c["void"], c["pending"], c["close_flags"], c["secondary"]) == (2, 1, 1, 1)
    assert s["secondary_by_market"]["player_rebounds"]["n"] == 1
    assert s["by_book"]["espnbet"]["n"] == 1


def test_stale_snapshots_note(db):
    flag(db, 1)
    db.commit()
    s = report.section(db, date(2026, 11, 20))  # snapshot is >36h old
    assert s["freshness"]["stale"]
    assert "no recent odds snapshots since 2026-11-15T10:00:00" in s["note"]
    assert "zero flags is not a result" in report.render(s)[0]


def test_no_table():
    engine = create_engine("sqlite://")
    s = sessionmaker(bind=engine)()
    sec = report.section(s, TODAY)
    assert sec == {"note": "no fair-price shadow table"}
    assert report.render(sec) == ["  no fair-price shadow table"]


def test_build_review_wiring(db, monkeypatch):
    monkeypatch.setattr(ms, "load_rows", lambda *a: {})
    r = ms.build_review(db, TODAY)
    assert "fair_price" in r
    assert "== Fair-price shadow (not published) ==" in ms.render_text(r)

    def boom(*a):
        raise RuntimeError("x")

    monkeypatch.setattr(report, "section", boom)
    r = ms.build_review(db, TODAY)
    assert "unavailable" in r["fair_price"]
    t = ms.render_text(r)
    assert (
        "== Fair-price shadow (not published) ==\n  unavailable: RuntimeError: x" in t
    )


def test_script_main(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path}/r.db"
    engine = create_engine(url)
    S.__table__.create(engine)
    F.__table__.create(engine)
    spec = importlib.util.spec_from_file_location(
        "fp_report_script",
        Path(__file__).resolve().parents[1] / "scripts" / "fair_price_shadow_report.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "_session", sessionmaker(bind=engine))
    assert (
        mod.main(
            ["--from", "2026-11-14", "--to", "2026-11-15", "--today", "2026-11-15"]
        )
        == 0
    )
    assert "no recent odds snapshots" in capsys.readouterr().out
    assert mod.main(["--today", "2026-11-15", "--json"]) == 0
    assert "freshness" in json.loads(capsys.readouterr().out)
