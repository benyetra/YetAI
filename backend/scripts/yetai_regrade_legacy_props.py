#!/usr/bin/env python3
"""Regrade legacy auto prop picks voided as "Ungradeable: Could not parse pick".

Those rows know the player, stat, side, line and only the OPPONENT (home_team/away_team
are NULL), so the grader cannot find the game. This finds the opponent's single game on
the pick's day via ESPN, builds the grading block new auto picks carry, and grades an
in-memory copy.

Dry run (default) writes nothing, one line per row:
  cd backend
  DATABASE_URL=<prod url> PYTHONPATH=. python scripts/yetai_regrade_legacy_props.py
  ... --ids ID1,ID2     also consider these void rows
Apply (rows the grader settles to won/lost/pushed/void-DNP only; the rest stay as they are):
  ... --apply

--apply does what admin "reopen" does (active, result cleared, settlement dropped, linked
copies mirrored back to PENDING) but WITHOUT its 24h auto-grade hold, then calls the
service's own _settle_one immediately, so status/result/settled_at/audit trail/copies are
written by the normal settle code. Idempotent: settled rows are no longer candidates.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PREFIX = "Ungradeable: Could not parse pick"
SETTLES = ("won", "lost", "pushed", "void")


def _factors(bet) -> dict:
    return bet.prediction_factors if isinstance(bet.prediction_factors, dict) else {}


def _meta(bet) -> dict:
    return _factors(bet).get("projection_metadata") or {}


def candidates(db, ids=()):
    from app.models.database_models import BetSource, BetType, YetAIBet

    rows = db.query(YetAIBet).filter(YetAIBet.status == "void").all()
    out = []
    for b in rows:
        m = _meta(b)
        legacy = (
            b.source == BetSource.AUTO
            and (b.result or "").startswith(PREFIX)
            and b.bet_type == BetType.PROP
        )
        if (legacy or b.id in ids) and all(
            m.get(k) for k in ("player", "stat", "side")
        ) and (m.get("opponent") or m.get("opponent_team_name")):
            out.append(b)
    return sorted(out, key=lambda b: b.created_at or datetime.min)


def resolve_game(bet, league: str):
    """(grading block, 'Away @ Home (day)') or (None, reason). Never guesses."""
    from app.services import espn_results as er
    from app.services.yetai_grading import game_day_for

    m = _meta(bet)
    day = game_day_for(bet)
    opp = m.get("opponent_team_name") or m.get("opponent")
    if not day:
        return None, "no game day"
    for d in (day, day + timedelta(days=1)):  # day+1 only when day has no game
        hits = []
        for ev in er._scoreboard(league, d):
            comp = (ev.get("competitions") or [{}])[0]
            sides = {c.get("homeAway"): c["team"] for c in comp.get("competitors", [])}
            if {"home", "away"} <= sides.keys() and any(
                er._team_matches(opp, t) for t in sides.values()
            ):
                hits.append(sides)
        if len(hits) > 1:
            return None, f"{len(hits)} games for {opp} on {d}"
        if hits:
            home, away = (hits[0][k].get("displayName") for k in ("home", "away"))
            block = {
                "market": "player_prop",
                "league": league,
                "game_date": d.isoformat(),
                "home_team": home,
                "away_team": away,
                "side": m["side"],
                "line": _factors(bet).get("market_line"),
                "player": m["player"],
                "stat": m["stat"],
            }
            note = "" if d == day else f" [day+1 used, pick day {day}]"
            return block, f"{away} @ {home} {d}{note}"
    return None, f"no game for {opp} on {day} or next day"


def _copies(db, bet) -> int:
    from app.services.yetai_bets_service_db import YetAIBetsServiceDB

    return len(YetAIBetsServiceDB()._linked_unified_bets_for_yetai_pick(db, bet))


def regrade(db, apply: bool, ids=()) -> list[str]:
    from app.models.database_models import YetAIBet
    from app.services import yetai_grading as yg
    from app.services.yetai_bets_service_db import YetAIBetsServiceDB

    lines = []
    for bet in candidates(db, ids):
        head = f"{bet.id} {bet.selection!r}"
        league = yg.normalize_league(bet.sport)
        if not league or _factors(bet).get("market_line") is None:
            lines.append(f"{head} UNRESOLVED: no league/line")
            continue
        block, game = resolve_game(bet, league)
        if not block:
            lines.append(f"{head} UNRESOLVED: {game}")
            continue
        probe = YetAIBet(  # transient, never added to the session
            selection=bet.selection,
            bet_type=bet.bet_type,
            sport=bet.sport,
            prediction_factors={"grading": block},
        )
        out = yg.grade_pick(probe)
        copies = _copies(db, bet)
        line = f"{head} game={game} grader={out.kind} ({out.result}) copies={copies}"
        if out.kind not in SETTLES:
            lines.append(f"{line} SKIP (left as is)")
            continue
        if not apply:
            lines.append(f"{line} would settle")
            continue
        svc, now = YetAIBetsServiceDB(), datetime.utcnow()
        factors = {k: v for k, v in _factors(bet).items() if k != "settlement"}
        factors["grading"] = block
        bet.prediction_factors = factors
        bet.status, bet.settled_at, bet.result = "active", None, None
        svc.mirror_to_linked_copies(db, bet)  # what admin reopen does, minus its hold
        svc._settle_one(db, bet, now)
        if bet.status != out.kind:  # re-grade disagreed: undo, leave untouched
            got = bet.status
            db.rollback()
            lines.append(f"{line} ROLLED BACK: settle gave {got}")
            continue
        db.commit()
        lines.append(f"{line} APPLIED -> {bet.status}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--ids", default="", help="extra void row ids, comma-separated")
    args = parser.parse_args()

    from scripts._db_script_guard import assert_not_local_default_db

    assert_not_local_default_db()
    from app.core.database import SessionLocal

    ids = {i.strip() for i in args.ids.split(",") if i.strip()}
    db = SessionLocal()
    try:
        lines = regrade(db, args.apply, ids)
        print("\n".join(lines) or "no candidates")
        print(f"{'APPLY' if args.apply else 'DRY RUN'}: {len(lines)} row(s)")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
