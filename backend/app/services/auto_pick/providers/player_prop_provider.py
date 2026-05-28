"""
Adapter from player-prop prediction sources to BetCandidate.

Audit findings:
- Source entry point: source.get_todays_projections(date_range) -> list[dict]
- DB tables: pred_points_projections (NBA pts), pred_strikeout_projections (MLB Ks),
  pred_assists_projections, pred_rebounds_projections, etc. — one table per stat type.
- player_props_service.PlayerPropsService fetches *live odds* from The Odds API
  (not stored projections); it is NOT the source for our ML projections.
- No unified player-prop table with odds exists; Task 14 orchestrator wires a shim
  that joins pred_*_projections with live odds from odds_api_service.
- If source raises or returns nothing, provider returns [].
"""

import logging

from app.services.auto_pick.candidate import BetCandidate, DateRange, MarketType

log = logging.getLogger(__name__)


class PlayerPropCandidateProvider:
    def __init__(self, source):
        self.source = source

    async def get_candidates(self, date_range: DateRange) -> list[BetCandidate]:
        try:
            rows = await self.source.get_todays_projections(date_range)
        except Exception as e:
            log.exception("PlayerPropCandidateProvider source failed: %s", e)
            return []

        out: list[BetCandidate] = []
        for r in rows:
            try:
                selection = f"{r['player']} {r['side'].upper()} {r['line']} {r['stat']}"
                away = (r.get("away_team_name") or r.get("team") or "").strip() or None
                home = (r.get("home_team_name") or "").strip() or None
                opponent = (
                    r.get("opponent") or r.get("opponent_team_name") or ""
                ).strip() or None
                out.append(
                    BetCandidate(
                        market_type=MarketType.PLAYER_PROP,
                        league=r["league"],
                        event_id=r["event_id"],
                        selection=selection,
                        market_line=float(r["line"]),
                        market_odds=int(r["odds"]),
                        our_projection=float(r["projection"]),
                        projection_metadata={
                            "sample_size": r.get("sample_size"),
                            "generated_at": r.get("generated_at"),
                            "model_confidence": r.get("model_confidence"),
                            "injury_flag": r.get("injury_flag", False),
                            "stat": r["stat"],
                            "side": r["side"],
                            "player": r.get("player"),
                            "team": r.get("team"),
                            "opponent": opponent,
                            "opponent_team_name": opponent,
                        },
                        away_team=away,
                        home_team=home,
                        commence_time=r.get("commence_time"),
                    )
                )
            except Exception as e:
                log.warning("Skipping malformed player-prop row: %s", e)
        return out
