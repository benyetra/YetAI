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
            bet_type=BetType.PROP,
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


def test_bets_record_is_auto_picks_by_game_date_and_never_shadow(sqlite_db):
    db = sqlite_db
    old_game = GAME - timedelta(days=20)
    # manual + legacy: game 20 days ago, settled yesterday -> not in 7d, not auto
    _bet(db, "man", source=BetSource.MANUAL, commence=old_game, settled_at=GAME)
    _bet(db, "leg", source=BetSource.MANUAL, commence=None, settled_at=GAME)
    # auto bet for yesterday's game settled today -> in 7d
    _bet(db, "auto", "won")
    # never-shown rows: three markers
    _bet(db, "sh1", "won", pf={"shadow": True})
    _bet(db, "sh2", "won", pf={"shown": False})
    _bet(db, "sh3", "shadow_won")
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


def test_versions_count_only_shown_auto_bets(sqlite_db):
    db = sqlite_db
    _bet(db, "a", "won")
    _bet(db, "sh", "won", pf={"shadow": True})
    _bet(db, "m", "won", source=BetSource.MANUAL)
    db.commit()
    assert ms._versions_section(db, TODAY)["bets_30d"] == {"v-test": 1}


_ROWS = [
    {
        "key": "NBA/player_prop/points",
        "state": "WITHHELD losing",
        "withheld": True,
        "bet_n": 2,
        "bet_units": -1.0,
        "proj_n": 40,
        "proj_hits": 10,
        "proj_units": -12.0,
        "n_eff": 30.0,
        "shrunk_roi": -0.2,
    },
    {
        "key": "NHL/total",
        "state": "open",
        "withheld": False,
        "bet_n": 0,
        "bet_units": 0.0,
        "proj_n": 12,
        "proj_hits": 7,
        "proj_units": None,
        "n_eff": 12.0,
        "shrunk_roi": 0.01,
    },
]


def _gate_text(db):
    review = {**_empty_review(), "gate": ms._gate_section(db, TODAY)}
    text = ms.render_text(review)
    return text[text.index("== Record gate ==") :]


def test_gate_table_prints_every_key_from_all_key_rows(sqlite_db, monkeypatch):
    rows = [
        {
            **_ROWS[1],
            "key": "NFL/spread",
            "n": 5,
            "hits": 3,
            "units": 0.4,
            "version": "v9",
        },
        _ROWS[0],
    ]
    monkeypatch.setattr(
        record_gate, "all_key_rows", lambda db, now: rows, raising=False
    )
    text = _gate_text(sqlite_db)
    assert "key | state | n | hits | units | n_eff | shrunk ROI | version" in text
    assert "WITHHELD NBA/player_prop/points" in text
    assert "NFL/spread | open | 5 | 3 | +0.40" in text and "| v9" in text
    assert text.index("WITHHELD NBA") < text.index("NFL/spread")  # withheld first


def test_gate_table_falls_back_to_gate_report_with_open_keys(sqlite_db, monkeypatch):
    monkeypatch.delattr(record_gate, "all_key_rows", raising=False)
    monkeypatch.setattr(record_gate, "gate_report", lambda db, now: _ROWS)
    text = _gate_text(sqlite_db)
    assert "WITHHELD NBA/player_prop/points | losing | 40 | 10" in text
    assert "NHL/total | open | 12 | 7 | n/a" in text


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
        ms._row(10.0, 10.0, 11.0 if i < hits else 9.0, "over", ("t", day, str(i)), "p")
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
    assert "NBA/player_prop/points: hit rate 51.0% -> 54.0%, crossed above" in joined
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
