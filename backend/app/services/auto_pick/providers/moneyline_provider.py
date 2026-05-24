"""
Adapter from moneyline/win-probability sources to BetCandidate.

Audit findings:
- Source entry point: source.get_todays_projections(date_range) -> list[dict]
- No dedicated moneyline prediction table exists. Win probability is stored in
  pred_nba_spread_projections.home_win_prob (NBASpreadProjections model).
  Raw moneyline odds are stored in pred_nba_game_lines.moneyline_home/away.
- Task 14 orchestrator wires a shim that joins pred_nba_spread_projections with
  pred_nba_game_lines on (game_date, home_team_name, away_team_name) and surfaces:
  event_id, home_team_name, away_team_name, home_win_prob, moneyline_home,
  moneyline_away, confidence_score, generated_at.
- market_line is 0 for moneyline (no point-spread line).
- our_projection is the implied win probability (0.0–1.0) for the chosen side.
- If source raises or returns nothing, provider returns [].
"""

import logging

from app.services.auto_pick.candidate import BetCandidate, DateRange, MarketType

log = logging.getLogger(__name__)


class MoneylineCandidateProvider:
    def __init__(self, source):
        self.source = source

    async def get_candidates(self, date_range: DateRange) -> list[BetCandidate]:
        try:
            rows = await self.source.get_todays_projections(date_range)
        except Exception as e:
            log.exception("MoneylineCandidateProvider source failed: %s", e)
            return []

        out: list[BetCandidate] = []
        for r in rows:
            try:
                side = r.get("side", "home")
                if side == "home":
                    team = r["home_team_name"]
                    odds = int(r["moneyline_home"])
                    win_prob = float(r["home_win_prob"])
                else:
                    team = r["away_team_name"]
                    odds = int(r["moneyline_away"])
                    win_prob = 1.0 - float(r["home_win_prob"])
                selection = f"{team} ML"
                out.append(
                    BetCandidate(
                        market_type=MarketType.MONEYLINE,
                        league=r["league"],
                        event_id=r["event_id"],
                        selection=selection,
                        market_line=0.0,
                        market_odds=odds,
                        our_projection=win_prob,
                        away_team=r.get("away_team_name"),
                        home_team=r.get("home_team_name"),
                        commence_time=r.get("game_time"),
                        projection_metadata={
                            "confidence_score": r.get("confidence_score"),
                            "home_win_prob": r.get("home_win_prob"),
                            "generated_at": r.get("generated_at"),
                            "side": side,
                        },
                    )
                )
            except Exception as e:
                log.warning("Skipping malformed moneyline row: %s", e)
        return out
