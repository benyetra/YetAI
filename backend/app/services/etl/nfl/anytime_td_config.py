"""Feature flags for NFL anytime-TD predictions."""

from __future__ import annotations

import os


def anytime_td_ui_enabled() -> bool:
    """Return True when the anytime-TD UI group may be shown (default off)."""
    return os.getenv("NFL_ANYTIME_TD_UI", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
