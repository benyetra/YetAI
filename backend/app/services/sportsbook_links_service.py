"""
Sportsbook Deep Linking Service

Generates deep links to sportsbook sites with bet information pre-filled.
Supports FanDuel, DraftKings, and other major sportsbooks.
"""

import logging
from typing import Dict, Optional
from urllib.parse import quote, urlencode
from enum import Enum

logger = logging.getLogger(__name__)


class Sportsbook(str, Enum):
    """Supported sportsbooks"""

    FANDUEL = "fanduel"
    DRAFTKINGS = "draftkings"
    CAESARS = "caesars"
    BETMGM = "betmgm"
    BETRIVERS = "betrivers"


class BetType(str, Enum):
    """Types of bets"""

    MONEYLINE = "h2h"
    SPREAD = "spreads"
    TOTAL = "totals"
    PARLAY = "parlay"


class SportsbookLinksService:
    """Service to generate deep links to sportsbooks"""

    # Affiliate tracking codes (replace with your actual affiliate IDs)
    AFFILIATE_CODES = {
        Sportsbook.FANDUEL: "yetai",  # Replace with your FanDuel affiliate code
        Sportsbook.DRAFTKINGS: "yetai",  # Replace with your DraftKings affiliate code
        Sportsbook.CAESARS: "yetai",
        Sportsbook.BETMGM: "yetai",
        Sportsbook.BETRIVERS: "yetai",
    }

    # Base URLs for sportsbooks
    BASE_URLS = {
        Sportsbook.FANDUEL: "https://sportsbook.fanduel.com",
        Sportsbook.DRAFTKINGS: "https://sportsbook.draftkings.com",
        Sportsbook.CAESARS: "https://www.caesars.com/sportsbook-and-casino",
        Sportsbook.BETMGM: "https://sports.betmgm.com",
        Sportsbook.BETRIVERS: "https://www.betrivers.com",
    }

    # Sport path mappings
    SPORT_PATHS = {
        "americanfootball_nfl": {
            Sportsbook.FANDUEL: "navigation/nfl",
            Sportsbook.DRAFTKINGS: "leagues/football/nfl",
        },
        "basketball_nba": {
            Sportsbook.FANDUEL: "navigation/nba",
            Sportsbook.DRAFTKINGS: "leagues/basketball/nba",
        },
        "baseball_mlb": {
            Sportsbook.FANDUEL: "navigation/mlb",
            Sportsbook.DRAFTKINGS: "leagues/baseball/mlb",
        },
        "icehockey_nhl": {
            Sportsbook.FANDUEL: "navigation/nhl",
            Sportsbook.DRAFTKINGS: "leagues/hockey/nhl",
        },
    }

    def generate_fanduel_link(
        self,
        sport_key: str,
        home_team: str,
        away_team: str,
        bet_type: BetType,
        bet_selection: Optional[str] = None,
    ) -> str:
        """
        Generate a FanDuel deep link.

        For FanDuel, we can link to the specific game page.
        If we had API access, we could create a pre-filled bet slip.
        """
        base_url = self.BASE_URLS[Sportsbook.FANDUEL]
        sport_path = self.SPORT_PATHS.get(sport_key, {}).get(
            Sportsbook.FANDUEL, "navigation/nfl"
        )

        # Build URL with affiliate tracking
        params = {
            "utm_source": "yetai",
            "utm_medium": "referral",
            "utm_campaign": "bet_placement",
        }

        # Add affiliate code if available
        if self.AFFILIATE_CODES[Sportsbook.FANDUEL]:
            params["partner"] = self.AFFILIATE_CODES[Sportsbook.FANDUEL]

        query_string = urlencode(params)
        url = f"{base_url}/{sport_path}?{query_string}"

        logger.info(f"Generated FanDuel link: {url}")
        return url

    def generate_draftkings_link(
        self,
        sport_key: str,
        home_team: str,
        away_team: str,
        bet_type: BetType,
        bet_selection: Optional[str] = None,
    ) -> str:
        """
        Generate a DraftKings deep link.

        Links to the specific sport/league page with game lines.
        """
        base_url = self.BASE_URLS[Sportsbook.DRAFTKINGS]
        sport_path = self.SPORT_PATHS.get(sport_key, {}).get(
            Sportsbook.DRAFTKINGS, "leagues/football/nfl"
        )

        # Build URL with tracking
        params = {
            "category": "game-lines",
            "utm_source": "yetai",
            "utm_medium": "referral",
        }

        # Add affiliate code if available
        if self.AFFILIATE_CODES[Sportsbook.DRAFTKINGS]:
            params["wpsrc"] = self.AFFILIATE_CODES[Sportsbook.DRAFTKINGS]

        query_string = urlencode(params)
        url = f"{base_url}/{sport_path}?{query_string}"

        logger.info(f"Generated DraftKings link: {url}")
        return url

    def generate_generic_link(
        self,
        sportsbook: Sportsbook,
        sport_key: str,
        home_team: str,
        away_team: str,
    ) -> str:
        """
        Generate a generic link to a sportsbook.

        For sportsbooks without deep linking support, we link to the main page.
        """
        base_url = self.BASE_URLS.get(sportsbook, "")

        if not base_url:
            logger.warning(f"No URL configured for sportsbook: {sportsbook}")
            return ""

        # Add tracking parameters
        params = {
            "utm_source": "yetai",
            "utm_medium": "referral",
            "utm_campaign": "bet_placement",
        }

        query_string = urlencode(params)
        url = f"{base_url}?{query_string}"

        logger.info(f"Generated {sportsbook} link: {url}")
        return url

    def generate_link(
        self,
        sportsbook: str,
        sport_key: str,
        home_team: str,
        away_team: str,
        bet_type: str = "h2h",
        bet_selection: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Generate a sportsbook link based on the sportsbook type.

        Args:
            sportsbook: The sportsbook key (e.g., 'fanduel', 'draftkings')
            sport_key: Sport identifier (e.g., 'americanfootball_nfl')
            home_team: Home team name
            away_team: Away team name
            bet_type: Type of bet (h2h, spreads, totals)
            bet_selection: The specific selection (team name, over/under)

        Returns:
            Dict with 'url' and 'sportsbook' keys
        """
        try:
            # Normalize sportsbook name
            sportsbook_lower = sportsbook.lower()

            # Generate appropriate link based on sportsbook
            if sportsbook_lower == Sportsbook.FANDUEL:
                url = self.generate_fanduel_link(
                    sport_key, home_team, away_team, BetType(bet_type), bet_selection
                )
            elif sportsbook_lower == Sportsbook.DRAFTKINGS:
                url = self.generate_draftkings_link(
                    sport_key, home_team, away_team, BetType(bet_type), bet_selection
                )
            else:
                # Generic link for other sportsbooks
                url = self.generate_generic_link(
                    Sportsbook(sportsbook_lower), sport_key, home_team, away_team
                )

            return {
                "url": url,
                "sportsbook": sportsbook,
                "requires_manual_selection": True,  # User needs to select bet manually
                "deep_link_supported": sportsbook_lower
                in [Sportsbook.FANDUEL, Sportsbook.DRAFTKINGS],
            }

        except Exception as e:
            logger.error(f"Error generating sportsbook link: {e}")
            return {
                "url": self.BASE_URLS.get(sportsbook, ""),
                "sportsbook": sportsbook,
                "requires_manual_selection": True,
                "deep_link_supported": False,
                "error": str(e),
            }


# Global instance
sportsbook_links_service = SportsbookLinksService()
