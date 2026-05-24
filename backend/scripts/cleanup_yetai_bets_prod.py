#!/usr/bin/env python3
"""
Production YetAI bets cleanup: reject demo seeds + repair MLB prop matchups.

Run against Railway Postgres (not the local default DB).

Usage:
  export DATABASE_URL='postgresql://...'   # from Railway Postgres → Connect
  cd backend
  PYTHONPATH=. .venv/bin/python scripts/cleanup_yetai_bets_prod.py --dry-run
  PYTHONPATH=. .venv/bin/python scripts/cleanup_yetai_bets_prod.py
"""

from __future__ import annotations

import argparse
import re
import sys

try:
    from app.core.database import SessionLocal
except ModuleNotFoundError as exc:
    if exc.name == "sqlalchemy":
        print(
            "Use backend venv:\n"
            "  PYTHONPATH=. .venv/bin/python scripts/cleanup_yetai_bets_prod.py",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    raise

from pathlib import Path

_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))
from _db_script_guard import assert_not_local_default_db  # noqa: E402

from app.models.database_models import BetType, YetAIBet
from app.models.predictions_models import Pitcher
from app.services.yetai_bets_demo import DEMO_MATCHUP_TITLES, is_demo_yetai_bet
from app.services.yetai_bets_display import (
    subscriber_game_label,
    title_looks_like_prop_line,
)

PROP_TITLE_RE = re.compile(r"\b(under|over)\b", re.I)
MLB_PROP_EVENT_RE = re.compile(r"mlb-prop-\d{4}-\d{2}-\d{2}-([^-]+)-strikeouts", re.I)
VISIBLE = {"active", "pending", "won", "lost", "pushed"}


def _pitcher_name_from_selection(selection: str) -> str | None:
    m = re.match(
        r"^(.+?)\s+(UNDER|OVER)\s+[\d.]+\s+\w+",
        selection.strip(),
        re.I,
    )
    return m.group(1).strip() if m else None


def _pitcher_meta_for_bet(
    bet: YetAIBet,
    by_name: dict[str, Pitcher],
    by_id: dict[str, Pitcher],
) -> Pitcher | None:
    factors = bet.prediction_factors if isinstance(bet.prediction_factors, dict) else {}
    event_id = str(factors.get("event_id") or "")
    pid_match = MLB_PROP_EVENT_RE.search(event_id)
    if pid_match:
        meta = by_id.get(pid_match.group(1))
        if meta:
            return meta

    name = _pitcher_name_from_selection(bet.selection or bet.title or "")
    if not name:
        return None
    key = name.lower()
    if key in by_name:
        return by_name[key]
    for pitcher_key, meta in by_name.items():
        if key in pitcher_key or pitcher_key in key:
            return meta
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    assert_not_local_default_db()

    db = SessionLocal()
    try:
        all_bets = db.query(YetAIBet).order_by(YetAIBet.created_at.desc()).all()
        print(f"Total yetai_bets rows: {len(all_bets)}")

        demo = [b for b in all_bets if is_demo_yetai_bet(b)]
        print(f"Demo/stub rows to reject: {len(demo)}")
        for bet in demo:
            print(
                f"  {'DRY reject' if args.dry_run else 'reject'} {bet.id[:8]} "
                f"status={bet.status} title={bet.title!r}"
            )
            if not args.dry_run:
                bet.status = "rejected"

        pitcher_rows = db.query(Pitcher).all()
        pitchers_by_name = {p.name.lower(): p for p in pitcher_rows}
        pitchers_by_id = {str(p.pitcher_id): p for p in pitcher_rows}
        repaired = 0
        for bet in all_bets:
            if (bet.sport or "").upper() != "MLB":
                continue
            if bet.bet_type != BetType.PROP:
                continue
            if bet.status not in VISIBLE and bet.status != "pending_approval":
                continue
            needs_repair = (
                not (bet.away_team and bet.home_team)
                or title_looks_like_prop_line(bet.title or "")
                or title_looks_like_prop_line(bet.selection or "")
            )
            if not needs_repair:
                continue
            meta = _pitcher_meta_for_bet(bet, pitchers_by_name, pitchers_by_id)
            if not meta:
                print(
                    f"  SKIP repair {bet.id[:8]} — no pred_pitcher "
                    f"for selection={bet.selection!r}"
                )
                continue
            new_title = f"{meta.team} vs {meta.opponent}"
            if (
                bet.title == new_title
                and bet.away_team == meta.team
                and bet.home_team == meta.opponent
            ):
                continue
            print(
                f"  {'DRY repair' if args.dry_run else 'repair'} {bet.id[:8]}: "
                f"{bet.title!r} -> {new_title!r}"
            )
            if not args.dry_run:
                bet.title = new_title
                bet.away_team = meta.team
                bet.home_team = meta.opponent
                if bet.reasoning and not bet.description:
                    bet.description = bet.reasoning
            repaired += 1

        if not args.dry_run and (demo or repaired):
            db.commit()

        print("\nSubscriber-visible after cleanup (would show on /predictions):")
        visible = [
            b for b in all_bets if b.status in VISIBLE and not is_demo_yetai_bet(b)
        ]
        for bet in visible[:20]:
            print(
                f"  {bet.id[:8]} {bet.sport} status={bet.status} "
                f"game={subscriber_game_label(bet)!r} pick={(bet.selection or '')[:50]!r}"
            )

        print(
            f"\nDone. demo_rejected={len(demo)} props_repaired={repaired} "
            f"visible_non_demo={len(visible)}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
