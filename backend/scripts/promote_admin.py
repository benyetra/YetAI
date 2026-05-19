#!/usr/bin/env python3
"""
Promote a YetAI user to admin by email.

Usage (from backend directory, with DATABASE_URL set):
    python scripts/promote_admin.py --email you@gmail.com

Options:
    --no-verify   Do not set is_verified (default: also mark email verified)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure backend app package is importable
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import func  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.models.database_models import User  # noqa: E402
from app.services.auth_service_db import auth_service_db  # noqa: E402


async def promote_admin(email: str, *, verify: bool = True) -> int:
    email = email.strip().lower()
    if not email:
        print("Error: --email is required", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        user = db.query(User).filter(func.lower(User.email) == email).first()
        if not user:
            print(f"Error: No user found with email {email!r}", file=sys.stderr)
            return 1

        update_data: dict = {"is_admin": True}
        if verify:
            update_data["is_verified"] = True

        updated = await auth_service_db.update_user(user.id, update_data)
        if not updated:
            print(f"Error: Failed to update user {user.id}", file=sys.stderr)
            return 1

        flags = ["is_admin=True"]
        if verify:
            flags.append("is_verified=True")
        print(
            f"OK: {email} (id={user.id}, username={user.username}) "
            f"→ {', '.join(flags)}"
        )
        return 0
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Promote a YetAI user to admin by email address."
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Email of the user to promote (e.g. you@gmail.com)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Do not set is_verified when promoting",
    )
    args = parser.parse_args()
    code = asyncio.run(promote_admin(args.email, verify=not args.no_verify))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
