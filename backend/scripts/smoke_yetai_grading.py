"""Live smoke test for yetai_grading against the public ESPN API. No DB, stdout only.

Usage: PYTHONPATH=. python scripts/smoke_yetai_grading.py [--date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.models.database_models import BetType, YetAIBet
from app.services import espn_results as er
from app.services.yetai_grading import grade_pick

TERMINAL = {"won", "lost", "pushed"}


def final_games(league: str, day: date) -> list[dict]:
    games = []
    for ev in er._scoreboard(league, day):
        comp = (ev.get("competitions") or [{}])[0]
        st = (comp.get("status") or ev.get("status") or {}).get("type", {})
        sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        if er._state(st) != "final" or len(sides) != 2:
            continue
        h, a = sides["home"], sides["away"]
        hs, as_ = er._score(h.get("score")), er._score(a.get("score"))
        if hs is None or as_ is None:
            continue
        games.append(
            {
                "id": str(ev["id"]),
                "home": h["team"]["displayName"],
                "away": a["team"]["displayName"],
                "hs": hs,
                "as": as_,
                "start": er._parse_time(ev.get("date")),
            }
        )
    return games


def find_prop(league: str, g: dict) -> tuple[str, str, float] | None:
    """(player, stat, value) for a box-score player with a gradeable stat."""
    sport, slug, _ = er.LEAGUES[league]
    summary = er._get_json(f"{er.BASE_URL}/{sport}/{slug}/summary", {"event": g["id"]})
    names = []
    for team in (summary.get("boxscore") or {}).get("players", []):
        for grp in team.get("statistics", []):
            for ath in grp.get("athletes", []):
                if ath.get("stats"):
                    names.append(ath["athlete"]["displayName"])
    for stat in sorted(er.PROP_STATS[league]):
        for name in names[:60]:
            r = er.player_stat(league, g["id"], name, stat)
            if r.status == "ok" and r.value >= 1:
                return name, stat, r.value
    return None


def picks_for(league: str, g: dict) -> list[tuple[str, YetAIBet]]:
    day = (
        g["start"]
        .replace(tzinfo=ZoneInfo("UTC"))
        .astimezone(ZoneInfo("America/New_York"))
        .date()
    )
    base = dict(
        sport=league,
        home_team=g["home"],
        away_team=g["away"],
        commence_time=g["start"],
        created_at=g["start"],
        odds=-110,
        confidence=60,
        title="smoke",
    )

    def bet(btype, selection, **grading):
        meta = {
            "league": league,
            "game_date": day.isoformat(),
            "home_team": g["home"],
            "away_team": g["away"],
            **grading,
        }
        return YetAIBet(
            bet_type=btype,
            selection=selection,
            prediction_factors={"grading": meta} if grading else None,
            **base,
        )

    total = g["hs"] + g["as"]
    out = [
        (
            "moneyline",
            bet(BetType.MONEYLINE, f"{g['home']} ML", market="moneyline", side="home"),
        ),
        (
            "spread",
            bet(
                BetType.SPREAD,
                f"{g['away']} +3.5",
                market="spread",
                side="away",
                line=3.5,
            ),
        ),
        (
            "total",
            bet(
                BetType.TOTAL,
                f"Over {total - 0.5:g}",
                market="total",
                side="over",
                line=total - 0.5,
            ),
        ),
    ]
    if league in er.PROP_STATS and (p := find_prop(league, g)):
        player, stat, val = p
        out.append(
            (
                "player_prop",
                bet(
                    BetType.PROP,
                    f"{player} Over {val - 0.5:g} {stat}",
                    market="player_prop",
                    side="over",
                    line=val - 0.5,
                    player=player,
                    stat=stat,
                ),
            )
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    args = ap.parse_args()
    day = (
        date.fromisoformat(args.date)
        if args.date
        else datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    )
    print(f"== Smoke date {day} ==")
    for league in er.LEAGUES:
        games = final_games(league, day)
        if not games:
            print(f"{league}: no games")
            continue
        counts: Counter = Counter()
        for g in games[:2]:
            matchup = f"{g['away']} @ {g['home']} ({g['as']}-{g['hs']})"
            picks = picks_for(league, g)
            fb = f"{g['home']} -1.5"
            picks.append(
                (
                    "spread(text)",
                    YetAIBet(
                        sport=league,
                        bet_type=BetType.SPREAD,
                        selection=fb,
                        home_team=g["home"],
                        away_team=g["away"],
                        commence_time=g["start"],
                        created_at=g["start"],
                    ),
                )
            )
            for market, b in picks:
                o = grade_pick(b)
                counts[o.kind] += 1
                flag = "" if o.kind in TERMINAL else "  <-- NON-TERMINAL"
                print(
                    f"{league} | {matchup} | {market} | {b.selection} | "
                    f"{o.kind} | {o.result}{flag}"
                )
        print(f"{league} summary: {dict(counts)}")


if __name__ == "__main__":
    main()
