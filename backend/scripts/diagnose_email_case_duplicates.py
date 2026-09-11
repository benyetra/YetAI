#!/usr/bin/env python3
"""List users that share the same lower(email) — case-variant duplicates.

Pre-#118 Google OAuth used exact-case email lookup, so a password signup
``Ben@x`` and a later Google login ``ben@x`` could create two rows. Password
login then became flaky after case-insensitive ``.first()`` (#116).

Usage:
  cd backend && PYTHONPATH=. .venv/bin/python scripts/diagnose_email_case_duplicates.py
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.database import SessionLocal


def main() -> int:
    db = SessionLocal()
    try:
        rows = db.execute(
            text(
                """
                SELECT lower(email) AS email_key,
                       count(*) AS n,
                       array_agg(id ORDER BY id) AS ids,
                       array_agg(email ORDER BY id) AS emails,
                       array_agg(username ORDER BY id) AS usernames,
                       array_agg(COALESCE(password_set, true) ORDER BY id) AS password_set
                FROM users
                GROUP BY lower(email)
                HAVING count(*) > 1
                ORDER BY n DESC, email_key
                """
            )
        ).fetchall()
    except Exception as e:
        # password_set may not exist yet on older DBs
        print(f"query_failed: {e}")
        rows = db.execute(
            text(
                """
                SELECT lower(email) AS email_key,
                       count(*) AS n,
                       array_agg(id ORDER BY id) AS ids,
                       array_agg(email ORDER BY id) AS emails,
                       array_agg(username ORDER BY id) AS usernames
                FROM users
                GROUP BY lower(email)
                HAVING count(*) > 1
                ORDER BY n DESC, email_key
                """
            )
        ).fetchall()
    finally:
        db.close()

    if not rows:
        print("No case-variant duplicate emails found.")
        return 0

    print(f"Found {len(rows)} email key(s) with case-variant duplicates:\n")
    for r in rows:
        print(dict(r._mapping))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
