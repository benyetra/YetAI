"""Feature flags for NFL anytime-TD predictions."""

from __future__ import annotations

import os


def anytime_td_ui_enabled() -> bool:
    """Return True when the anytime-TD UI group may be shown.

    Default on after the 2026-09-04 walk-forward gate (`passes_gate=true`).
    Set ``NFL_ANYTIME_TD_UI=0`` to hide.
    """
    return os.getenv("NFL_ANYTIME_TD_UI", "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
