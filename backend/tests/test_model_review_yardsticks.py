"""Yardsticks T3: auto-pick record, own-snapshot disagreements, full gate table,
honest credits, attention block, and a Redis-free end-to-end render."""

from datetime import date, datetime, timedelta

from app.core.config import settings
from app.models.database_models import BetSource, BetType, YetAIBet
from app.models.predictions_models import PointsActuals, PointsProjections
from app.services import model_review_service as ms
from app.services import odds_api_budget
from app.services.auto_pick import record_gate
from tests.auto_pick.conftest import sqlite_db  # noqa: F401  (fixture)

TODAY = date(2026, 11, 13)
YESTERDAY = TODAY - timedelta(days=1)
GAME = datetime(2026, 11, 12, 23, 0)  # naive UTC: 18:00 ET on 11-12
SETTLED_TODAY = datetime(2026, 11, 13, 13, 0)  # 08:00 ET today


def _bet(db, id, status="won", source=BetSource.AUTO, commence=GAME, **kw):
    pf = kw.pop("pf", {})
    db.add(
        YetAIBet(
            id=id,
            title=f"Bet {id}",
            bet_type=kw.pop("bet_type", BetType.PROP),
            selection="s",
            odds=-110,
            confidence=70,
            status=status,
            source=source,
            sport="basketball_nba",
            settled_at=kw.pop("settled_at", SETTLED_TODAY),
            created_at=GAME,
            commence_time=commence,
            prediction_factors=pf,
            model_version="v-test",
            **kw,
        )
    )


def _record(text_review, days="7"):
    return text_review["bets"]["windows"][days]


def test_bets_record_is_auto_picks_by_game_date(sqlite_db):
    db = sqlite_db
    old_game = GAME - timedelta(days=20)
    # manual + legacy: game 20 days ago, settled yesterday -> not in 7d, not auto
    _bet(db, "man", source=BetSource.MANUAL, commence=old_game, settled_at=GAME)
    _bet(db, "leg", source=BetSource.MANUAL, commence=None, settled_at=GAME)
    # auto bet for yesterday's game settled today -> in 7d
    _bet(db, "auto", "won")
    # a status outside won/lost/pushed is not a graded bet
    _bet(db, "void", "void")
    db.commit()
    b = ms._bets_section(db, TODAY)
    w7, w30 = b["windows"]["7"], b["windows"]["30"]
    assert (w7["picks"], w7["w"]) == (1, 1)
    assert w7["manual_legacy"]["picks"] == 1  # "leg": settled_at fallback, 11-12
    assert w30["picks"] == 1 and w30["manual_legacy"]["picks"] == 2
    text = ms.render_text(
        {**_empty_review(), "bets": b}
    )  # labelled apart in the render
    assert "manual/legacy (not auto picks)" in text


def _empty_review():
    return {
        "date": TODAY.isoformat(),
        "attention": {"lines": [], "more": 0},
        "bets": {"unavailable": "x"},
        "projections": [],
        "board_counts": {"keys": [], "flagged": []},
        "gate": {"unavailable": "x"},
        "misses": {"unavailable": "x"},
        "disagreements": {"unavailable": "x"},
        "model_versions": {"unavailable": "x"},
        "clv": {"unavailable": "x"},
        "shadow": {"note": "n"},
        "fair_price": {"unavailable": "x"},
        "credits": {"not_available": "z"},
    }


def test_disagreement_uses_the_bets_own_line_not_the_overwritten_row(sqlite_db):
    db = sqlite_db
    # the projection row's line was later overwritten to 30.5; actual 25
    db.add(
        PointsProjections(
            date=YESTERDAY,
            player_id=7,
            player_name="P7",
            fanduel_line=30.5,
            fanduel_over_under="under",
            projected_points=22.0,
        )
    )
    db.add(
        PointsActuals(
            date=YESTERDAY,
            player_id=7,
            player_name="P7",
            actual_points=25.0,
            projected_points=22.0,
        )
    )
    ref = {
        "table": PointsProjections.__tablename__,
        "date": YESTERDAY.isoformat(),
        "player_id": 7,
    }
    # taken: over 20.5 -> actual 25 hits; the bet was recorded as lost -> disagrees
    _bet(
        db,
        "b1",
        "lost",
        pf={"market_line": 20.5, "grading": {"side": "over"}, "projection_ref": ref},
    )
    # no snapshot at all
    _bet(db, "b2", "won", pf={"projection_ref": ref})
    db.commit()
    cur = ms.load_rows(db, YESTERDAY, YESTERDAY)
    d = ms._disagreements_section(db, TODAY, cur)
    assert (d["checked"], d["disagreements"], d["without_snapshot"]) == (1, 1, 1)
    row = d["rows"][0]
    assert (row["bet_line"], row["line"], row["bet_side"]) == (20.5, 30.5, "over")
    text = ms.render_text({**_empty_review(), "disagreements": d})
    assert "over at 20.5 grades won" in text and "current row line 30.5" in text


def test_versions_count_only_auto_bets(sqlite_db):
    db = sqlite_db
    _bet(db, "a", "won")
    _bet(db, "m", "won", source=BetSource.MANUAL)
    db.commit()
    assert ms._versions_section(db, TODAY)["bets_30d"] == {"v-test": 1}


def _key_row(key, state, **kw):
    """One row as record_gate.all_key_rows returns it."""
    row = {
        "key": key,
        "n": 0,
        "hits": 0,
        "units": 0.0,
        "n_eff": 0.0,
        "shrunk_roi": 0.0,
        "version": None,
        "selection_version": "ev-v1",
        "unpriced_n": 0,
        "bet_n": 0,
        "dates": 0,
        "state": state,
        "reason": None if state == "open" else "unproven_record",
    }
    row.update(kw)
    return row


def _gate_text(db):
    review = {**_empty_review(), "gate": ms._gate_section(db, TODAY)}
    text = ms.render_text(review)
    return text[text.index("== Record gate ==") :]


def test_gate_table_prints_every_key_with_its_record_fields(sqlite_db, monkeypatch):
    rows = [
        _key_row("NFL/spread", "open", n=5, hits=3, units=0.4, version="v9"),
        _key_row(
            "NBA/player_prop/points",
            "withheld-losing",
            n=40,
            hits=10,
            units=-12.0,
            n_eff=40.0,
            shrunk_roi=-0.2,
            dates=12,
            version="xgb-11-14",
            reason="losing_record",
        ),
        _key_row("NHL/total", "withheld-unproven", unpriced_n=12),
    ]
    monkeypatch.setattr(record_gate, "all_key_rows", lambda db, now: rows)
    text = _gate_text(sqlite_db)
    assert "| dates | unpriced | version | selection | reason" in text
    assert (
        "WITHHELD NBA/player_prop/points | withheld-losing | 40 | 10 | -12.00 | 40.0 |"
        " -20.0% | 12 | 0 | xgb-11-14 | ev-v1 | losing_record" in text
    )
    assert "NFL/spread | open | 5 | 3 | +0.40" in text and "| v9 | ev-v1 | -" in text
    assert "WITHHELD NHL/total | withheld-unproven | 0 | 0 |" in text
    assert "| 0 | 12 | n/a | ev-v1 | unproven_record" in text
    assert text.index("WITHHELD NBA") < text.index("NFL/spread")  # withheld first


def test_credits_without_redis_say_so_instead_of_zeros(sqlite_db, monkeypatch):
    monkeypatch.setattr(odds_api_budget, "_sync_redis", lambda: None)
    monkeypatch.setattr(settings, "ODDS_API_KEY", "k")
    c = ms._credits_section(sqlite_db, TODAY)
    assert c == {
        "not_available": "not available in this runner (no Redis); "
        "production numbers are in the 09:45 ET email"
    }
    text = ms.render_text({**_empty_review(), "credits": c})
    assert "not available in this runner (no Redis)" in text
    assert "remaining" not in text.split("== Odds API credits ==")[1]


def _ou(hits, n, day):
    return [
        # projection 11 over line 10; the stored side says "under" and must be ignored
        ms._row(11.0, 10.0, 11.0 if i < hits else 9.0, "under", ("t", day, str(i)), "p")
        for i in range(n)
    ]


def test_attention_lists_crossing_thin_board_and_empty_says_nothing(sqlite_db):
    key = ("NBA", "player_prop", "points")
    cur = {key: ("ou", _ou(54, 100, "2026-11-10"))}
    prev = {key: ("ou", _ou(51, 100, "2026-11-09"))}
    board = {
        "flagged": [
            {
                "date": "2026-11-13",
                "key": "NHL/total",
                "flag": "thin",
                "rows": 1,
                "expected": 6.0,
            }
        ]
    }
    gate = {"withheld_count": 1, "withheld": [{"key": "NBA/spread"}]}
    got = ms._attention_section(sqlite_db, TODAY, cur, prev, board, gate)["lines"]
    joined = "\n".join(got)
    assert (
        "NBA/player_prop/points: current-model hit rate 51.0% -> 54.0%, crossed above"
        in joined
    )
    assert "board 2026-11-13 NHL/total: thin" in joined
    assert "1 gate keys withheld: NBA/spread" in joined
    empty = ms._attention_section(
        sqlite_db, TODAY, {}, {}, {"flagged": []}, {"withheld_count": 0}
    )
    assert empty["lines"] == []
    assert "nothing needs attention" in ms.render_text(
        {**_empty_review(), "attention": empty}
    )


def test_full_review_renders_without_redis_or_odds_key(sqlite_db, monkeypatch):
    monkeypatch.setattr(odds_api_budget, "_sync_redis", lambda: None)
    monkeypatch.setattr(settings, "ODDS_API_KEY", None)
    text = ms.render_text(ms.build_review(sqlite_db, TODAY))
    heads = [
        "== What changed since yesterday / needs attention ==",
        "== YetAI Bets record ==",
        "== Projection accuracy",
        "== Board row counts ==",
        "== Record gate ==",
        "== Biggest misses",
        "== Bet vs projection disagreements",
        "== Model versions",
        "== CLV ==",
        "== Residual shadow",
        "== Fair-price shadow",
        "== Odds API credits ==",
    ]
    pos = [text.index(h) for h in heads]
    assert pos == sorted(pos)
    assert text.index(heads[0]) < text.index("== YetAI Bets record ==")
    credits = text.split("== Odds API credits ==")[1]
    assert "unavailable:" not in credits and "not available in this runner" in credits


def test_spread_bets_are_still_compared_on_the_stored_call(sqlite_db):
    table = "pred_nba_spread_projections"
    cur = {
        ("NFL", "spread", None): (
            "edge",
            [
                ms._row(
                    3.0,
                    -2.5,
                    7.0,
                    "HOME",
                    (table, YESTERDAY, "Home", "Away"),
                    "Away @ Home",
                    correct=True,
                )
            ],
        )
    }
    ref = {
        "table": table,
        "game_date": YESTERDAY.isoformat(),
        "home_team_name": "Home",
        "away_team_name": "Away",
    }
    _bet(sqlite_db, "s1", "lost", bet_type=BetType.SPREAD, pf={"projection_ref": ref})
    sqlite_db.commit()
    d = ms._disagreements_section(sqlite_db, TODAY, cur)
    assert (d["checked"], d["disagreements"], d["without_snapshot"]) == (1, 1, 0)


def _gate_file(**kw):
    rec = {
        "status": "rejected_by_line_gate",
        "recorded_at": "2026-11-16T12:00:00+00:00",
        "champion_below_line": True,
        "champion": {"champion_mae": 5.34, "line_mae": 4.97},
        "lined": {"model_mae": 5.30, "line_mae": 4.97},
    }
    rec.update(kw)
    return lambda key: rec


def test_model_vs_line_reads_the_promote_gate_record():
    below = ms._model_vs_line("points", TODAY, read=_gate_file())
    assert below["state"] == "model below line" and below["model_mae"] == 5.34
    ok = ms._model_vs_line("points", TODAY, read=_gate_file(champion_below_line=False))
    assert ok["state"] == "not below line"
    promoted = ms._model_vs_line(
        "points", TODAY, read=_gate_file(status="pass", upload_status="uploaded")
    )
    assert promoted["state"] == "not below line" and promoted["model_mae"] == 5.30
    # missing, stale, unreadable and no-line-evidence records are "unknown", never "fine"
    assert ms._model_vs_line("points", TODAY, read=lambda k: None)["state"] == "unknown"
    stale = _gate_file(recorded_at="2026-10-01T00:00:00+00:00")
    assert ms._model_vs_line("points", TODAY, read=stale)["state"] == "unknown"

    def boom(key):
        raise RuntimeError("s3 down")

    assert ms._model_vs_line("points", TODAY, read=boom)["state"] == "unknown"
    none = _gate_file(status="no_line_evidence", champion_below_line=None)
    assert ms._model_vs_line("points", TODAY, read=none)["state"] == "unknown"


def test_model_vs_line_without_s3_credentials_is_unknown(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    m = ms._model_vs_line("rebounds", TODAY)
    assert m == {"state": "unknown", "note": "no S3 credentials in this runner"}


def test_review_shows_model_below_line_per_stat(sqlite_db, monkeypatch):
    monkeypatch.setattr(record_gate, "all_key_rows", lambda db, now: [])
    from app.services.ml import promote_gate

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setattr(promote_gate, "read_outcome", _gate_file())
    gate = ms._gate_section(sqlite_db, TODAY)
    text = ms.render_text({**_empty_review(), "gate": gate})
    assert "NBA points model: model below line (champion kept" in text
    assert "model MAE 5.34 vs line 4.97, recorded 2026-11-16" in text
    att = ms._attention_section(sqlite_db, TODAY, {}, {}, None, gate)
    assert any(
        "NBA rebounds: the serving model is worse than the line" in x
        for x in att["lines"]
    )
