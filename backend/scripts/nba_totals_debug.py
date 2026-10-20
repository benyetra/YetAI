"""Read-only: print the team stats that drive NBA totals projections."""

from __future__ import annotations

from app.core.database import SessionLocal
from app.models.predictions_models import TeamDefenseStats, TeamOffenseStats
from app.services.etl.nba import totals_projector as tp

TEAMS = [
    "Boston Celtics",
    "Detroit Pistons",
    "Philadelphia 76ers",
    "New York Knicks",
    "Oklahoma City Thunder",
    "San Antonio Spurs",
]


def main() -> None:
    tp.db = SessionLocal()
    try:
        for t in TEAMS:
            tid = tp.get_team_id_from_name(t)
            off = tp.db.query(TeamOffenseStats).filter_by(team_id=tid).first()
            dfn = tp.db.query(TeamDefenseStats).filter_by(team_id=tid).first()
            print(t, tid)
            if off:
                print(
                    f"  off: games={off.games_played} ppg={off.points_per_game} "
                    f"pace={off.pace} updated={getattr(off, 'last_updated', None)}"
                )
            else:
                print("  off: none")
            if dfn:
                print(
                    f"  def: pts_allowed(tracked)={dfn.points_allowed_per_game} "
                    f"drtg={dfn.defensive_rating} pace={dfn.pace} "
                    f"updated={dfn.last_updated}"
                )
            else:
                print("  def: none")
            print("  derived:", tp.get_team_pace_and_efficiency(t))
    finally:
        tp.db.close()


if __name__ == "__main__":
    main()
