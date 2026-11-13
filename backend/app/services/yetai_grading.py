"""One grader for every YetAI pick: league/market-agnostic, driven by ESPN results.

`grade_pick` reads the contract `prediction_factors["grading"]` metadata when present and
otherwise derives the same fields from the row (admin picks, older rows). It never writes;
callers persist the returned `Outcome`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

from app.services import espn_results, mlb_results

_ET = ZoneInfo("America/New_York")
_GAME_MARKETS = ("moneyline", "spread", "total")
SOCCER = "SOCCER"  # generic "Soccer" admin label: league is resolved by searching ESPN


@dataclass(frozen=True)
class Outcome:
    kind: str  # won | lost | pushed | void | not_ready | error | ungradeable
    result: str  # text for won/lost/pushed; reason for the others


# not_ready reasons that mean "ESPN says the game has not finished": never voided early.
WAITING = ("scheduled", "in_progress")


_ODDS_API_LEAGUES = {
    "basketball_nba": "NBA",
    "basketball_wnba": "WNBA",
    "basketball_ncaab": "NCAAB",
    "americanfootball_nfl": "NFL",
    "americanfootball_ncaaf": "NCAAF",
    "icehockey_nhl": "NHL",
    "baseball_mlb": "MLB",
    "soccer_epl": "EPL",
    "soccer_usa_mls": "MLS",
    "soccer_uefa_champs_league": "UCL",
    "soccer_spain_la_liga": "LALIGA",
    "soccer_germany_bundesliga": "BUNDESLIGA",
    "soccer_italy_serie_a": "SERIEA",
    "soccer_france_ligue_one": "LIGUE1",
}
_LABELS = {  # admin sport labels (yetai_bets_service_db._ADMIN_SPORT_TO_GAME_META)
    "NCAA FOOTBALL": "NCAAF",
    "NCAA BASKETBALL": "NCAAB",
    "COLLEGE FOOTBALL": "NCAAF",
    "COLLEGE BASKETBALL": "NCAAB",
    "SOCCER": SOCCER,
}


def normalize_league(sport: str | None) -> str | None:
    key = (sport or "").strip()
    if key.lower() in _ODDS_API_LEAGUES:
        return _ODDS_API_LEAGUES[key.lower()]
    key = key.upper()
    if key in espn_results.LEAGUES:
        return key
    return _LABELS.get(key)


def can_grade(league: str, market: str, stat: str | None = None) -> bool:
    lg = normalize_league(league)
    if lg is None:
        return False
    if market in _GAME_MARKETS:
        return lg == SOCCER or lg in espn_results.LEAGUES
    if market == "player_prop":
        return stat in espn_results.PROP_STATS.get(
            lg, ()
        ) or stat in mlb_results.PROP_STATS.get(lg, ())
    return False


_NUM = r"\d+(?:\.\d+)?"
_PAREN = re.compile(r"\([^)]*\)")
_OVER_UNDER = re.compile(rf"\b(?:(over|under)\s*|([ou])(?=\d))({_NUM})", re.I)
_TOKEN = re.compile(r"(?<![\w.])[+-]?\d+(?:\.\d+)?(?![\w.])")
_PICK = re.compile(r"\b(?:pk|pick'?em|pick)\b", re.I)


def _over_under(text: str) -> tuple[str, float] | None:
    m = _OVER_UNDER.search(text)
    if not m:
        return None
    word = (m.group(1) or m.group(2)).lower()
    return ("over" if word.startswith("o") else "under"), float(m.group(3))


_ODDS_TAIL = re.compile(r"\s[+-]\d{3,}(?:\.\d+)?\s*$")


def parse_line(selection: str) -> float | None:
    """Over/under number, else the spread: a trailing American-odds token is ignored."""
    text = _PAREN.sub(" ", selection or "")
    ou = _over_under(text)
    if ou:
        return ou[1]
    text = _ODDS_TAIL.sub(" ", f" {text}")
    tokens = [float(t) for t in _TOKEN.findall(text)]
    if tokens:
        return tokens[-1] if abs(tokens[-1]) < 100 else None
    return 0.0 if _PICK.search(text) else None


# Partial-game and team-total markets: never graded as the full-game market.
_PARTIAL = re.compile(
    r"\b(?:[12]h|1st half|2nd half|first half|second half|half ?time|"
    r"[1-4]q|q[1-4]|[1-4](?:st|nd|rd|th) quarter|"
    r"(?:first|second|third|fourth) quarter|quarter|"
    r"[1-3]p|[1-3](?:st|nd|rd) period|(?:first|second|third) period|"
    r"f5|f3|first (?:5|five|3|three) innings?|1st (?:5|3) innings?|innings?|"
    r"team total|tt|alt(?:ernate)?|race to|both teams|btts|anytime|"
    r"draw no bet|double chance|correct score|handicap)\b",
    re.I,
)


# "Player Anytime TD", "anytime touchdown", "to score a touchdown", "ATD", ["Yes"|"No"]
_ANYTIME_TD = re.compile(
    r"\b(?:any ?time (?:td|touchdown)(?: scorer)?|to score (?:a|an) (?:td|touchdown)|atd)\b",
    re.I,
)


def unsupported_market(text: str | None) -> str | None:
    text = text or ""
    if _ANYTIME_TD.search(text):  # a supported pick: "(anytime)" is part of it
        text = re.sub(
            r"\(\s*any ?time\s*\)", " ", _ANYTIME_TD.sub(" ", text), flags=re.I
        )
    m = _PARTIAL.search(text)
    return m.group(0) if m else None


_JUNK = {
    "first",
    "last",
    "scorer",
    "td",
    "tds",
    "touchdown",
    "touchdowns",
    "or",
    "and",
    "not",
}


def _parse_anytime_td(selection: str) -> dict | None:
    """Player and side of an anytime-TD pick; None when the text says more than that
    (2+ TDs, first/last scorer, combos, odds in the middle): not gradeable as anytime TD.
    """
    raw = selection or ""
    if not _ANYTIME_TD.search(_PAREN.sub(" ", raw)):
        return None
    # "(No)" / "(Yes)" is the side: read it before the parentheses are dropped
    paren = {m.lower() for m in re.findall(r"\(\s*(yes|no)\s*\)", raw, re.I)}
    text = _ODDS_TAIL.sub(" ", f" {_PAREN.sub(' ', raw)}")
    words = (
        _ANYTIME_TD.sub(" ", text)
        .replace("-", " ")
        .replace("–", " ")
        .replace(":", " ")
        .split()
    )
    bare = set()
    for i in (-1, 0):
        if words and words[i].lower() in ("yes", "no"):
            bare.add(words.pop(i).lower())
    sides = paren | bare
    if len(sides) > 1 or not words:
        return None
    if any(re.search(r"[\d&/+]", w) or w.lower() in _JUNK for w in words):
        return None
    return {
        "player": " ".join(words),
        "side": sides.pop() if sides else "yes",
        "line": None,
        "stat": "anytime_td",
    }


_norm = espn_results._norm


def _pick_side(selection: str, home: str, away: str) -> str | None:
    """Side whose name, nickname or location appears in the selection; longest match wins."""
    text = f" {_norm(_PAREN.sub(' ', selection))} "
    best: dict[str, int] = {}
    for side, team in (("home", home), ("away", away)):
        words = _norm(team).split()
        # full name, nickname tail ("76ers", "Trail Blazers"), location head ("Ohio State")
        cands = {" ".join(words[-n:]) for n in (1, 2)} | {
            " ".join(words[:n]) for n in (1, 2, 3) if n < len(words)
        }
        cands.add(" ".join(words))
        hits = [len(c) for c in cands if c and f" {c} " in text]
        if hits:
            best[side] = max(hits)
    if not best or (len(best) == 2 and best["home"] == best["away"]):
        return None
    return max(best, key=best.get)


_STAT_WORDS = {
    "points": "points",
    "point": "points",
    "pts": "points",
    "rebounds": "rebounds",
    "rebs": "rebounds",
    "reb": "rebounds",
    "assists": "assists",
    "ast": "assists",
    "steals": "steals",
    "stl": "steals",
    "blocks": "blocks",
    "blk": "blocks",
    "threes": "threes",
    "3pm": "threes",
    "3 pointers": "threes",
    "3 pointers made": "threes",
    "three pointers": "threes",
    "three pointers made": "threes",
    "threes made": "threes",
    "turnovers": "turnovers",
    "to": "turnovers",
    "pra": "pra",
    "pts reb ast": "pra",
    "p r a": "pra",
    "points rebounds assists": "pra",
    "pr": "pr",
    "p r": "pr",
    "pts reb": "pr",
    "points rebounds": "pr",
    "pa": "pa",
    "p a": "pa",
    "pts ast": "pa",
    "points assists": "pa",
    "ra": "ra",
    "r a": "ra",
    "reb ast": "ra",
    "rebounds assists": "ra",
    "blocks steals": "blocks_steals",
    "blk stl": "blocks_steals",
    "goals": "goals",
    "goals scored": "goals",
    "blocked shots": "blocked_shots",
    "pass tds": "passing_tds",
    "passing tds": "passing_tds",
    "passing touchdowns": "passing_tds",
    "pass completions": "pass_completions",
    "completions": "pass_completions",
    "receptions": "receptions",
    "rec": "receptions",
    "strikeouts": "strikeouts",
    "ks": "strikeouts",
    "pitcher strikeouts": "strikeouts",
    "hits": "hits",
    "batter hits": "hits",
    "batter home runs": "home_runs",
    "batter total bases": "total_bases",
    "batter rbis": "rbis",
    "rbis": "rbis",
    "rbi": "rbis",
    "batter strikeouts": "batter_strikeouts",
    "pitcher outs": "pitcher_outs",
    "outs recorded": "pitcher_outs",
    "pitcher outs recorded": "pitcher_outs",
    "home runs": "home_runs",
    "home run": "home_runs",
    "hr": "home_runs",
    "total bases": "total_bases",
    "passing yards": "passing_yards",
    "pass yards": "passing_yards",
    "receiving yards": "receiving_yards",
    "rec yards": "receiving_yards",
    "rushing yards": "rushing_yards",
    "rush yards": "rushing_yards",
    "saves": "saves",
    "goalie saves": "saves",
    "shots on goal": "shots_on_goal",
    "sog": "shots_on_goal",
}
_PROP_A = re.compile(rf"^(.+?)\s+(over|under)\s+({_NUM})\s+(.+)$", re.I)
_PROP_B = re.compile(rf"^(over|under)\s+({_NUM})\s+(.+?)\s+-\s+(.+)$", re.I)


def _parse_prop(selection: str) -> dict | None:
    text = _PAREN.sub(" ", selection or "").strip()
    if m := _PROP_A.match(text):
        player, side, line, stat = m.groups()
    elif m := _PROP_B.match(text):
        side, line, stat, player = m.groups()
    else:
        return None
    # an unknown stat still parses: can_grade then voids it with the stat named
    stat = _STAT_WORDS.get(_norm(stat)) or _norm(stat).replace(" ", "_")
    if not stat:
        return None
    return {
        "player": player.strip(),
        "side": side.lower(),
        "line": float(line),
        "stat": stat,
    }


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _meta(bet) -> dict | None:
    factors = getattr(bet, "prediction_factors", None)
    g = factors.get("grading") if isinstance(factors, dict) else None
    return g if isinstance(g, dict) and g.get("market") and g.get("league") else None


def game_day_for(bet_like) -> date | None:
    meta = _meta(bet_like)
    if meta and (d := _to_date(meta.get("game_date"))):
        return d
    ct = getattr(bet_like, "commence_time", None)
    if ct:
        if ct.tzinfo is None:
            ct = ct.replace(tzinfo=timezone.utc)
        return ct.astimezone(_ET).date()
    factors = getattr(bet_like, "prediction_factors", None)
    m = re.search(
        r"(\d{4}-\d{2}-\d{2})",
        str(factors.get("event_id") or "") if isinstance(factors, dict) else "",
    )
    if m:
        return date.fromisoformat(m.group(1))
    created = getattr(bet_like, "created_at", None)
    return created.date() if created else None


def _market_of(bet_like) -> str | None:
    bt = getattr(bet_like, "bet_type", None)
    bt = str(getattr(bt, "value", bt) or "").lower()
    if bt in _GAME_MARKETS:
        return bt
    return "player_prop" if bt in ("prop", "player_prop") else None


def grading_spec(bet_like) -> dict | None:
    home = getattr(bet_like, "home_team", None)
    away = getattr(bet_like, "away_team", None)
    meta = _meta(bet_like)
    if meta:
        spec = dict(meta)
        spec["league"] = normalize_league(spec["league"]) or spec["league"]
        spec.setdefault("home_team", home)
        spec.setdefault("away_team", away)
        if not spec.get("game_date"):
            spec["game_date"] = game_day_for(bet_like)
        return spec

    league = normalize_league(getattr(bet_like, "sport", None))
    market = _market_of(bet_like)
    day = game_day_for(bet_like)
    sel = getattr(bet_like, "selection", None) or ""
    if not (league and market and day and home and away):
        return None
    spec = {
        "market": market,
        "league": league,
        "game_date": day.isoformat(),
        "home_team": home,
        "away_team": away,
    }
    if market == "player_prop":
        prop = _parse_anytime_td(sel) or _parse_prop(sel)
        return {**spec, **prop} if prop else None
    if market == "total":
        ou = _over_under(_PAREN.sub(" ", sel))
        return {**spec, "side": ou[0], "line": ou[1]} if ou else None
    side = _pick_side(sel, home, away)
    if not side and market == "moneyline" and re.search(r"\b(?:draw|tie)\b", sel, re.I):
        side = "draw"
    if not side:
        return None
    if market == "spread":
        line = parse_line(sel)
        if line is None:
            return None
        return {**spec, "side": side, "line": line}
    return {**spec, "side": side, "line": None}


def _fmt(n: float) -> str:
    return f"{n:g}"


def _compare(value: float, line: float, side: str) -> str:
    if value == line:
        return "pushed"
    return "won" if (value > line) == (side == "over") else "lost"


class EspnPayloadError(Exception):
    """ESPN answered, but the payload is not shaped as expected: retry, never void."""


def _espn(fn, *args, **kwargs):
    """Call espn_results; transport errors pass through, anything else is a bad payload."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        if _transport_error(exc):
            raise
        raise EspnPayloadError(f"{type(exc).__name__}: {str(exc)[:100]}") from exc


def _find_games(league: str, spec: dict, day: date, commence_time, exact_day: bool):
    leagues = [league]
    if league == SOCCER:
        soccer = espn_results.SOCCER_LEAGUES
        leagues = [lg for lg in ("EPL", "MLS", "UCL") if lg in soccer]
        leagues += sorted(soccer - set(leagues))
    for lg in leagues:
        games = _espn(
            espn_results.find_games,
            lg,
            spec["home_team"],
            spec["away_team"],
            day,
            commence_time,
            exact_day,
        )
        if games:
            return lg, games
    return league, []


_GAME_HINT = re.compile(r"\b(?:game|gm|g)\s*#?\s*([12])\b", re.I)


def game_number(spec: dict, bet_like) -> int | None:
    """Doubleheader hint: spec["game_number"] or "Game 2" / "G2" in the pick text."""
    n = spec.get("game_number")
    if n is None and (m := _GAME_HINT.search(getattr(bet_like, "selection", "") or "")):
        n = m.group(1)
    try:
        return int(n) if n is not None and int(n) in (1, 2) else None
    except (TypeError, ValueError):
        return None


def _transport_error(exc: Exception) -> bool:
    return isinstance(exc, (requests.RequestException, json.JSONDecodeError))


def grade_pick(bet_like, db=None) -> Outcome:
    """Never raises: ESPN trouble (transport or payload) is ``error`` and retried, bad
    pick metadata is ``ungradeable``. Which one is decided by where the exception was
    raised (``_espn`` wraps every ESPN call), not by its type."""
    try:
        if not _meta(bet_like):  # free text: refuse partial-game / team-total markets
            bad = unsupported_market(getattr(bet_like, "selection", None))
            if bad:
                return Outcome("ungradeable", f"Unsupported market: {bad}")
        spec = grading_spec(bet_like)
        if not spec:
            return Outcome("ungradeable", "Could not parse pick")
        return _grade(spec, bet_like)
    except Exception as exc:
        if _transport_error(exc):
            return Outcome("error", f"ESPN error: {str(exc)[:120]}")
        if isinstance(exc, EspnPayloadError):
            return Outcome("error", f"ESPN payload: {exc}")
        if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)):
            return Outcome("ungradeable", f"Bad pick data: {type(exc).__name__}")
        return Outcome("error", f"{type(exc).__name__}: {str(exc)[:120]}")


def _grade(spec: dict, bet_like) -> Outcome:
    day = _to_date(spec.get("game_date"))
    side = spec.get("side")
    league, market, stat = spec["league"], spec["market"], spec.get("stat")
    yes_no = market == "player_prop" and stat == "anytime_td"
    if yes_no:  # default side is yes; the line is meaningless
        side = str(side or "yes").lower()
        spec = {**spec, "side": side, "line": None}
    sides = ("home", "away", "over", "under") + (
        ("draw",) if market == "moneyline" else ()
    )
    if yes_no:
        sides = ("yes", "no")
    if (
        not day
        or not isinstance(spec.get("home_team"), str)
        or not isinstance(spec.get("away_team"), str)
        or not spec["home_team"]
        or not spec["away_team"]
        or side not in sides
    ):
        return Outcome("ungradeable", "Could not parse pick")
    if not can_grade(league, market, stat):
        extra = f" {stat}" if stat else ""
        return Outcome("ungradeable", f"Unsupported: {league} {market}{extra}")
    line = spec.get("line")
    if market in ("spread", "total", "player_prop") and not yes_no:
        if line is None:
            return Outcome("ungradeable", "Could not parse pick")
        line = float(line)  # "220.5" is fine; "abc" -> ValueError -> ungradeable
    if market == "player_prop" and not isinstance(spec.get("player"), str):
        return Outcome("ungradeable", "Could not parse pick")

    soccer_line = league == SOCCER or league in espn_results.SOCCER_LEAGUES
    if soccer_line and market in ("spread", "total") and abs(line * 4) % 2 == 1:
        # Asian quarter lines (-0.25, 2.75) split the stake; this grader has no half results.
        return Outcome("ungradeable", f"Quarter-ball line {_fmt(line)} not supported")

    # a slate date from metadata is exact; a guessed one (admin free text) may be a day off
    exact_day = bool(_meta(bet_like)) and not getattr(bet_like, "commence_time", None)
    league, games = _find_games(
        league, spec, day, getattr(bet_like, "commence_time", None), exact_day
    )
    if not games:
        return Outcome("not_ready", "Game not found")
    if getattr(bet_like, "commence_time", None):
        games = games[:1]  # nearest start
    elif len(games) > 1 and (n := game_number(spec, bet_like)) and n <= len(games):
        games = [games[n - 1]]  # games come back earliest first
    outcomes = [_grade_game(spec, league, g, line) for g in games]
    if len({(o.kind, o.result) for o in outcomes}) == 1 or len(outcomes) == 1:
        return outcomes[0]
    if all(o.kind == outcomes[0].kind for o in outcomes) and outcomes[0].kind in (
        "won",
        "lost",
        "pushed",
    ):
        return outcomes[0]  # doubleheader, same result either game
    waiting = [o for o in outcomes if o.kind == "not_ready" and o.result in WAITING]
    if waiting:
        return waiting[0]
    return Outcome(
        "not_ready",
        "Doubleheader: the games differ and the pick does not say which (add Game 1/2)",
    )


def _grade_game(spec: dict, league: str, game, line) -> Outcome:
    market, side, stat = spec["market"], spec["side"], spec.get("stat")
    if game.state == "postponed":
        return Outcome("void", "Postponed")
    if game.state == "cancelled":
        return Outcome("void", "Cancelled")
    if game.state != "final":
        return Outcome("not_ready", game.state)

    soccer = league in espn_results.SOCCER_LEAGUES
    if side == "draw" and not soccer:
        return Outcome("ungradeable", f"Draw pick in {league}")

    if market == "player_prop":
        player = spec["player"]
        if stat == "total_bases":
            stat_res = _espn(
                mlb_results.total_bases, game, _to_date(spec["game_date"]), player
            )
        else:
            stat_res = _espn(
                espn_results.player_stat, league, game.event_id, player, stat
            )
        if stat_res.status == "did_not_play":
            return Outcome("void", f"DNP: {player}")
        if stat_res.status == "stat_unavailable":
            # final box score, player present, but the stat does not exist for his role
            if stat == "anytime_td":  # a TD play with no scorer we can name
                return Outcome(
                    "ungradeable", f"Touchdown scorer not identifiable: {player}"
                )
            return Outcome("ungradeable", f"Stat not recorded for {player}: {stat}")
        if stat_res.status == "ambiguous":
            return Outcome("ungradeable", f"Ambiguous player name: {player}")
        if stat_res.status != "ok":
            return Outcome("not_ready", f"Player not in box score: {player}")
        if stat == "anytime_td":
            kind = "won" if (stat_res.value > 0) == (side == "yes") else "lost"
            return Outcome(
                kind,
                f"{kind.title()}: {player} anytime TD {side} ({_fmt(stat_res.value)} TD)",
            )
        kind = _compare(stat_res.value, line, side)
        label = stat.replace("_", " ")
        return Outcome(
            kind,
            f"{kind.title()}: {player} {side} {_fmt(line)} {label} ({_fmt(stat_res.value)})",
        )

    if game.home_score is None or game.away_score is None:
        if soccer:  # extra time/penalties and no derivable 90-minute score
            return Outcome("void", f"No regulation score: {game.detail}")
        return Outcome("not_ready", "No final score")
    hs, aws = game.home_score, game.away_score
    if market == "total":
        kind = _compare(hs + aws, line, side)
        return Outcome(
            kind, f"{kind.title()}: {side.title()} {_fmt(line)} (total {hs + aws})"
        )

    if side == "draw":
        kind = "won" if hs == aws else "lost"
        return Outcome(kind, f"{kind.title()}: Draw ({hs}-{aws})")
    mine, theirs = (hs, aws) if side == "home" else (aws, hs)
    team = spec["home_team"] if side == "home" else spec["away_team"]
    score = f"{mine}-{theirs}"
    if market == "moneyline":
        if mine == theirs:
            kind = "lost" if soccer else "pushed"
        else:
            kind = "won" if mine > theirs else "lost"
        return Outcome(kind, f"{kind.title()}: {team} ML ({score})")
    kind = _compare(mine + line, theirs, "over")
    return Outcome(kind, f"{kind.title()}: {team} {line:+g} ({score})")
