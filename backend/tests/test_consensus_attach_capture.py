"""Capture widened to all PROP_BOOKS at no credit cost: the stored lines and legacy
columns must not change, the phase lists put the quotes minutes from the pricing, and the
NHL moneyline is one recorded bulk call."""

from types import SimpleNamespace

import pytest

from app.services.etl.nba._fanduel_lines import PROP_BOOKS

LEGACY = ("fanduel", "draftkings", "betmgm")
EXTRA = ("williamhill_us", "espnbet", "betrivers", "pinnacle", "novig")


class FakeOdds:
    """Stands in for sync_odds_get: returns canned JSON by URL tail, keeps the params."""

    def __init__(self, by_tail):
        self.by_tail = by_tail
        self.calls = []

    def __call__(self, url, params=None, caller=None, **kw):
        self.calls.append((url, params, caller))
        for tail, payload in self.by_tail.items():
            if url.endswith(tail):
                return SimpleNamespace(
                    status_code=200, json=lambda p=payload: p, text=""
                )
        return SimpleNamespace(status_code=404, json=lambda: {}, text="")


def _book(key, market, outcomes):
    return {
        "key": key,
        "title": key.title(),
        "markets": [{"key": market, "outcomes": outcomes}],
    }


def _prop_outcomes(player, line, over=-110, under=-110):
    return [
        {"name": "Over", "description": player, "point": line, "price": over},
        {"name": "Under", "description": player, "point": line, "price": under},
    ]


@pytest.fixture
def fake(monkeypatch):
    def install(by_tail):
        f = FakeOdds(by_tail)
        monkeypatch.setattr("app.services.odds_api_sync.sync_odds_get", f)
        monkeypatch.setattr(
            "app.services.odds_api_service.sport_in_season", lambda s: True
        )
        return f

    return install


# ---- NFL game lines ---------------------------------------------------------------


def _game_book(key, spread, total):
    return {
        "key": key,
        "title": key.title(),
        "markets": [
            {
                "key": "spreads",
                "outcomes": [
                    {"name": "H", "point": spread, "price": -110},
                    {"name": "A", "point": -spread, "price": -110},
                ],
            },
            {
                "key": "totals",
                "outcomes": [
                    {"name": "Over", "point": total, "price": -110},
                    {"name": "Under", "point": total, "price": -110},
                ],
            },
        ],
    }


def test_nfl_game_lines_row_identical_with_extra_books():
    from app.services.etl.nfl.update_game_lines import _parse_odds

    base = [_game_book("fanduel", -3.5, 47.5), _game_book("betmgm", -4.0, 48.0)]
    # pinnacle was already requested (BOOKMAKER_PRIORITY): the new books are the others
    extra = [_game_book(k, -7.0, 40.0) for k in EXTRA if k != "pinnacle"]
    for books in (base + extra, extra + base):  # order in the payload is irrelevant
        assert _parse_odds({"bookmakers": books}, "H", "A") == _parse_odds(
            {"bookmakers": base}, "H", "A"
        )


def test_nfl_game_lines_request_reads_all_prop_books(fake, monkeypatch):
    from app.services.etl.nfl import update_game_lines as m

    f = fake({"/odds": []})
    monkeypatch.setenv("ODDS_API_KEY", "k")
    m._fetch_bulk_odds()
    assert f.calls[0][1]["bookmakers"] == PROP_BOOKS
    assert f.calls[0][1]["markets"] == "spreads,totals,h2h"


# ---- NFL yards props: legacy columns read only the original three books ------------


def _events_payload(market, player):
    books = [
        _book(k, market, _prop_outcomes(player, line, -110, -110))
        for k, line in zip(
            LEGACY + EXTRA, (250.5, 251.5, 252.5, 240.5, 241.5, 242.5, 243.5, 244.5)
        )
    ]
    return {"/events": [{"id": "e1"}], "/events/e1/odds": {"bookmakers": books}}


def test_qb_lines_keep_only_legacy_books_and_widen_the_request(fake, monkeypatch):
    from app.services.etl.nfl import qb_betting as m

    f = fake(_events_payload("player_pass_yds", "Josh Allen"))
    lines = m.get_nfl_games_and_lines()
    assert set(lines["Josh Allen"]) == {"Fanduel", "Draftkings", "Betmgm"}
    odds_call = [c for c in f.calls if c[0].endswith("/odds")][0]
    assert odds_call[1]["bookmakers"] == PROP_BOOKS
    # the legacy columns: consensus line of the three books only
    from app.services.etl.nfl.prop_lines import best_lines

    assert best_lines(lines["Josh Allen"])["consensus"] == 251.5


def test_recv_lines_keep_only_legacy_books_and_widen_the_request(fake):
    from app.services.etl.nfl import recv_yds_betting as m

    f = fake(_events_payload(m.RECV_YDS_MARKET, "Tyreek Hill"))
    lines = m.fetch_reception_yds_lines()
    assert set(lines["Tyreek Hill"]) == {"Fanduel", "Draftkings", "Betmgm"}
    odds_call = [c for c in f.calls if c[0].endswith("/odds")][0]
    assert odds_call[1]["bookmakers"] == PROP_BOOKS


def test_legacy_match_is_by_key_not_title(fake):
    from app.services.etl.nfl import recv_yds_betting as m

    payload = _events_payload(m.RECV_YDS_MARKET, "Tyreek Hill")
    # a non-legacy book whose title is "FanDuel" must not leak in
    payload["/events/e1/odds"]["bookmakers"].append(
        {
            **_book("novig", m.RECV_YDS_MARKET, _prop_outcomes("Tyreek Hill", 99.5)),
            "title": "FanDuel",
        }
    )
    fake(payload)
    lines = m.fetch_reception_yds_lines()
    assert lines["Tyreek Hill"]["Fanduel"]["over"]["line"] == 250.5


# ---- NHL --------------------------------------------------------------------------


def test_nhl_event_odds_request_and_parsers_unchanged(fake, monkeypatch):
    from app.services.etl.nhl import generate_daily_predictions as g

    monkeypatch.setattr(g, "ODDS_API_KEY", "k")
    g.clear_nhl_event_odds_cache()
    books = [
        _book(
            k, "player_total_saves", _prop_outcomes("Igor Shesterkin", line, -115, -105)
        )
        for k, line in zip(
            ("draftkings",) + EXTRA, (24.5, 22.5, 23.5, 25.5, 21.5, 26.5)
        )
    ]
    f = fake({"/events/e1/odds": {"bookmakers": books}})
    lines = g.get_goalie_saves_odds_for_event("e1", "H", "A", "player_total_saves")
    g.clear_nhl_event_odds_cache()
    assert f.calls[0][1]["bookmakers"] == PROP_BOOKS
    assert lines["Igor Shesterkin"]["line"] == 24.5  # draftkings only, as before
    assert lines["Igor Shesterkin"]["over_odds"] == -115


def test_nhl_moneyline_capture_is_one_recorded_bulk_call(fake, monkeypatch):
    from app.services.etl.nhl import generate_daily_predictions as g

    monkeypatch.setattr(g, "ODDS_API_KEY", "k")
    f = fake({"/sports/icehockey_nhl/odds": []})
    assert g.capture_nhl_moneylines() is True
    ((url, params, caller),) = f.calls
    assert caller == "etl.nhl.moneylines"
    assert params["markets"] == "h2h" and params["bookmakers"] == PROP_BOOKS
    assert params["regions"] == "us" and params["oddsFormat"] == "american"


def test_nhl_moneyline_capture_skips_without_key_and_never_raises(fake, monkeypatch):
    from app.services.etl.nhl import generate_daily_predictions as g

    f = fake({})
    monkeypatch.setattr(g, "ODDS_API_KEY", None)
    assert g.capture_nhl_moneylines() is False and not f.calls

    monkeypatch.setattr(g, "ODDS_API_KEY", "k")

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr("app.services.odds_api_sync.sync_odds_get", boom)
    assert g.capture_nhl_moneylines() is False


def test_both_nhl_runs_capture_moneylines(monkeypatch):
    from app.services.etl.nhl import daily_predictions as d

    calls = []
    monkeypatch.setattr(d, "capture_nhl_moneylines", lambda: calls.append(1))
    monkeypatch.setattr(d, "get_nhl_events_from_odds_api", lambda: [])
    monkeypatch.setattr(d, "clear_nhl_event_odds_cache", lambda: None)
    monkeypatch.setattr(d, "generate_goalie_predictions", lambda *a, **k: 0)
    monkeypatch.setattr(d, "generate_player_predictions", lambda *a, **k: 0)
    monkeypatch.setattr(d, "generate_team_totals_predictions", lambda *a, **k: 0)
    monkeypatch.setattr(d, "update_nhl_stats", lambda: True)
    monkeypatch.setattr(d, "games_to_refresh", lambda *a, **k: [{"id": 1}])
    monkeypatch.setattr(d, "game_datetime_et", lambda g, s=None: (s, None))
    monkeypatch.setattr(d, "slate_game_dates_et", lambda g, s: {s})
    client = SimpleNamespace(
        get_schedule=lambda day: {"gameWeek": [{"games": [{"id": 1}]}]}
    )
    monkeypatch.setattr(d, "NHLAPIClient", lambda: client)
    import app.services.etl.nhl._db as nhl_db

    monkeypatch.setattr(nhl_db, "init_session", lambda: None)
    monkeypatch.setattr(nhl_db, "close_session", lambda: None)

    d._run_daily_core()
    d.run_goalie_refresh()
    assert len(calls) == 2


# ---- phase lists ------------------------------------------------------------------


def test_nba_projectors_run_first_in_predictions():
    from app.tasks import etl_pipeline as e

    preds = dict(e.NBA_PHASES)["predictions"]
    assert preds[:2] == [e.nba_totals_projector, e.nba_spread_projector]
    assert (
        preds.count(e.nba_totals_projector) == preds.count(e.nba_spread_projector) == 1
    )
    # nba_pregame reuses the same list, right after the game lines refresh
    pre = dict(e.NBA_PREGAME_PHASES)
    assert pre["predictions"] is preds
    assert pre["pre_prediction"][-1] is e.nba_update_game_lines


def test_nfl_gameday_refreshes_game_lines_before_projections_only():
    from app.tasks import etl_pipeline as e

    names = [n for n, _ in e.NFL_GAMEDAY_AVAILABILITY_PHASES]
    assert names == ["predictions", "game_lines", "game_projections", "anytime_td"]
    assert dict(e.NFL_GAMEDAY_AVAILABILITY_PHASES)["game_lines"] == [
        e.nfl_update_game_lines
    ]
    # the weekly list is unchanged
    assert [n for n, _ in e.NFL_PHASES] == [
        "actuals",
        "game_lines",
        "predictions",
        "game_projections",
        "anytime_td",
    ]
