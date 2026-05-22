"""
Adapter from spread projection sources to BetCandidate.

Audit findings:
- Source entry point: source.get_todays_projections(date_range) -> list[dict]
- DB table: pred_nba_spread_projections (NBASpreadProjections model).
  Columns used: game_date, home_team_name, away_team_name, projected_margin,
  market_spread_home, edge, recommendation, confidence_score, factors,
  home_win_prob, created_at.
- Sibling table: pred_nba_game_lines (NBAGameLines) holds odds_api_event_id
  and spread_home_odds / spread_away_odds.
- Task 14 orchestrator wires a shim joining both tables and surfacing:
  event_id, home_team_name, away_team_name, projected_margin, market_spread_home,
  spread_odds, side ("home"/"away"), confidence_score, factors, generated_at.
- If source raises or returns nothing, provider returns [].
"""
import logging

from app.services.auto_pick.candidate import BetCandidate, DateRange, MarketType

log = logging.getLogger(__name__)


class SpreadCandidateProvider:
    def __init__(self, source):
        self.source = source

    async def get_candidates(self, date_range: DateRange) -> list[BetCandidate]:
        try:
            rows = await self.source.get_todays_projections(date_range)
        except Exception as e:
            log.exception("SpreadCandidateProvider source failed: %s", e)
            return []

        out: list[BetCandidate] = []
        for r in rows:
            try:
                side = r.get("side", "home")
                team = r["home_team_name"] if side == "home" else r["away_team_name"]
                line = float(r["market_spread_home"]) if side == "home" else -float(r["market_spread_home"])
                selection = f"{team} {line:+.1f}"
                out.append(BetCandidate(
                    market_type=MarketType.SPREAD,
                    league=r["league"],
                    event_id=r["event_id"],
                    selection=selection,
                    market_line=line,
                    market_odds=int(r.get("spread_odds", -110)),
                    our_projection=float(r["projected_margin"]),
                    projection_metadata={
                        "edge": r.get("edge"),
                        "recommendation": r.get("recommendation"),
                        "confidence_score": r.get("confidence_score"),
                        "home_win_prob": r.get("home_win_prob"),
                        "factors": r.get("factors"),
                        "generated_at": r.get("generated_at"),
                        "side": side,
                    },
                ))
            except Exception as e:
                log.warning("Skipping malformed spread row: %s", e)
        return out
