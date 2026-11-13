"""ESPN results client: final scores and box-score stats for every league YetAI shows.

Uses ESPN's public site API (no key). `find_game` resolves a game by team names and slate
date; `player_stat` reads one stat from the game's box score. Network errors propagate to the
caller (the grader records them and retries); responses are cached in-process until
`clear_cache()`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import requests

GameState = Literal["final", "in_progress", "scheduled", "postponed", "cancelled"]

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
TIMEOUT = 10

_COLLEGE_LIMIT = "300"

# league -> (sport path, league slug, extra scoreboard params)
LEAGUES: dict[str, tuple[str, str, dict]] = {
    "NBA": ("basketball", "nba", {}),
    "WNBA": ("basketball", "wnba", {}),
    "NFL": ("football", "nfl", {}),
    "NHL": ("hockey", "nhl", {}),
    "MLB": ("baseball", "mlb", {}),
    "NCAAF": (
        "football",
        "college-football",
        {"groups": "80", "limit": _COLLEGE_LIMIT},  # FBS; FCS (81) added below
    ),
    "NCAAB": (
        "basketball",
        "mens-college-basketball",
        {"groups": "50", "limit": _COLLEGE_LIMIT},  # 50 = all of Division I (checked)
    ),
    "EPL": ("soccer", "eng.1", {}),
    "MLS": ("soccer", "usa.1", {}),
    "UCL": ("soccer", "uefa.champions", {}),
    "LALIGA": ("soccer", "esp.1", {}),
    "BUNDESLIGA": ("soccer", "ger.1", {}),
    "SERIEA": ("soccer", "ita.1", {}),
    "LIGUE1": ("soccer", "fra.1", {}),
}
# Extra scoreboard `groups` merged into the league's slate (FCS is its own ESPN group).
_EXTRA_GROUPS = {"NCAAF": ("81",)}
# Leagues whose loose name rules can land on the wrong real game when the right one is
# missing from the slate, so a name that is itself a different ESPN team is refused.
_COLLEGE = frozenset({"NCAAF", "NCAAB"})
SOCCER_LEAGUES = frozenset(k for k, v in LEAGUES.items() if v[0] == "soccer")

_BASKETBALL = frozenset(
    {
        "points",
        "rebounds",
        "assists",
        "steals",
        "blocks",
        "threes",
        "turnovers",
        "pra",
        "pr",
        "pa",
        "ra",
        "blocks_steals",
    }
)
# Only stats whose box-score label/key was checked against real payloads.
PROP_STATS: dict[str, frozenset[str]] = {
    "NBA": _BASKETBALL,
    "WNBA": _BASKETBALL,
    "NFL": frozenset(
        {
            "passing_yards",
            "receiving_yards",
            "rushing_yards",
            "passing_tds",
            "pass_completions",
            "receptions",
            "anytime_td",
        }
    ),
    "NCAAF": frozenset({"anytime_td"}),
    "NHL": frozenset(
        {"saves", "shots_on_goal", "goals", "assists", "points", "blocked_shots"}
    ),
    # No total_bases: ESPN's MLB box score has no 2B/3B columns (see mlb_results).
    "MLB": frozenset(
        {"strikeouts", "hits", "home_runs", "rbis", "batter_strikeouts", "pitcher_outs"}
    ),
}

# (league, stat) -> (box-score group name/type or None for any, ESPN stat key)
_BB_KEYS = {
    "points": "points",
    "rebounds": "rebounds",
    "assists": "assists",
    "steals": "steals",
    "blocks": "blocks",
    "threes": "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
    "turnovers": "turnovers",
}
_STAT_KEYS: dict[tuple[str, str], tuple[str | None, str]] = {
    ("NFL", "passing_yards"): ("passing", "passingYards"),
    ("NFL", "receiving_yards"): ("receiving", "receivingYards"),
    ("NFL", "rushing_yards"): ("rushing", "rushingYards"),
    ("NFL", "passing_tds"): ("passing", "passingTouchdowns"),
    ("NFL", "pass_completions"): ("passing", "completions/passingAttempts"),
    ("NFL", "receptions"): ("receiving", "receptions"),
    ("NHL", "saves"): ("goalies", "saves"),
    ("NHL", "shots_on_goal"): (
        None,
        "shotsTotal",
    ),  # label "S"; "SOG" is shootout goals
    ("NHL", "goals"): (None, "goals"),
    ("NHL", "assists"): (None, "assists"),
    ("NHL", "blocked_shots"): (None, "blockedShots"),
    ("MLB", "strikeouts"): ("pitching", "strikeouts"),
    ("MLB", "hits"): ("batting", "hits"),
    ("MLB", "home_runs"): ("batting", "homeRuns"),
    ("MLB", "rbis"): ("batting", "RBIs"),
    ("MLB", "batter_strikeouts"): ("batting", "strikeouts"),
    ("MLB", "pitcher_outs"): ("pitching", "fullInnings.partInnings"),  # "6.1" = 19
}
# Stats that are a sum of other stats of the same league.
_COMBOS: dict[tuple[str, str], tuple[str, ...]] = {
    ("NHL", "points"): ("goals", "assists"),
}
for _lg in ("NBA", "WNBA"):
    for _st, _key in _BB_KEYS.items():
        _STAT_KEYS[(_lg, _st)] = (None, _key)
    for _st, _parts in {
        "pra": ("points", "rebounds", "assists"),
        "pr": ("points", "rebounds"),
        "pa": ("points", "assists"),
        "ra": ("rebounds", "assists"),
        "blocks_steals": ("blocks", "steals"),
    }.items():
        _COMBOS[(_lg, _st)] = _parts

# anytime_td: touchdowns sportsbooks count (not passing). ESPN's defensiveTouchdowns includes
# interception returns and sometimes kick/punt returns, so those columns are not added to it.
_ANYTIME_TD_KEYS = (
    "rushingTouchdowns",
    "receivingTouchdowns",
    "defensiveTouchdowns",
    "interceptionTouchdowns",
    "kickReturnTouchdowns",
    "puntReturnTouchdowns",
)
# A scoring-play text names its scorer right before the yardage ("Woody Marks 1 Yd Fumble
# Recovery", "Marshawn Kneeland Blocked Punt Recovery"); a passer follows "pass from".
_TD_ANCHOR = r"(?: (?:jr|sr|ii|iii|iv|v))?(?: \d+ yds?\b| no gain\b| blocked\b| recovered\b| for \d+ yds?\b)"
# A scorer written out in full (two words of 2+ letters, so not "W. Eget") before the anchor
_FULL_NAME = re.compile(rf" \w{{2,}} \w{{2,}}{_TD_ANCHOR}")

_MINUTES_KEY = "minutes"
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


@dataclass(frozen=True)
class GameResult:
    state: str  # GameState
    home_score: int | None  # oriented to the caller's home/away
    away_score: int | None
    event_id: str
    start_time: datetime | None  # naive UTC
    detail: str  # ESPN status detail, e.g. "Final/OT"
    teams: tuple[str, ...] = ()  # the two competitors' displayNames, either order
    number: int = 0  # 1-based order among same-day games of the pair; 0 = only game


@dataclass(frozen=True)
class StatResult:
    # "ok" | "did_not_play" | "not_found" (not in the box score) | "stat_unavailable"
    # (in the box score, but not with this stat: a goalie's goals, a batter's strikeouts)
    status: str
    value: float | None = None


_cache: dict[tuple, dict] = {}


def clear_cache() -> None:
    _cache.clear()


def _get_json(url: str, params: dict | None = None) -> dict:
    key = (url, tuple(sorted((params or {}).items())))
    if key not in _cache:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        _cache[key] = resp.json()
    return _cache[key]


def _norm(text: str | None) -> str:
    """Lowercase, accent-free, punctuation-free, single-spaced."""
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[.'’`]", "", s.replace("&", " and "))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", s).split())


def _initials(text: str) -> str:
    return "".join(w[0] for w in text.split())


def _team_matches(name: str, team: dict, loose: bool | str = False) -> bool:
    """Exact: displayName, shortDisplayName, abbreviation or location + name.

    Loose (only used when no exact match exists anywhere): the nickname alone, the
    location alone, a multi-word tail of the full name ("Trail Blazers"), or the
    nickname after the location's initials ("NY Giants", "LA Lakers"), or any other
    location spelling in front of the nickname ("Los Angeles Clippers").
    ``loose="strong"`` leaves out the weakest rule (same location, any nickname), which
    would match "Los Angeles Clippers" to the Lakers; callers try it before ``True``.
    """
    n = _norm(name)
    if not n:
        return False
    nick, loc = _norm(team.get("name")), _norm(team.get("location"))
    full = _norm(team.get("displayName"))
    exact = {
        full,
        _norm(team.get("shortDisplayName")),
        _norm(team.get("abbreviation")),
        f"{loc} {nick}".strip(),
    }
    exact.discard("")
    if n in exact:
        return True
    if not loose:
        return False
    if n in (nick, loc) or (full.endswith(" " + n) and " " in n):
        return True
    # Same nickname, different location spelling ("Los Angeles Clippers" vs "LA Clippers",
    # "Connecticut Huskies" vs "UConn Huskies", "Oakland Athletics" vs "Athletics").
    if nick and n.endswith(" " + nick):
        return True
    # Renamed franchise ("Utah Hockey Club" -> "Utah Mammoth"): same location, the
    # opponent and date still have to pin down a single game.
    if loose is True and loc and n.startswith(loc + " "):
        return True
    head, _, tail = n.rpartition(" ")
    return bool(nick and loc and tail == nick and head == _initials(loc))


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _score(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _state(status_type: dict) -> str:
    name = (status_type.get("name") or "").upper()
    if "POSTPONED" in name:
        return "postponed"
    if any(w in name for w in ("CANCEL", "ABANDON", "FORFEIT")):
        return "cancelled"
    if status_type.get("completed"):  # STATUS_FINAL*, soccer STATUS_FULL_TIME
        return "final"
    if status_type.get("state") == "in":
        return "in_progress"
    return "scheduled"


def _scoreboard(league: str, day: date) -> list[dict]:
    sport, slug, extra = LEAGUES[league]
    events, seen = [], set()
    for groups in (extra.get("groups"), *_EXTRA_GROUPS.get(league, ())):
        params = {"dates": day.strftime("%Y%m%d"), **extra}
        if groups:
            params["groups"] = groups
        data = _get_json(f"{BASE_URL}/{sport}/{slug}/scoreboard", params)
        for e in data.get("events") or []:
            if e.get("id") not in seen:
                seen.add(e.get("id"))
                events.append(e)
    return events


def _team_ids_by_name(league: str) -> dict[str, str]:
    """Exact normalised name (displayName, location + nickname) -> ESPN team id."""
    if ("ids", league) in _cache:
        return _cache[("ids", league)]
    sport, slug, _ = LEAGUES[league]
    data = _get_json(f"{BASE_URL}/{sport}/{slug}/teams", {"limit": "1000"})
    teams = [
        t["team"]
        for sp in data.get("sports") or []
        for lg in sp.get("leagues") or []
        for t in lg.get("teams") or []
    ]
    if not teams:  # never "no such team": the guard cannot be applied, so retry later
        raise requests.ConnectionError(f"ESPN {league} team list is empty")
    out = {}
    for t in teams:
        for key in (t.get("displayName"), f"{t.get('location')} {t.get('name')}"):
            if _norm(key):
                out[_norm(key)] = str(t.get("id"))
    _cache[("ids", league)] = out
    return out


def _names_agree(league: str, home: str, away: str, comp: dict, swapped: bool) -> bool:
    """False when a pick name is exactly another ESPN team than the event's competitor."""
    ids = _team_ids_by_name(league)
    sides = {c["homeAway"]: c for c in comp["competitors"]}
    mine = (sides["away" if swapped else "home"], sides["home" if swapped else "away"])
    for name, comp_side in zip((home, away), mine):
        want = ids.get(_norm(name))
        if want and want != str(comp_side["team"].get("id")):
            return False
    return True


def _match_event(
    event: dict, home: str, away: str, loose: bool | str = False
) -> tuple[dict, bool] | None:
    """(competition, swapped) when BOTH teams match in exactly one orientation."""
    comp = (event.get("competitions") or [{}])[0]
    sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
    if "home" not in sides or "away" not in sides:
        return None
    eh, ea = sides["home"]["team"], sides["away"]["team"]

    def m(name, team):
        return _team_matches(name, team, loose)

    straight = m(home, eh) and m(away, ea)
    swapped = m(home, ea) and m(away, eh)
    if straight == swapped:  # neither, or ambiguous ("New York" vs "New York")
        return None
    return comp, swapped


_MAX_START_GAP = timedelta(hours=12)


def _candidates(
    league: str,
    home: str,
    away: str,
    game_date: date,
    commence_time,
    loose: bool | str,
    exact_day: bool = False,
) -> list[tuple[dict, dict, bool]]:
    """Matching events on the slate date, else the previous day, else the next."""
    days = (
        (game_date,)
        if exact_day
        else (
            game_date,
            game_date - timedelta(days=1),
            game_date + timedelta(days=1),
        )
    )
    for day in days:
        found = []
        for event in _scoreboard(league, day):
            hit = _match_event(event, home, away, loose)
            if not hit:
                continue
            start = _parse_time(event.get("date"))
            if commence_time and (
                start is None or abs(start - commence_time) > _MAX_START_GAP
            ):
                continue
            if (
                loose
                and league in _COLLEGE
                and not _names_agree(league, home, away, *hit)
            ):
                continue
            found.append((event, *hit))
        if found:
            return found
    return []


def _is_extra_time(status_type: dict) -> bool:
    name = (status_type.get("name") or "").upper()
    return any(k in name for k in ("AET", "PEN", "EXTRA", "SHOOTOUT"))


def _regulation_scores(league: str, event_id: str) -> dict[str, int] | None:
    """Soccer 90'+stoppage score per side: the first two period linescores."""
    sport, slug, _ = LEAGUES[league]
    summary = _get_json(f"{BASE_URL}/{sport}/{slug}/summary", {"event": event_id})
    comps = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    out = {}
    for c in comps.get("competitors", []):
        lines = c.get("linescores") or []
        vals = [_score(x.get("displayValue", x.get("value"))) for x in lines[:2]]
        if len(vals) < 2 or None in vals:
            return None
        out[c.get("homeAway")] = sum(vals)
    return out if {"home", "away"} <= out.keys() else None


def _pair(found_item) -> frozenset:
    """The two ESPN team ids of one event (a doubleheader repeats the pair)."""
    comp = found_item[1]
    return frozenset(str(c.get("team", {}).get("id")) for c in comp["competitors"])


def _result(league: str, event: dict, comp: dict, swapped: bool) -> GameResult:
    sides = {c["homeAway"]: c for c in comp["competitors"]}
    status_type = (comp.get("status") or event.get("status") or {}).get("type", {})
    state = _state(status_type)
    h, a = _score(sides["home"].get("score")), _score(sides["away"].get("score"))
    detail = status_type.get("detail") or status_type.get("description") or ""
    if league in SOCCER_LEAGUES and state == "final" and _is_extra_time(status_type):
        # soccer bets settle on 90 minutes + stoppage; None means "underivable"
        reg = _regulation_scores(league, str(event["id"]))
        h, a = (reg["home"], reg["away"]) if reg else (None, None)
        detail = f"{detail} (regulation)" if reg else f"{detail} (no regulation score)"
    if swapped:
        h, a = a, h
    return GameResult(
        state=state,
        home_score=h,
        away_score=a,
        event_id=str(event["id"]),
        start_time=_parse_time(event.get("date")),
        detail=detail,
        teams=tuple(c["team"].get("displayName") or "" for c in comp["competitors"]),
    )


def find_games(
    league: str,
    home: str,
    away: str,
    game_date: date,
    commence_time: datetime | None = None,
    exact_day: bool = False,
) -> list[GameResult]:
    """Every game of the pair on the slate date (a doubleheader gives two), best first.

    With ``commence_time`` the nearest start is first; without it, earliest start first.
    Exact names win; the loose passes (strongest first) must find a single pairing, so
    "Los Angeles Clippers" never lands on the Lakers. ``exact_day`` skips the previous and
    next day, for a slate date that is known to be right (no makeup-game mix-ups).
    """
    league = (league or "").upper()
    if league not in LEAGUES:
        return []
    for loose in (False, "strong", True):
        found = _candidates(
            league, home, away, game_date, commence_time, loose, exact_day
        )
        if not found:
            continue
        if loose is not False and len({_pair(f) for f in found}) > 1:
            return []  # ambiguous loose hit: a weaker pass would only add more
        break
    else:
        return []
    far = datetime.max
    if commence_time:
        found.sort(
            key=lambda f: (
                abs(t - commence_time)
                if (t := _parse_time(f[0].get("date")))
                else timedelta.max
            )
        )
    else:
        found.sort(key=lambda f: _parse_time(f[0].get("date")) or far)
    results = [_result(league, *f) for f in found]
    if len(results) > 1:  # a doubleheader: number the games chronologically
        order = sorted(results, key=lambda r: r.start_time or far)
        results = [replace(r, number=order.index(r) + 1) for r in results]
    return results


def find_game(
    league: str,
    home: str,
    away: str,
    game_date: date,
    commence_time: datetime | None = None,
    exact_day: bool = False,
) -> GameResult | None:
    """The one game of the pair; None when none matches or a doubleheader is ambiguous."""
    games = find_games(league, home, away, game_date, commence_time, exact_day)
    return games[0] if games and (commence_time or len(games) == 1) else None


def _person(name: str | None) -> str:
    parts = _norm(name).split()
    while len(parts) > 1 and parts[-1] in _SUFFIXES:
        parts.pop()
    return " ".join(parts)


_LEADING_NUM = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)")


def _num(raw) -> float | None:
    """Signed leading number: "-3" -> -3, "3-5" (made-attempted) -> 3."""
    m = _LEADING_NUM.match(str(raw))
    return float(m.group(1)) if m else None


CORE_URL = "https://sports.core.api.espn.com/v2/sports"


def _td_plays(summary: dict) -> list[str]:
    """Normalised text of every touchdown scoring play, PAT / two-point parentheses dropped
    and, after a lateral, only the part naming the final ball carrier."""
    out = []
    for p in summary.get("scoringPlays") or []:
        if "touchdown" not in ((p.get("type") or {}).get("text") or "").lower():
            continue
        text = re.sub(r"\([^)]*\)", " ", p.get("text") or "")
        text = re.split(r"lateral(?:ed)?(?: to)?", text, flags=re.I)[-1]
        # "Sacker 22 Yd Fumble Recovery by Scorer For 22 Yd Loss": the scorer follows "by"
        text = re.split(r"\bby\b", text, flags=re.I)[-1]
        out.append(f" {_norm(text)} ")
    return out


def _scorer_is(play: str, person: str) -> bool:
    parts = person.split()
    forms = {person} | ({f"{parts[0][0]} {parts[-1]}"} if len(parts) > 1 else set())
    return any(re.search(f" {re.escape(f)}{_TD_ANCHOR}", play) for f in forms)


def _mentions(play: str, person: str) -> bool:
    """The name anywhere in the play text, also as "F. Last" or glued "FLast" ("J.Gibbs")."""
    parts = person.split()
    forms = {person}
    if len(parts) > 1:
        forms |= {f"{parts[0][0]} {parts[-1]}", f"{parts[0][0]}{parts[-1]}"}
    return any(f" {f} " in play for f in forms)


def _td_plays_check(summary: dict, want: str) -> tuple[int, bool]:
    """(touchdown plays this player scored, a touchdown play has an unidentified scorer).

    A play is identified when its scorer is the player, a box-score athlete or a full name,
    or when a box-score athlete credited with a TD is mentioned in it (ESPN's odd play-by-play
    wording). Passing TDs credit the receiver only; extra points and two-point tries are
    not touchdown plays.
    """
    plays = _td_plays(summary)
    box, credited = set(), set()
    for t in (summary.get("boxscore") or {}).get("players", []):
        for g in t.get("statistics", []):
            idx = [
                i for i, k in enumerate(g.get("keys") or []) if k in _ANYTIME_TD_KEYS
            ]
            for a in g.get("athletes", []):
                name = _person(a["athlete"].get("displayName"))
                box.add(name)
                if any(_num(a["stats"][i]) for i in idx if a.get("stats")):
                    credited.add(name)
    mine = sum(_scorer_is(p, want) for p in plays)
    unknown = any(
        not _scorer_is(p, want)
        and not _FULL_NAME.search(p)
        and not any(_scorer_is(p, n) for n in box)
        and not any(_mentions(p, n) for n in credited)
        for p in plays
    )
    return mine, unknown


def _roster_status(league: str, event_id: str, summary: dict, want: str) -> StatResult:
    """A player with no box-score line: active zero-touch ("ok", 0) or inactive.

    ESPN's core event roster (NFL only: `valid` is meaningless for NCAAF) lists the gameday
    squad with `valid` true and `didNotPlay` false for everyone who dressed; every box-score
    player of 16 checked teams is that way. Entries carry only a last name, so candidates are
    resolved to a full name through their athlete $ref. Not on either roster = not_found.
    """
    sport, slug, _ = LEAGUES[league]
    found = {}
    for team in (summary.get("boxscore") or {}).get("players", []):
        tid = team["team"]["id"]
        roster = _get_json(
            f"{CORE_URL}/{sport}/leagues/{slug}/events/{event_id}"
            f"/competitions/{event_id}/competitors/{tid}/roster"
        )
        for e in roster["entries"]:
            if _person(e["displayName"]).split()[-1:] != want.split()[-1:]:
                continue
            ref = e["athlete"]["$ref"].replace("http://", "https://")
            if _person(_get_json(ref)["fullName"]) == want:
                found[e["playerId"]] = e
    if len(found) > 1:
        return StatResult("ambiguous")
    if not found:
        return StatResult("not_found")
    e = next(iter(found.values()))
    if e["valid"] and not e["didNotPlay"]:
        return StatResult("ok", 0.0)
    return StatResult("did_not_play")


def player_stat(league: str, event_id: str, player: str, stat: str) -> StatResult:
    league = (league or "").upper()
    if stat not in PROP_STATS.get(league, ()):
        return StatResult("not_found")
    sport, slug, _ = LEAGUES[league]
    summary = _get_json(f"{BASE_URL}/{sport}/{slug}/summary", {"event": event_id})
    want = _person(player)
    exact = _norm(player)
    entries = []  # (group id, keys, athlete entry)
    for team in (summary.get("boxscore") or {}).get("players", []):
        for group in team.get("statistics", []):
            gid = group.get("name") or group.get("type")
            for ath in group.get("athletes", []):
                if _person(ath["athlete"].get("displayName")) == want:
                    entries.append((gid, group.get("keys") or [], ath))
    scored, unknown = _td_plays_check(summary, want) if stat == "anytime_td" else (0, 0)
    if not entries:
        if scored:  # scored without a box-score line (e.g. a blocked-punt recovery)
            return StatResult("ok", float(scored))
        if unknown:  # a touchdown nobody can be named for: never guess lost
            return StatResult("stat_unavailable")
        if stat == "anytime_td" and league == "NFL":
            return _roster_status(league, event_id, summary, want)
        return StatResult("not_found")

    def who(entry) -> str:
        a = entry[2]["athlete"]
        return str(a.get("id") or a.get("displayName"))

    if len({who(e) for e in entries}) > 1:
        # "Michael Carter" vs "Michael Carter II": only an exact name (with suffix) decides
        entries = [
            e for e in entries if _norm(e[2]["athlete"].get("displayName")) == exact
        ]
        if len({who(e) for e in entries}) != 1:
            return StatResult("ambiguous" if stat == "anytime_td" else "not_found")

    def raw(key: str, group: str | None):
        for gid, keys, ath in entries:
            if (group is None or gid == group) and key in keys and ath.get("stats"):
                return ath["stats"][keys.index(key)]
        return None

    def value(key: str, group: str | None) -> float | None:
        text = raw(key, group)
        return None if text is None else _num(text)

    if all(a.get("didNotPlay") or not a.get("stats") for _, _, a in entries):
        return StatResult("did_not_play")
    # played-zero-minutes basketball lines (minutes "0" / "--") are DNPs too
    minutes = value(_MINUTES_KEY, None)
    if minutes is not None and minutes == 0:
        return StatResult("did_not_play")

    if stat == "anytime_td":
        sums = dict.fromkeys(_ANYTIME_TD_KEYS, 0.0)
        for _, keys, ath in entries:
            for k in _ANYTIME_TD_KEYS:
                if k in keys and ath.get("stats"):
                    sums[k] += _num(ath["stats"][keys.index(k)]) or 0
        returns = sums["kickReturnTouchdowns"] + sums["puntReturnTouchdowns"]
        box = (
            sums["rushingTouchdowns"]
            + sums["receivingTouchdowns"]
            + max(sums["defensiveTouchdowns"], returns + sums["interceptionTouchdowns"])
        )
        total = max(box, float(scored))
        if not total and unknown:  # a TD with an unnamed scorer might be his
            return StatResult("stat_unavailable")
        return StatResult("ok", total)

    def one(name: str) -> float | None:
        group, key = _STAT_KEYS[(league, name)]
        if name == "pitcher_outs":  # innings "6.1" = 6 full + 1 out
            ip = raw(key, group)
            m = re.match(r"^\s*(\d+)(?:\.(\d))?", str(ip)) if ip is not None else None
            return int(m.group(1)) * 3 + int(m.group(2) or 0) if m else None
        return value(key, group)

    parts = [one(p) for p in _COMBOS.get((league, stat), (stat,))]
    if None in parts:
        # NFL box scores only list a player under groups where he recorded something.
        if league == "NFL":
            return StatResult("ok", 0.0)
        return StatResult("stat_unavailable")
    return StatResult("ok", float(sum(parts)))
