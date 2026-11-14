"""NBA totals baseline from final scores, plus its self-correction and call policy.

Pure functions (no DB) shared by ``totals_projector`` and the backtest script.

Each side's points come from scored/allowed per game. Once a team has a few
games this season only this season counts; until then last season stands in,
with this season's games blended in as they arrive. A backtest over 2025-26
showed a baseline built on last season drifting (about +8 points low in
October, ~-10 in the playoffs), so the projector adds a shrunk average of the
baseline's recent errors. Raw edge against the line had no predictive power
there (hit rate ~49% at every edge size), so calls need a bigger edge and their
confidence comes from measured results, not the edge.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List, NamedTuple, Optional, Sequence, Tuple

from app.services.etl.nba._season import regular_season_start, season_start_year

MIN_FORM_GAMES = 10


class Blend(NamedTuple):
    """How a team's scoring baseline mixes last season with this one."""

    # This season counts from this many days after opening night.
    delay_days: int
    # Last season weighs as this many games: this season's weight is n / (n + it).
    prior_games: int
    # Last season is dropped once the team has this many games this season.
    current_only_after: Optional[int]


CURRENT_SEASON = Blend(delay_days=0, prior_games=20, current_only_after=5)
# The policy until November 2026, kept for backtest comparisons.
LAST_SEASON_WEIGHTED = Blend(delay_days=14, prior_games=20, current_only_after=None)

# Self-correction: mean error of the baseline over the last BIAS_WINDOW games of
# the season, shrunk toward zero by BIAS_SHRINK.
BIAS_WINDOW = 30
BIAS_SHRINK = 10
# The published-error correction never moves a total by more than this.
BIAS_CLAMP = 8.0

# A call needs at least this much edge against the line.
MIN_EDGE = 4.0
# Needed to beat -110 vig.
BREAKEVEN = 0.5238
# Calibration starts when projections moved to the fixed baseline; earlier rows
# came from the old pace/ORtg model and would poison the record.
CALIBRATION_START = date(2026, 10, 22)
MIN_PICKS_FOR_RECORD = 30

# Stamped on every totals row. The call record counts only rows of this
# version, so a new formula is judged on its own calls (NBA-8).
MODEL_VERSION = "totals-anchor-v1"
# Published total = market + a + k * (model - market), fitted walk-forward
# (market_anchor.fit_anchor). Chosen on 2025-26 in
# scripts/nba_game_model_replay.py (MAE within 0.01 of the best variant, the
# smallest bias), then checked on 2026-27 to 2026-11-13: bias -0.63, MAE 13.82
# vs the line's 13.75 (n=183); k stayed below 0.05 (no information in the model).
ANCHOR_WINDOW = 150
ANCHOR_K_PRIOR = 200
ANCHOR_A_PRIOR = 100


class Final(NamedTuple):
    """A completed game (what pred_nba_spread_actuals rows reduce to)."""

    game_date: date
    home_team_name: str
    away_team_name: str
    home_score: int
    away_score: int


def scoring_averages(games, team_name: str) -> Tuple[float, float, int]:
    """(points scored, points allowed) per game and game count for a team.

    games: rows with home_team_name/away_team_name/home_score/away_score."""
    scored: List[float] = []
    allowed: List[float] = []
    for g in games:
        if g.home_team_name == team_name:
            scored.append(g.home_score)
            allowed.append(g.away_score)
        elif g.away_team_name == team_name:
            scored.append(g.away_score)
            allowed.append(g.home_score)
    n = len(scored)
    if not n:
        return 0.0, 0.0, 0
    return sum(scored) / n, sum(allowed) / n, n


def blended_scoring(
    prior_games, current_games, team_name: str, blend: Blend = CURRENT_SEASON
) -> Optional[Tuple[float, float]]:
    """This season's scoring once there's enough of it, else last season's
    shifted toward this one as its games pile up."""
    p_for, p_against, p_n = scoring_averages(prior_games, team_name)
    c_for, c_against, c_n = scoring_averages(current_games, team_name)
    if blend.current_only_after is not None and c_n >= blend.current_only_after:
        return c_for, c_against
    if p_n < MIN_FORM_GAMES:
        # No usable history: wait for this season.
        return (c_for, c_against) if c_n >= MIN_FORM_GAMES else None
    w = c_n / (c_n + blend.prior_games)
    return (1 - w) * p_for + w * c_for, (1 - w) * p_against + w * c_against


def windows(
    finals: Sequence, game_date: date, blend: Blend = CURRENT_SEASON
) -> Tuple[List, List]:
    """(last season's games, this season's games before game_date to use)."""
    year = season_start_year(game_date)
    opener = regular_season_start(year)
    prior = [g for g in finals if date(year - 1, 7, 1) <= g.game_date < opener]
    use_current = game_date >= opener + timedelta(days=blend.delay_days)
    current = (
        [g for g in finals if opener <= g.game_date < game_date] if use_current else []
    )
    return prior, current


def baseline_scores(
    finals: Sequence,
    home_team: str,
    away_team: str,
    game_date: date,
    blend: Blend = CURRENT_SEASON,
) -> Optional[Tuple[float, float]]:
    """(home, away) projected points for a game, or None without history."""
    prior, current = windows(finals, game_date, blend)
    home = blended_scoring(prior, current, home_team, blend)
    away = blended_scoring(prior, current, away_team, blend)
    if home is None or away is None:
        return None
    return (home[0] + away[1]) / 2, (away[0] + home[1]) / 2


def recent_bias(
    finals: Sequence,
    game_date: date,
    window: int = BIAS_WINDOW,
    shrink: int = BIAS_SHRINK,
    blend: Blend = CURRENT_SEASON,
) -> Tuple[float, int]:
    """(points to add, games used): shrunk mean of the baseline's recent errors.

    No longer added to the published total (see ``published_bias``): it fits the
    plain baseline, but the total also carries injury, rest, venue and form
    adjustments, so it corrected the wrong number. Kept for the backtest script
    and as the fallback when NBA_TOTALS_PUBLISHED_BIAS_ENABLED is off.

    Replays the baseline point-in-time for the last ``window`` games of the
    current season before ``game_date`` and averages actual - projected."""
    year = season_start_year(game_date)
    opener = regular_season_start(year)
    recent = sorted(
        (g for g in finals if opener <= g.game_date < game_date),
        key=lambda g: g.game_date,
    )[-window:]
    errors: List[float] = []
    for g in recent:
        scores = baseline_scores(
            finals, g.home_team_name, g.away_team_name, g.game_date, blend
        )
        if scores is not None:
            errors.append(g.home_score + g.away_score - sum(scores))
    if not errors:
        return 0.0, 0
    return sum(errors) / (len(errors) + shrink), len(errors)


def published_bias(
    history: Sequence,
    game_date: date,
    window: int = BIAS_WINDOW,
    shrink: int = BIAS_SHRINK,
    clamp: float = BIAS_CLAMP,
) -> Tuple[float, int]:
    """(points to add, games used): correction fit on the error as published.

    history: rows with game_date, actual_total, projected_total (as published)
    and applied_bias (the correction already inside that total; None/0 if
    unknown). Uses the last ``window`` games of this season, from calibration
    on, strictly before ``game_date``.

    Each published total already contains the correction applied that day, so a
    shrunk mean of (actual - published) alone would close only part of a
    persistent gap. Integrate instead: the correction in force plus the shrunk
    remaining error, which drives a steady bias to ~0. Clamped to ±``clamp``."""
    start = max(regular_season_start(season_start_year(game_date)), CALIBRATION_START)
    recent = sorted(
        (
            r
            for r in history
            if start <= r.game_date < game_date
            and r.actual_total is not None
            and r.projected_total is not None
        ),
        key=lambda r: r.game_date,
    )[-window:]
    if not recent:
        return 0.0, 0
    n = len(recent)
    applied = sum(r.applied_bias or 0.0 for r in recent) / n
    residual = sum(r.actual_total - r.projected_total for r in recent)
    return max(-clamp, min(applied + residual / (n + shrink), clamp)), n


def pick_record(rows: Iterable, min_edge: float = MIN_EDGE) -> Tuple[int, int]:
    """(hits, picks) the model would have had at |edge| >= min_edge.

    rows: graded games with projected_total, market_total and actual_total.
    Uses the sign of the edge, not the recommendation that was shown, so the
    record keeps updating while calls are withheld. Pushes are skipped."""
    hits = picks = 0
    for r in rows:
        if r.projected_total is None or not r.market_total or r.actual_total is None:
            continue
        edge = r.projected_total - r.market_total
        if abs(edge) < min_edge or r.actual_total == r.market_total:
            continue
        picks += 1
        hits += (edge > 0) == (r.actual_total > r.market_total)
    return hits, picks


def recommend(
    edge: Optional[float],
    record: Tuple[int, int],
    min_edge: float = MIN_EDGE,
    sides: Tuple[str, str] = ("OVER", "UNDER"),
) -> Tuple[str, float, str]:
    """(recommendation, confidence, note) for a game's edge vs the line.

    record: (hits, picks) of this model version's would-be calls. A call is
    shown only once that record has MIN_PICKS_FOR_RECORD graded picks and its
    rate, shrunk toward 50%, is at or above -110 breakeven; until then the row
    says NO_PLAY and why. Confidence is that shrunk rate, not a function of
    the edge. ``sides``: names for a positive and a negative edge."""
    hits, picks = record
    if edge is None or abs(edge) < min_edge:
        return "NO_PLAY", 0.5, "edge below threshold"
    side = sides[0] if edge > 0 else sides[1]
    if picks < MIN_PICKS_FOR_RECORD:
        return (
            "NO_PLAY",
            0.5,
            f"withheld: {picks} graded picks of this version,"
            f" {MIN_PICKS_FOR_RECORD} needed",
        )
    rate = (hits + 10) / (picks + 20)
    confidence = round(min(max(rate, 0.4), 0.65), 2)
    if rate < BREAKEVEN:
        return "NO_PLAY", confidence, f"withheld: record {hits}/{picks} below breakeven"
    return side, confidence, f"record {hits}/{picks}"
