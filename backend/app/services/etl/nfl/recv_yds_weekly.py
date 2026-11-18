"""Weekly receiving-yards chain: Odds slate → features → soft-anchor upsert."""

from __future__ import annotations

from typing import Any, Callable


def attach_best_quotes(session, feature_rows, all_lines) -> int:
    """Set best_* (consensus price, None when none) on this run's lined rows.

    The projector writes the row; this prices its published yards against the stored
    ou_line. Rows whose game has kicked off stay frozen."""
    from app.models.predictions_models import RecvYdsPredictions as R
    from app.services.etl._consensus_attach import nfl_prop_fields
    from app.services.etl.nfl.nfl_common import has_kicked_off
    from app.services.etl.nfl.recv_yds_betting import match_player_lines

    n = 0
    for feat in feature_rows:
        if not match_player_lines(feat["player_name"], all_lines):
            continue
        row = (
            session.query(R)
            .filter_by(
                season=feat["season"], week=feat["week"], player_id=feat["player_id"]
            )
            .one_or_none()
        )
        if row is None or has_kicked_off(row.game_date):
            continue
        quote = nfl_prop_fields(
            session,
            row,
            market="player_reception_yds",
            projection=row.predicted_receiving_yards,
            line=row.ou_line,
            player=row.player_name,
        )
        for key, value in quote.items():
            setattr(row, key, value)
        n += 1
    return n


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
    stats["best_quotes"] = attach_best_quotes(session, feature_rows, all_lines)
    session.commit()
    return {"status": "ok", "task": "nfl_recv_yds_weekly", **stats}


def run() -> dict:
    from app.services.etl.nfl._db import close_session, db_session, init_session
    from app.services.etl.nfl.recv_yds_betting import fetch_reception_yds_lines
    from app.services.etl.nfl.recv_yds_usage import load_usage_priors_for_names

    init_session()
    try:
        # db_session is a _SessionProxy singleton, not a factory.
        return _run_core(
            db_session,
            fetch_lines=fetch_reception_yds_lines,
            load_priors=load_usage_priors_for_names,
        )
    finally:
        close_session()
