"""
MLB strikeout projection source for auto-pick.

Uses YetAI pick (projected K vs FanDuel line) with a minimum K-edge gate so
auto picks align with what users see on the MLB stats table.
"""

import logging
from sqlalchemy.orm import Session

from app.models.predictions_models import (
    GameProjections,
    Pitcher,
    StrikeoutProjections,
)
from app.services.auto_pick.candidate import DateRange, to_naive_utc
from app.services.mlb_strikeout_pick import (
    pick_confidence_pct,
    projection_pick_side,
    qualifies_for_auto_pick,
)

log = logging.getLogger(__name__)


class MLBStrikeoutSource:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def get_todays_projections(self, date_range: DateRange) -> list[dict]:
        day = date_range.slate_date

        try:
            rows = (
                self.db.query(StrikeoutProjections)
                .filter(
                    StrikeoutProjections.date == day,
                )
                .all()
            )
            # pred_pitcher has no date column; keep only today's starts (naive UTC).
            pitcher_meta = {
                p.pitcher_id: p
                for p in self.db.query(Pitcher)
                .filter(
                    Pitcher.game_time >= date_range.start,
                    Pitcher.game_time < date_range.end,
                )
                .all()
            }
            games = {
                g.game_id: g
                for g in self.db.query(GameProjections)
                .filter(GameProjections.date == day)
                .all()
            }
        except Exception:
            log.exception("MLBStrikeoutSource: DB query failed")
            return []

        if not rows:
            return []

        out: list[dict] = []
        for r in rows:
            if r.projected_strikeouts is None:
                continue

            line_val = r.fanduel_line
            if line_val is None or line_val <= 0:
                log.debug(
                    "MLBStrikeoutSource: skipping %s (%s) — no fanduel_line",
                    r.pitcher_name,
                    r.date,
                )
                continue

            side = (
                (r.fanduel_over_under or "").strip().lower()
                if r.fanduel_over_under
                else projection_pick_side(r.projected_strikeouts, line_val)
            )
            if side not in ("over", "under"):
                side = projection_pick_side(r.projected_strikeouts, line_val)
            if side not in ("over", "under"):
                continue
            if not qualifies_for_auto_pick(r.projected_strikeouts, line_val, side):
                log.debug(
                    "MLBStrikeoutSource: skipping %s — insufficient K edge",
                    r.pitcher_name,
                )
                continue

            meta = pitcher_meta.get(str(r.pitcher_id))
            if meta is None or not meta.team or not meta.opponent:
                continue  # no start time / teams for today -> cannot grade
            prob_over = getattr(meta, "prob_over", None) if meta else None
            pick_edge_pct = getattr(meta, "pick_edge_pct", None) if meta else None
            confidence = getattr(r, "pick_confidence", None) or pick_confidence_pct(
                float(r.projected_strikeouts),
                float(line_val),
                prob_over=prob_over,
                ev_edge_pct=pick_edge_pct,
            )
            # fanduel_price is the price of the EV side (flag o/u), or the over
            # price when there is no EV play; trust it only for the picked side.
            odds, assumed = -110, True
            flag = (getattr(meta, "fanduel_flag", None) or "").lower()
            if flag == side[0] and meta.fanduel_price:
                odds, assumed = int(meta.fanduel_price), False

            player_name = r.pitcher_name or f"pitcher_{r.pitcher_id}"
            event_id = f"mlb-prop-{r.date}-{r.pitcher_id}-strikeouts"

            game = games.get(meta.game_id)
            if game is not None:
                home, away = game.home_team, game.away_team
            else:  # settlement tolerates swapped order
                home, away = meta.opponent, meta.team
            out.append(
                {
                    "event_id": event_id,
                    "league": "MLB",
                    "game_date": day,
                    "player": player_name,
                    "stat": "strikeouts",
                    "line": float(line_val),
                    "odds": odds,
                    "odds_assumed": assumed,
                    "projection": float(r.projected_strikeouts),
                    "side": side,
                    "sample_size": None,
                    # StrikeoutProjections has no timestamp column.
                    "generated_at": None,
                    "model_confidence": confidence / 100.0,
                    "injury_flag": False,
                    "team": meta.team,
                    "opponent": meta.opponent,
                    "away_team_name": away,
                    "home_team_name": home,
                    "commence_time": to_naive_utc(meta.game_time),
                }
            )

        return out
