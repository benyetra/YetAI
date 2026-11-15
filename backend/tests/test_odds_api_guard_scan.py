"""Source scan: every Odds API call goes through app/services/odds_api_sync.py.

That module guards the shared daily budget and records the credit cost, so a
module that calls the API itself would spend credits the counter never sees.
"""

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ALLOWED = {"app/services/odds_api_sync.py"}
RECORDERS = {"app/services/odds_api_budget.py", "app/services/odds_api_sync.py"}
# Files that use ODDS_API_BASE and also make HTTP calls of their own: each was
# read by hand (odds calls go through odds_api_sync; the other calls are ESPN,
# MLB Stats, or an aiohttp session handed to async_odds_get). A new file here
# must be reviewed the same way before it is added.
REVIEWED_MIXED = {
    "app/services/data_pipeline.py",
    "app/services/etl/mlb/strikeouts.py",
    "app/services/odds_api_service.py",
    "app/services/optimized_odds_api_service.py",
    "app/services/player_props_service.py",
}
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
            calls_http = any(c in src for c in HTTP_CALLS)
            if rel in ALLOWED or not calls_http:
                pass
            elif "the-odds-api.com" in src:
                direct.append(rel)
            elif "ODDS_API_BASE" in src and rel not in REVIEWED_MIXED:
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
