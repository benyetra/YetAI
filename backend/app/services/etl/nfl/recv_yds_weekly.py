"""Weekly receiving-yards chain: Odds slate → features → soft-anchor upsert."""

from __future__ import annotations

from typing import Any, Callable


def _run_core(
    session,
    *,
    fetch_lines: Callable[[], dict[str, dict]],
    load_priors: Callable[[list[str]], list[dict[str, Any]]],
) -> dict[str, Any]:
    from app.services.etl.nfl.recv_yds_features import build_recv_feature_row
    from app.services.etl.nfl.recv_yds_projector import project_lined_players

    all_lines = fetch_lines()
    if not all_lines:
        return {
            "status": "ok",
            "task": "nfl_recv_yds_weekly",
            "upserted": 0,
            "note": "no_reception_yds_lines",
        }
    prior_rows = load_priors(list(all_lines.keys()))
    feature_rows = []
    for prior in prior_rows:
        feat = build_recv_feature_row(
            prior,
            game_env=prior.get("game_env"),
            opponent_defense=prior.get("opponent_defense"),
        )
        if feat is not None:
            feature_rows.append(feat)
    stats = project_lined_players(session, feature_rows, all_lines)
    session.commit()
    return {"status": "ok", "task": "nfl_recv_yds_weekly", **stats}


def run() -> dict:
    from app.services.etl.nfl._db import close_session, db_session, init_session
    from app.services.etl.nfl.recv_yds_betting import fetch_reception_yds_lines
    from app.services.etl.nfl.recv_yds_usage import load_usage_priors_for_names

    init_session()
    try:
        return _run_core(
            db_session(),
            fetch_lines=fetch_reception_yds_lines,
            load_priors=load_usage_priors_for_names,
        )
    finally:
        close_session()
