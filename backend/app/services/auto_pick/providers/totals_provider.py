"""
Adapter from game-totals projection sources to BetCandidate.

Audit findings:
- Source entry point: source.get_todays_projections(date_range) -> list[dict]
- DB table: pred_nba_totals_projections (NBATotalsProjections model).
  Columns used: game_date, home_team_name, away_team_name, projected_total,
  market_total, edge, recommendation, confidence_score, injury_report, factors,
  created_at.
- Sibling table: pred_nba_game_lines holds over_odds / under_odds.
- Task 14 orchestrator wires a shim joining both tables and surfacing:
  event_id, home_team_name, away_team_name, projected_total, market_total,
  side ("over"/"under"), line_odds, confidence_score, factors, generated_at.
- WNBA equivalent: pred_wnba_totals_projections (WNBATotalsProjections model).
- If source raises or returns nothing, provider returns [].
"""
import logging

from app.services.auto_pick.candidate import BetCandidate, DateRange, MarketType

log = logging.getLogger(__name__)


class TotalsCandidateProvider:
    def __init__(self, source):
        self.source = source

    async def get_candidates(self, date_range: DateRange) -> list[BetCandidate]:
        try:
            rows = await self.source.get_todays_projections(date_range)
        except Exception as e:
            log.exception("TotalsCandidateProvider source failed: %s", e)
            return []

        out: list[BetCandidate] = []
        for r in rows:
            try:
                side = r.get("side", "over")
                market_total = float(r["market_total"])
                selection = f"{r['away_team_name']} vs {r['home_team_name']} {side.upper()} {market_total}"
                out.append(BetCandidate(
                    market_type=MarketType.TOTAL,
                    league=r["league"],
                    event_id=r["event_id"],
                    selection=selection,
                    market_line=market_total,
                    market_odds=int(r.get("line_odds", -110)),
                    our_projection=float(r["projected_total"]),
                    projection_metadata={
                        "edge": r.get("edge"),
                        "recommendation": r.get("recommendation"),
                        "confidence_score": r.get("confidence_score"),
                        "factors": r.get("factors"),
                        "injury_report": r.get("injury_report"),
                        "generated_at": r.get("generated_at"),
                        "side": side,
                    },
                ))
            except Exception as e:
                log.warning("Skipping malformed totals row: %s", e)
        return out
