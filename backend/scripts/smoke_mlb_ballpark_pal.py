#!/usr/bin/env python3
"""Smoke test Ballpark Pal integration without DB or network (default).

Usage (from backend/):

    PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_ballpark_pal.py
    PYTHONPATH=. .venv/bin/python scripts/smoke_mlb_ballpark_pal.py --live

Default: fixture parse + prior math + client envelope parsing (mocked session).
``--live``: today's games count when enabled and API key is set (never prints key).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

FIX = BACKEND_ROOT / "tests" / "fixtures" / "ballpark_pal"


def _load_fixture(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def check_prior_math() -> None:
    from app.services.ballpark_pal.priors import (
        apply_park_factor_to_runs,
        blend,
        blend_prop_mean,
        blend_team_run_rates,
        shrink_with_matchup_rate,
    )
    from app.services.etl.mlb.hits import (
        BPP_HITS_BASELINE,
        BPP_HR_BASELINE,
        _relative_bpp_multiplier,
    )

    assert blend(4.0, 8.0, 0.5) == 6.0
    home, away, applied = blend_team_run_rates(4.0, 3.0, 5.0, 4.0, 0.5)
    assert applied is True
    assert home == 4.5 and away == 3.5
    home, away = apply_park_factor_to_runs(4.0, 3.0, 18)
    assert home == 4.72 and away == 3.54
    mean, applied = blend_prop_mean(6.0, 8.0, 0.25)
    assert applied is True
    assert mean == 6.5
    mean, applied = shrink_with_matchup_rate(0.25, 4.2, weight=0.5, typical_pa=4.0)
    assert applied is True
    assert abs(mean - 0.209) < 1e-6
    assert _relative_bpp_multiplier(BPP_HITS_BASELINE, BPP_HITS_BASELINE, 0.25) == 1.0
    assert _relative_bpp_multiplier(1.2, BPP_HITS_BASELINE, 0.25) > 1.0
    assert _relative_bpp_multiplier(0.05, BPP_HR_BASELINE, 0.25) >= 0.5
    assert _relative_bpp_multiplier(0.50, BPP_HR_BASELINE, 1.0) <= 1.5
    print("prior math OK")


def check_client_parse() -> None:
    from app.services.ballpark_pal.client import BallparkPalClient

    payload = {
        "meta": {"asOf": "2026-08-05T12:00:00Z", "requestId": "r1"},
        "data": {"items": [{"gameId": 776345, "teamAwayId": 108, "teamHomeId": 136}]},
    }
    client = BallparkPalClient(api_key="smoke-test-key", session=MagicMock())
    resp = MagicMock(status_code=200)
    resp.json.return_value = payload
    resp.headers = {}
    client._session.get.return_value = resp
    out = client.games("2026-08-05")
    assert out is not None
    assert out["items"][0]["gameId"] == 776345

    err_client = BallparkPalClient(api_key="bad", session=MagicMock())
    err_resp = MagicMock(status_code=401)
    err_resp.json.return_value = _load_fixture("error_unauthorized.json")
    err_resp.headers = {}
    err_client._session.get.return_value = err_resp
    assert err_client.games("2026-08-05") is None
    print("client parse OK")


def check_config_gate() -> None:
    import os

    prev_enabled = os.environ.get("BALLPARK_PAL_ENABLED")
    prev_key = os.environ.get("BALLPARK_PAL_API_KEY")
    try:
        os.environ["BALLPARK_PAL_ENABLED"] = "1"
        os.environ.pop("BALLPARK_PAL_API_KEY", None)
        from app.services.ballpark_pal.config import (
            ballpark_pal_enabled,
            get_ballpark_pal_api_key,
        )

        assert get_ballpark_pal_api_key() is None
        assert ballpark_pal_enabled() is False
    finally:
        if prev_enabled is None:
            os.environ.pop("BALLPARK_PAL_ENABLED", None)
        else:
            os.environ["BALLPARK_PAL_ENABLED"] = prev_enabled
        if prev_key is None:
            os.environ.pop("BALLPARK_PAL_API_KEY", None)
        else:
            os.environ["BALLPARK_PAL_API_KEY"] = prev_key
    print("config gate OK")


def run_live() -> int:
    from app.services.ballpark_pal.client import BallparkPalClient
    from app.services.ballpark_pal.config import ballpark_pal_enabled

    if not ballpark_pal_enabled():
        print("SKIP live: BALLPARK_PAL_ENABLED=0 or no API key set")
        return 0

    client = BallparkPalClient()
    iso_date = date.today().isoformat()
    payload = client.games(iso_date)
    if payload is None:
        print("FAIL: games fetch returned None (check key/quota/network)")
        return 1

    items = payload if isinstance(payload, list) else payload.get("items", [])
    if isinstance(items, dict):
        items = items.get("items", [])
    count = len(items) if isinstance(items, list) else 0
    print(f"live games date={iso_date} count={count}")
    print("OK live")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Fetch today's games when enabled (network + key required)",
    )
    args = parser.parse_args()

    check_prior_math()
    check_client_parse()
    check_config_gate()
    print("OK offline smoke")

    if args.live:
        return run_live()
    print("Tip: --live for connectivity check when BALLPARK_PAL_ENABLED=1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
