"""NBA totals baseline from final scores, plus its self-correction and call policy.

Pure functions (no DB) shared by ``totals_projector`` and the backtest script.

Each side's points come from scored/allowed per game: last season carries the
weight, this season is ignored for its first two weeks and then blended in. A
backtest over 2025-26 showed that baseline is unbiased over a season but drifts
(about +8 points low in October, ~-10 in the playoffs), so the projector adds a
shrunk average of the baseline's recent errors. Raw edge against the line had no
predictive power there (hit rate ~49% at every edge size), so calls need a
bigger edge and their confidence comes from measured results, not the edge.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, List, NamedTuple, Optional, Sequence, Tuple

from app.services.etl.nba._season import regular_season_start, season_start_year

MIN_FORM_GAMES = 10
CURRENT_SEASON_DELAY_DAYS = 14
CURRENT_SEASON_PRIOR_GAMES = 20  # current-season weight = n / (n + this)

# Self-correction: mean error of the baseline over the last BIAS_WINDOW games of
# the season, shrunk toward zero by BIAS_SHRINK.
BIAS_WINDOW = 30
BIAS_SHRINK = 10

# A call needs at least this much edge against the line.
MIN_EDGE = 4.0
# Needed to beat -110 vig.
BREAKEVEN = 0.5238
# Calibration starts when projections moved to the fixed baseline; earlier rows
# came from the old pace/ORtg model and would poison the record.
CALIBRATION_START = date(2026, 10, 22)
MIN_PICKS_FOR_RECORD = 30


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
    prior_games, current_games, team_name: str
) -> Optional[Tuple[float, float]]:
    """Last season's scoring, shifted toward this season as its games pile up."""
    p_for, p_against, p_n = scoring_averages(prior_games, team_name)
    c_for, c_against, c_n = scoring_averages(current_games, team_name)
    if p_n < MIN_FORM_GAMES:
        # No usable history: wait for this season.
        return (c_for, c_against) if c_n >= MIN_FORM_GAMES else None
    w = c_n / (c_n + CURRENT_SEASON_PRIOR_GAMES)
    return (1 - w) * p_for + w * c_for, (1 - w) * p_against + w * c_against


def windows(finals: Sequence, game_date: date) -> Tuple[List, List]:
    """(last season's games, this season's games before game_date to use)."""
    year = season_start_year(game_date)
    opener = regular_season_start(year)
    prior = [g for g in finals if date(year - 1, 7, 1) <= g.game_date < opener]
    use_current = game_date >= opener + timedelta(days=CURRENT_SEASON_DELAY_DAYS)
    current = (
        [g for g in finals if opener <= g.game_date < game_date] if use_current else []
    )
    return prior, current


def baseline_scores(
    finals: Sequence, home_team: str, away_team: str, game_date: date
) -> Optional[Tuple[float, float]]:
    """(home, away) projected points for a game, or None without history."""
    prior, current = windows(finals, game_date)
    home = blended_scoring(prior, current, home_team)
    away = blended_scoring(prior, current, away_team)
    if home is None or away is None:
        return None
    return (home[0] + away[1]) / 2, (away[0] + home[1]) / 2


def recent_bias(
    finals: Sequence,
    game_date: date,
    window: int = BIAS_WINDOW,
    shrink: int = BIAS_SHRINK,
) -> Tuple[float, int]:
    """(points to add, games used): shrunk mean of the baseline's recent errors.

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
            finals, g.home_team_name, g.away_team_name, g.game_date
        )
        if scores is not None:
            errors.append(g.home_score + g.away_score - sum(scores))
    if not errors:
        return 0.0, 0
    return sum(errors) / (len(errors) + shrink), len(errors)


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


def recommend(edge: Optional[float], record: Tuple[int, int]) -> Tuple[str, float, str]:
    """(recommendation, confidence, note) for a game's edge vs the line.

    Confidence is the measured hit rate (shrunk toward 50%), not a function of
    the edge. Once the record is long enough, a model that isn't beating -110
    stops making calls until it does."""
    hits, picks = record
    if edge is None or abs(edge) < MIN_EDGE:
        return "NO_PLAY", 0.5, "edge below threshold"
    side = "OVER" if edge > 0 else "UNDER"
    if picks < MIN_PICKS_FOR_RECORD:
        return side, 0.5, f"unproven: {picks} graded picks so far"
    rate = (hits + 10) / (picks + 20)
    confidence = round(min(max(rate, 0.4), 0.65), 2)
    if rate < BREAKEVEN:
        return "NO_PLAY", confidence, f"recent record {hits}/{picks} below breakeven"
    return side, confidence, f"recent record {hits}/{picks}"
