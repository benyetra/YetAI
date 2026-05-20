"""Run QB dynamic predictions then attach O/U betting lines (YetiBets chain)."""

from __future__ import annotations


def run() -> dict:
    from app.services.etl.nfl._db import close_session, init_session
    from app.services.etl.nfl.qb_betting import _run_qb_betting_core
    from app.services.etl.nfl.qb_dynamic import _run_qb_dynamic_core

    init_session()
    try:
        _run_qb_dynamic_core()
        _run_qb_betting_core()
        return {"status": "ok", "task": "nfl_qb_weekly"}
    finally:
        close_session()
