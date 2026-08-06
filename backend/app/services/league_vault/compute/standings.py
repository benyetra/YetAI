"""All-play records and luck differential."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.models.league_vault_models import LvMatchup, LvSeason, LvTeam


def compute_all_play_for_lineage(db: Session, lineage_id: int) -> dict[str, Any]:
    """For each season, compute all-play W/L and luck differential per team.

    All-play: each week, every team's score is compared to every other team's
    score that week (not just their scheduled opponent). Luck differential =
    actual wins − expected wins, where expected wins = all_play_win_pct × games.
    """
    seasons = db.query(LvSeason).filter_by(lineage_id=lineage_id).all()
    updated = 0
    for season in seasons:
        teams = db.query(LvTeam).filter_by(season_id=season.id).all()
        if len(teams) < 2:
            continue
        team_by_id = {t.id: t for t in teams}

        # week -> list of (team_id, score) for teams that played
        week_scores: dict[int, list[tuple[int, float]]] = defaultdict(list)
        matchups = db.query(LvMatchup).filter_by(season_id=season.id).all()
        for m in matchups:
            if m.team_a_id and m.score_a is not None:
                week_scores[m.week].append((m.team_a_id, float(m.score_a)))
            if m.team_b_id and m.score_b is not None:
                week_scores[m.week].append((m.team_b_id, float(m.score_b)))

        ap_wins: dict[int, int] = defaultdict(int)
        ap_losses: dict[int, int] = defaultdict(int)
        for _week, scores in week_scores.items():
            # dedupe if a team appears twice somehow
            seen: dict[int, float] = {}
            for tid, sc in scores:
                seen[tid] = sc
            entries = list(seen.items())
            for i, (tid_a, sc_a) in enumerate(entries):
                for tid_b, sc_b in entries[i + 1 :]:
                    if sc_a > sc_b:
                        ap_wins[tid_a] += 1
                        ap_losses[tid_b] += 1
                    elif sc_b > sc_a:
                        ap_wins[tid_b] += 1
                        ap_losses[tid_a] += 1
                    # ties: no win either side for all-play (conservative)

        for tid, team in team_by_id.items():
            w = ap_wins.get(tid, 0)
            l = ap_losses.get(tid, 0)
            team.all_play_wins = w
            team.all_play_losses = l
            games = (team.wins or 0) + (team.losses or 0) + (team.ties or 0)
            ap_games = w + l
            if ap_games > 0 and games > 0:
                expected = (w / ap_games) * games
                team.luck_differential = round((team.wins or 0) - expected, 3)
            else:
                team.luck_differential = 0.0
            updated += 1

    db.commit()
    return {"seasons": len(seasons), "teams_updated": updated}
