"""College slates: the right game is found (FBS + FCS merged), and when it is absent the
answer is not-found, never another real game. Fixtures are trimmed real ESPN payloads."""

import json
from datetime import date
from pathlib import Path

import pytest
import requests

from app.services import espn_results as er

FIX = Path(__file__).parent / "fixtures" / "espn"
SLATES = json.loads((FIX / "college_slates.json").read_text())
TEAMS = json.loads((FIX / "college_teams.json").read_text())
SLUG_LEAGUE = {"college-football": "NCAAF", "mens-college-basketball": "NCAAB"}


def _serve(monkeypatch, removed=(), groups=None, teams=True):
    """Serve fixture slates; `removed` event ids are missing, `groups` limits the groups."""
    served = []

    def fake(url, params=None):
        params = params or {}
        league = SLUG_LEAGUE[url.split("/")[-2]]
        if url.endswith("/teams"):
            if not teams:
                raise requests.ConnectionError("down")
            return {
                "sports": [
                    {"leagues": [{"teams": [{"team": t} for t in TEAMS[league]]}]}
                ]
            }
        served.append(params["groups"])
        day = SLATES[league].get(params["dates"], {})
        evs = (
            day.get(params["groups"], []) if params["groups"] in (groups or day) else []
        )
        return {"events": [e for e in evs if e["id"] not in removed]}

    er.clear_cache()
    monkeypatch.setattr(er, "_get_json", fake)
    return served


def _event(league, day, home, away):
    for evs in SLATES[league][day.strftime("%Y%m%d")].values():
        for e in evs:
            sides = {
                c["homeAway"]: c["team"]["displayName"]
                for c in e["competitions"][0]["competitors"]
            }
            if (sides["home"], sides["away"]) == (home, away):
                return e
    raise AssertionError((home, away))


REAL_CASES = [  # real FCS games the old groups=80-only board matched to an FBS game
    (date(2026, 11, 7), "Texas Southern Tigers", "Alabama State Hornets"),
    (date(2026, 11, 7), "Grambling Tigers", "Arkansas-Pine Bluff Golden Lions"),
    (date(2025, 11, 29), "Abilene Christian Wildcats", "Lamar Cardinals"),
]


@pytest.mark.parametrize("day,home,away", REAL_CASES)
def test_fcs_game_is_found_on_every_grading_path(monkeypatch, day, home, away):
    served = _serve(monkeypatch)
    ev = _event("NCAAF", day, home, away)
    start = er._parse_time(ev["date"])
    for kw in ({"commence_time": start}, {"exact_day": True}, {}):
        g = er.find_game("NCAAF", home, away, day, **kw)
        assert g is not None and g.event_id == ev["id"], kw
    assert {"80", "81"} <= set(served)


@pytest.mark.parametrize("day,home,away", REAL_CASES)
def test_fcs_game_absent_is_not_found_not_another_game(monkeypatch, day, home, away):
    _serve(monkeypatch, groups={"80"})  # the old FBS-only slate
    ev = _event("NCAAF", day, home, away)
    start = er._parse_time(ev["date"])
    for kw in ({"commence_time": start}, {"exact_day": True}, {}):
        assert er.find_game("NCAAF", home, away, day, **kw) is None, kw


def test_team_list_down_is_a_transport_error_not_a_match(monkeypatch):
    _serve(monkeypatch, groups={"80"}, teams=False)
    with pytest.raises(requests.RequestException):
        er.find_game(
            "NCAAF", "Texas Southern Tigers", "Alabama State Hornets", date(2026, 11, 7)
        )


def test_loose_pass_still_works_for_a_real_nickname_slip(monkeypatch):
    _serve(monkeypatch)
    ev = _event(
        "NCAAF", date(2026, 11, 7), "Notre Dame Fighting Irish", "Miami Hurricanes"
    )
    g = er.find_game("NCAAF", "Notre Dame", "Miami Hurricanes", date(2026, 11, 7))
    assert g is not None and g.event_id == ev["id"]


@pytest.mark.parametrize(
    "league,day",
    [
        ("NCAAF", "20261107"),
        ("NCAAF", "20261031"),
        ("NCAAB", "20260221"),
        ("NCAAB", "20260124"),
    ],
)
def test_game_removed_sweep_never_returns_another_game(monkeypatch, league, day):
    """Remove each real game from the slate, ask for it by ESPN name: must be None."""
    when = date(int(day[:4]), int(day[4:6]), int(day[6:]))
    events = [e for evs in SLATES[league][day].values() for e in evs]
    assert len(events) >= 100
    wrong = []
    for e in events:
        _serve(monkeypatch, removed={e["id"]})
        sides = {c["homeAway"]: c["team"] for c in e["competitions"][0]["competitors"]}
        for h, a in ((sides["home"], sides["away"]), (sides["away"], sides["home"])):
            for form in ("displayName", "shortDisplayName"):
                g = er.find_game(league, h[form], a[form], when)
                if g is not None:
                    wrong.append((e["name"], form, g.event_id))
    assert wrong == []
