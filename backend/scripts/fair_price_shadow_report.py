"""Fair-price shadow report (read-only). DATABASE_URL from the environment, never printed.

  fair_price_shadow_report.py --from 2026-11-14 --to 2026-11-15 [--today YYYY-MM-DD] [--json]
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.fair_price import report  # noqa: E402


def _session():
    from app.core.database import SessionLocal

    return SessionLocal()


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="start", type=date.fromisoformat)
    p.add_argument("--to", dest="end", type=date.fromisoformat)
    p.add_argument("--today", type=date.fromisoformat, default=date.today())
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    db = _session()
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY"))
        sec = report.section(db, a.today, a.start, a.end)
    finally:
        db.rollback()
        db.close()
    print(json.dumps(sec, indent=1) if a.json else "\n".join(report.render(sec)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
