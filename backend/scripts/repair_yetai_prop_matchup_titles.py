#!/usr/bin/env python3
"""
Fix YetAI bets whose title was stored as the prop line instead of a matchup.

Joins MLB auto/prop picks to pred_pitcher on pitcher name and sets:
  title, home_team, away_team, description (from reasoning if missing)

Usage:
  export DATABASE_URL='postgresql://...'
  cd backend && PYTHONPATH=. .venv/bin/python scripts/repair_yetai_prop_matchup_titles.py --dry-run
  cd backend && PYTHONPATH=. .venv/bin/python scripts/repair_yetai_prop_matchup_titles.py
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
            "Missing dependencies. Run with the backend venv:\n"
            "  cd backend && PYTHONPATH=. .venv/bin/python scripts/repair_yetai_prop_matchup_titles.py",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    raise
from app.models.database_models import BetType, YetAIBet
from app.models.predictions_models import Pitcher


PROP_TITLE_RE = re.compile(r"\b(under|over)\b", re.I)


def _pitcher_name_from_selection(selection: str) -> str | None:
    m = re.match(
        r"^(.+?)\s+(UNDER|OVER)\s+[\d.]+\s+\w+",
        selection.strip(),
        re.I,
    )
    return m.group(1).strip() if m else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        pitchers = {p.name.lower(): p for p in db.query(Pitcher).all()}
        bets = (
            db.query(YetAIBet)
            .filter(
                YetAIBet.sport == "MLB",
                YetAIBet.bet_type == BetType.PROP,
            )
            .all()
        )
        updated = 0
        for bet in bets:
            if not bet.title or not PROP_TITLE_RE.search(bet.title):
                continue
            name = _pitcher_name_from_selection(bet.selection or bet.title)
            if not name:
                continue
            meta = pitchers.get(name.lower())
            if not meta:
                print(f"SKIP {bet.id[:8]} — no pred_pitcher for {name!r}")
                continue
            new_title = f"{meta.team} vs {meta.opponent}"
            if (
                bet.title == new_title
                and bet.away_team == meta.team
                and bet.home_team == meta.opponent
            ):
                continue
            print(
                f"{'DRY' if args.dry_run else 'FIX'} {bet.id[:8]}: "
                f"{bet.title!r} -> {new_title!r}"
            )
            if not args.dry_run:
                bet.title = new_title
                bet.away_team = meta.team
                bet.home_team = meta.opponent
                if bet.reasoning and not bet.description:
                    bet.description = bet.reasoning
            updated += 1
        if not args.dry_run and updated:
            db.commit()
        print(
            f"Done. {'Would update' if args.dry_run else 'Updated'} {updated} bet(s)."
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
