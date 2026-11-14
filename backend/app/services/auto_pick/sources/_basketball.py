"""Shared row builders for the NBA / WNBA auto-pick sources (same table shapes)."""

import logging

from app.services.auto_pick.candidate import (
    DateRange,
    moved_line_edge,
    projection_ref,
    same_line,
    to_naive_utc,
)

log = logging.getLogger(__name__)


def _lines(db, lines_model, date_range: DateRange) -> list:
    return (
        db.query(lines_model)
        .filter(lines_model.game_date == date_range.slate_date)
        .all()
    )


def _base(gl, league: str, game_date, home: str, away: str) -> dict:
    return {
        "event_id": gl.odds_api_event_id
        or f"{league.lower()}-{game_date}-{home}-{away}",
        "league": league,
        "game_date": game_date,
        "home_team_name": home,
        "away_team_name": away,
        "commence_time": to_naive_utc(gl.game_time),
    }


def _reanchored(r, stored_line, live_line, sign: int):
    """Projection moved onto the live line, or None when the row isn't anchored.

    An anchored row's projection = line + k * (model - line) + a, so a line move
    shifts it by (1 - k) * move; ``sign`` is +1 for totals, -1 for spread (home
    spread is the negative of the margin line)."""
    f = r.factors if isinstance(r.factors, dict) else {}
    anchor = f.get("anchor")
    if not isinstance(anchor, dict) or anchor.get("k") is None:
        return None
    proj = r.projected_total if sign > 0 else r.projected_margin
    if proj is None or stored_line is None or live_line is None:
        return None
    return proj + sign * (1 - float(anchor["k"])) * (live_line - stored_line)


def _spread_threshold(league: str) -> float:
    from app.services.etl._spread_model import NBA_CONFIG, WNBA_CONFIG

    return (NBA_CONFIG if league == "NBA" else WNBA_CONFIG).edge_threshold


def _totals_threshold(league: str) -> float:
    if league == "NBA":
        from app.services.etl.nba.totals_baseline import MIN_EDGE

        return MIN_EDGE
    return 2.0  # mirrors the inline `abs(edge) > 2` in etl/wnba/totals_projector.py


def spread_rows(db, proj_model, lines_model, league, date_range) -> list[dict]:
    try:
        with db.begin_nested():  # keep a failed query from aborting the run
            rows = (
                db.query(proj_model)
                .filter(proj_model.game_date == date_range.slate_date)
                .all()
            )
            gls = {
                (g.home_team_name, g.away_team_name): g
                for g in _lines(db, lines_model, date_range)
            }
    except Exception:
        log.exception("%s spread source: query failed", league)
        return []
    out = []
    for r in rows:
        side = {"HOME": "home", "AWAY": "away"}.get((r.recommendation or "").upper())
        gl = gls.get((r.home_team_name, r.away_team_name))
        if side is None or gl is None:
            continue
        odds = gl.spread_home_odds if side == "home" else gl.spread_away_odds
        if odds is None:
            continue
        edge = r.edge
        margin = r.projected_margin
        if not same_line(gl.spread_home, r.market_spread_home):
            # line moved since the projection: re-derive the edge on the current line
            moved = _reanchored(r, r.market_spread_home, gl.spread_home, -1)
            margin = r.projected_margin if moved is None else moved
            edge = moved_line_edge(
                "spread",
                side,
                margin,
                gl.spread_home,
                _spread_threshold(league),
            )
            if edge is None:
                continue
        out.append(
            {
                **_base(gl, league, r.game_date, r.home_team_name, r.away_team_name),
                "projection_ref": projection_ref(
                    r,
                    game_date=r.game_date,
                    home_team_name=r.home_team_name,
                    away_team_name=r.away_team_name,
                ),
                "model_version": getattr(r, "model_version", None),
                "projected_margin": margin,
                "market_spread_home": gl.spread_home,
                "spread_odds": odds,
                "side": side,
                "confidence_score": r.confidence_score,
                "edge": edge,
                "recommendation": r.recommendation,
                "home_win_prob": r.home_win_prob,
                "factors": r.factors,
                "generated_at": r.created_at,
            }
        )
    return out


def totals_rows(db, proj_model, lines_model, league, date_range) -> list[dict]:
    try:
        with db.begin_nested():  # keep a failed query from aborting the run
            rows = (
                db.query(proj_model)
                .filter(proj_model.game_date == date_range.slate_date)
                .all()
            )
            gls = {
                (g.home_team_name, g.away_team_name): g
                for g in _lines(db, lines_model, date_range)
            }
    except Exception:
        log.exception("%s totals source: query failed", league)
        return []
    out = []
    for r in rows:
        side = {"OVER": "over", "UNDER": "under"}.get((r.recommendation or "").upper())
        gl = gls.get((r.home_team_name, r.away_team_name))
        if side is None or gl is None:
            continue
        odds = gl.over_odds if side == "over" else gl.under_odds
        if odds is None:
            continue
        edge = r.edge
        total = r.projected_total
        if not same_line(gl.total, r.market_total):
            # line moved since the projection: re-derive the edge on the current line
            moved = _reanchored(r, r.market_total, gl.total, 1)
            total = r.projected_total if moved is None else moved
            edge = moved_line_edge(
                "total",
                side,
                total,
                gl.total,
                _totals_threshold(league),
                strict=league != "NBA",  # WNBA projector plays on `edge > 2`
            )
            if edge is None:
                continue
        out.append(
            {
                **_base(gl, league, r.game_date, r.home_team_name, r.away_team_name),
                "projection_ref": projection_ref(
                    r,
                    game_date=r.game_date,
                    home_team_name=r.home_team_name,
                    away_team_name=r.away_team_name,
                ),
                "model_version": getattr(r, "model_version", None),
                "projected_total": total,
                "market_total": gl.total,
                "side": side,
                "line_odds": odds,
                "confidence_score": r.confidence_score,
                "edge": edge,
                "recommendation": r.recommendation,
                "injury_report": r.injury_report,
                "factors": r.factors,
                "generated_at": r.created_at,
            }
        )
    return out


def prop_rows(db, specs, lines_model, league, date_range, side_of) -> list[dict]:
    """``specs``: (model, stat, projection_attr, line_attr, generated_at_attr|None).

    ``side_of(row)`` returns "over"/"under" or None. Game, both teams, event id
    and start time come from the game-lines row whose home/away is the opponent.
    """
    try:
        with db.begin_nested():  # keep a failed query from aborting the run
            by_team = {}
            for g in _lines(db, lines_model, date_range):
                by_team[g.home_team_name] = (g, True)
                by_team[g.away_team_name] = (g, False)
    except Exception:
        log.exception("%s prop source: game lines query failed", league)
        return []
    out = []
    for model, stat, proj_attr, line_attr, gen_attr in specs:
        try:
            with db.begin_nested():  # keep a failed query from aborting the run
                rows = db.query(model).filter(model.date == date_range.slate_date).all()
        except Exception:
            log.exception("%s prop source: query failed for %s", league, stat)
            continue
        for r in rows:
            proj, line = getattr(r, proj_attr, None), getattr(r, line_attr, None)
            side = side_of(r)
            hit = by_team.get(getattr(r, "opponent_team_name", None))
            price = getattr(r, "fanduel_price", None)
            book = "fanduel" if price is not None else None
            # NBA rows carry the best quote across books; it is the line we publish.
            best = [getattr(r, f"best_{k}", None) for k in ("book", "line", "price")]
            if None not in best:
                book, line, price = best
            if (
                proj is None
                or line is None
                or side is None
                or hit is None
                or price is None  # rows written before the price column existed
            ):
                continue
            gl, opp_is_home = hit
            team = gl.away_team_name if opp_is_home else gl.home_team_name
            out.append(
                {
                    **_base(gl, league, r.date, gl.home_team_name, gl.away_team_name),
                    "projection_ref": projection_ref(
                        r, date=r.date, player_id=r.player_id, stat=stat
                    ),
                    "model_version": getattr(r, "model_version", None),
                    "player": r.player_name or f"player_{r.player_id}",
                    "stat": stat,
                    "line": float(line),
                    "odds": int(price),
                    "odds_assumed": False,
                    "book": book,
                    "projection": float(proj),
                    "side": side,
                    "team": team,
                    "opponent": r.opponent_team_name,
                    "opponent_team_name": r.opponent_team_name,
                    "sample_size": None,
                    "generated_at": getattr(r, gen_attr) if gen_attr else None,
                    "model_confidence": (
                        conf / 100.0
                        if (conf := getattr(r, "confidence_score", None)) is not None
                        else None
                    ),
                    "injury_flag": False,
                }
            )
    return out
