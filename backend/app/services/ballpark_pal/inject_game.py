from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from app.services.ballpark_pal import store
from app.services.ballpark_pal.config import (
    ballpark_pal_enabled,
    bpp_game_prior_weight,
)
from app.services.ballpark_pal.priors import (
    apply_park_factor_to_runs,
    blend_team_run_rates,
)
from app.services.etl.mlb.monte_carlo import TeamRunRates

logger = logging.getLogger(__name__)


def _slate_date(as_of: Any) -> date | None:
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    if isinstance(as_of, str):
        try:
            return date.fromisoformat(as_of[:10])
        except ValueError:
            return None
    return None


def _runs_average(row: Any) -> float | None:
    try:
        value = (row.averages_json or {}).get("runs")
        return float(value) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _runs_percent(row: Any) -> int | None:
    try:
        value = (row.factors_json or {}).get("runsPercent")
        return int(value) if value is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def maybe_apply_bpp_run_priors(
    features: dict,
    rates: TeamRunRates,
    as_of,
    *,
    game_id: int | None,
    session=None,
) -> tuple[TeamRunRates, dict | None]:
    """Blend full-game BPP team run priors into Monte Carlo rates."""
    del features
    slate_date = _slate_date(as_of)
    if not ballpark_pal_enabled() or game_id is None or slate_date is None:
        return rates, None

    owns_session = session is None
    try:
        if owns_session:
            from app.services.etl.mlb import _db

            session = _db.init_session()

        game = store.load_game_snapshot(session, int(game_id), slate_date)
        if game is None:
            return rates, None

        home_row = store.load_player_proj(
            session,
            game.team_home_id,
            slate_date,
            "team",
            game_pk=int(game_id),
            bpp_game_id=game.bpp_game_id,
        )
        away_row = store.load_player_proj(
            session,
            game.team_away_id,
            slate_date,
            "team",
            game_pk=int(game_id),
            bpp_game_id=game.bpp_game_id,
        )
        home_prior = _runs_average(home_row)
        away_prior = _runs_average(away_row)
        weight = bpp_game_prior_weight()
        home_mu, away_mu, applied = blend_team_run_rates(
            rates.home_mu,
            rates.away_mu,
            home_prior,
            away_prior,
            weight,
        )
        if not applied:
            return rates, None

        park_row = store.load_game_park_factor(session, int(game_id), slate_date)
        home_mu, away_mu = apply_park_factor_to_runs(
            home_mu,
            away_mu,
            _runs_percent(park_row),
        )
        adjusted = TeamRunRates(
            home_mu=round(home_mu, 3),
            away_mu=round(away_mu, 3),
        )
        return adjusted, {
            "applied": True,
            "weight": weight,
            "home_runs_prior": home_prior,
            "away_runs_prior": away_prior,
        }
    except Exception as exc:
        logger.warning("Ballpark Pal game prior injection skipped: %s", exc)
        return rates, None
    finally:
        if owns_session:
            try:
                _db.close_session()
            except Exception:
                pass
