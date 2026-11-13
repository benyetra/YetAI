"""MLB batter total bases from the MLB Stats API box score.

ESPN's MLB box score has no 2B/3B columns, so this one stat comes from statsapi.mlb.com. The
game itself (state, doubleheader order, postponements) is still resolved by `espn_results`;
here the ESPN game is mapped to its gamePk by team names and start time. Transport errors
propagate (the grader retries); "player not found" and "did not play" are `StatResult`s like
the ESPN path.
"""

from __future__ import annotations

from datetime import date, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services import espn_results as er

BASE_URL = "https://statsapi.mlb.com/api/v1"
PROP_STATS = {"MLB": frozenset({"total_bases"})}
_MAX_START_GAP = timedelta(minutes=90)
_ET = ZoneInfo("America/New_York")


def find_game_pk(game: er.GameResult, day: date) -> int | None:
    """gamePk of the schedule game with the same two teams.

    Two games of the pair on the date (a doubleheader) map by order: ESPN's chronological
    game number to the schedule's gameNumber (a traditional doubleheader's game 2 carries a
    placeholder start time, so times cannot be compared). One game maps by start time.
    """
    want = {er._norm(t) for t in game.teams}
    found = []
    for d in er._get_json(f"{BASE_URL}/schedule", {"sportId": "1", "date": str(day)})[
        "dates"
    ]:
        for g in d["games"]:
            names = {er._norm(g["teams"][s]["team"]["name"]) for s in ("home", "away")}
            if names == want:
                found.append(g)
    if len(found) > 1:
        if not game.number:
            return None  # cannot tie the ESPN game to one of them: never guess
        found = [g for g in found if g.get("gameNumber") == game.number]
        return found[0]["gamePk"] if len(found) == 1 else None
    if found and game.start_time:
        start = er._parse_time(found[0].get("gameDate"))
        if start and abs(start - game.start_time) > _MAX_START_GAP:
            return None
    return found[0]["gamePk"] if found else None


def total_bases(game: er.GameResult, day: date, player: str) -> er.StatResult:
    if game.start_time:  # the game's own (ET) date, not the pick's guess
        day = game.start_time.replace(tzinfo=timezone.utc).astimezone(_ET).date()
    pk = find_game_pk(game, day)
    if pk is None:
        return er.StatResult("not_found")
    box = er._get_json(f"{BASE_URL}/game/{pk}/boxscore")
    want, exact = er._person(player), er._norm(player)
    hits = [
        p
        for side in ("home", "away")
        for p in box["teams"][side]["players"].values()
        if er._person(p["person"]["fullName"]) == want
    ]
    if (
        len({p["person"]["id"] for p in hits}) > 1
    ):  # "X Jr." and "X": exact name decides
        hits = [p for p in hits if er._norm(p["person"]["fullName"]) == exact]
        if len({p["person"]["id"] for p in hits}) != 1:
            return er.StatResult("ambiguous")
    if not hits:
        return er.StatResult("not_found")
    batting = hits[0]["stats"].get("batting") or {}
    if not batting.get(
        "plateAppearances"
    ):  # bench, pitcher who did not bat, pinch runner
        return er.StatResult("did_not_play")
    return er.StatResult("ok", float(batting["totalBases"]))
