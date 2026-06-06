"""Load backend env files and resolve DATABASE_URL for local script runs.

Production templates in ``.env.production`` often use placeholder host/port tokens.
``Settings`` reads only ``.env``, but scripts that bootstrap both files must not let
the template overwrite a valid URL from the shell or ``.env``.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

_PORT_PLACEHOLDER = re.compile(r":port(?:/|$|\?)")
_HOST_PORT_PLACEHOLDER = re.compile(r"@host:port")
_PLACEHOLDER_FRAGMENTS = (
    "your_",
    "changeme",
    "replace_me",
)


def is_placeholder_database_url(url: str | None) -> bool:
    if not url or not str(url).strip():
        return True
    text = str(url).strip()
    lower = text.lower()
    if _PORT_PLACEHOLDER.search(lower) or _HOST_PORT_PLACEHOLDER.search(lower):
        return True
    return any(fragment in lower for fragment in _PLACEHOLDER_FRAGMENTS)


def _database_url_from_file(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        from dotenv import dotenv_values
    except ImportError:
        return ""
    values = dotenv_values(path) or {}
    for key in ("DATABASE_URL", "POSTGRES_URL"):
        raw = (values.get(key) or "").strip()
        if raw:
            return raw
    return ""


def resolve_database_url(
    *,
    shell_database_url: str = "",
    shell_public_url: str = "",
    backend_root: Path | None = None,
) -> str | None:
    """Pick the best Postgres URL without letting template placeholders win."""
    root = backend_root or BACKEND_ROOT

    pre_shell = shell_database_url.strip()
    if pre_shell and not is_placeholder_database_url(pre_shell):
        return pre_shell

    pre_public = shell_public_url.strip()
    if pre_public and not is_placeholder_database_url(pre_public):
        return pre_public

    env_public = (os.environ.get("DATABASE_PUBLIC_URL") or "").strip()
    env_db = (os.environ.get("DATABASE_URL") or "").strip()

    if env_public and not is_placeholder_database_url(env_public):
        if (
            not env_db
            or is_placeholder_database_url(env_db)
            or "railway.internal" in env_db
        ):
            return env_public

    for name in (".env", ".env.production"):
        file_url = _database_url_from_file(root / name)
        if file_url and not is_placeholder_database_url(file_url):
            return file_url

    if (
        env_db
        and not is_placeholder_database_url(env_db)
        and "railway.internal" not in env_db
    ):
        return env_db

    return None


def bootstrap_env(*, backend_root: Path | None = None) -> None:
    """Load ``.env.production`` + ``.env`` and normalize ``DATABASE_URL``."""
    root = backend_root or BACKEND_ROOT
    shell_database_url = os.environ.get("DATABASE_URL", "").strip()
    shell_public_url = os.environ.get("DATABASE_PUBLIC_URL", "").strip()

    try:
        from dotenv import load_dotenv
    except ImportError:
        resolved = resolve_database_url(
            shell_database_url=shell_database_url,
            shell_public_url=shell_public_url,
            backend_root=root,
        )
        if resolved:
            os.environ["DATABASE_URL"] = resolved
        return

    for name in (".env.production", ".env"):
        path = root / name
        if path.is_file():
            load_dotenv(path)

    resolved = resolve_database_url(
        shell_database_url=shell_database_url,
        shell_public_url=shell_public_url,
        backend_root=root,
    )
    if resolved:
        os.environ["DATABASE_URL"] = resolved


def ensure_database_url(*, backend_root: Path | None = None) -> None:
    """Exit with a helpful message when no usable DATABASE_URL is available."""
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if url and not is_placeholder_database_url(url):
        return

    root = backend_root or BACKEND_ROOT
    print(
        "DATABASE_URL is missing or still a template placeholder "
        f"(checked shell env, {root / '.env'}, and {root / '.env.production'}).\n"
        "Fix options:\n"
        "  1) Railway dashboard → Postgres → Connect → copy public URL, then:\n"
        "       export DATABASE_URL='postgresql://...'\n"
        "  2) Or create backend/.env with DATABASE_URL=... (gitignored)\n"
        "  3) Or Railway CLI:\n"
        "       railway login && railway link\n"
        '       export DATABASE_URL="$(python3 scripts/resolve_railway_database_url.py)"\n'
        "Note: if resolve_railway_database_url.py fails, do not export its output — "
        "that clears any DATABASE_URL already in your shell.",
        file=sys.stderr,
    )
    raise SystemExit(2)
