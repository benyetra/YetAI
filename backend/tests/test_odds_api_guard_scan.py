"""Source scan: every Odds API call goes through app/services/odds_api_sync.py.

That module guards the shared daily budget and records the credit cost, so a
module that calls the API itself would spend credits the counter never sees.
"""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ALLOWED = {"app/services/odds_api_sync.py"}
RECORDERS = {"app/services/odds_api_budget.py", "app/services/odds_api_sync.py"}
HTTP_CALLS = (
    "requests.get(",
    "requests.request(",
    "requests.Session(",
    "session.get(",
    "client.get(",
    "httpx.",
    "aiohttp.ClientSession(",
    "urlopen(",
)
RECORD_IMPORT = re.compile(r"\b(record_sync|record_async)\b")


def scan(root: Path) -> tuple[list[str], list[str]]:
    """(files calling the API directly, files importing the record functions)."""
    direct, recorders = [], []
    for sub in ("app", "scripts"):
        for path in sorted((root / sub).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            src = "\n".join(  # comment lines (doc URLs) do not count
                ln
                for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines()
                if not ln.lstrip().startswith("#")
            )
            if (
                "the-odds-api.com" in src
                and any(c in src for c in HTTP_CALLS)
                and rel not in ALLOWED
            ):
                direct.append(rel)
            if rel not in RECORDERS and RECORD_IMPORT.search(src):
                recorders.append(rel)
    return direct, recorders


def test_no_direct_odds_api_http_calls():
    direct, _ = scan(BACKEND)
    assert not direct, f"route through sync_odds_get/async_odds_get: {direct}"


def test_only_the_two_http_paths_record_credits():
    _, recorders = scan(BACKEND)
    assert not recorders, f"do not call record_sync/record_async directly: {recorders}"
