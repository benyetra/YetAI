"""Guard maintenance scripts from accidentally hitting the local default DB."""

from __future__ import annotations

import os
import sys


def assert_not_local_default_db() -> None:
    from app.core.config import settings

    url = (settings.DATABASE_URL or "").lower()
    if os.environ.get("ALLOW_LOCAL_DB") == "1":
        return
    if "localhost" in url or "127.0.0.1" in url or "sports_betting_ai" in url:
        print(
            "Refusing to run: DATABASE_URL looks like the local dev default.\n"
            "  export DATABASE_URL='<production postgres url>'\n"
            "  or set ALLOW_LOCAL_DB=1 to override intentionally.",
            file=sys.stderr,
        )
        raise SystemExit(2)
