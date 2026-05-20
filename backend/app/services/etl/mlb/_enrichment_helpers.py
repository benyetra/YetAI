"""Lightweight helpers for MLB enrichment tasks (no heavy imports)."""


def flatten_batters(batters):
    if not batters:
        return []
    if isinstance(batters[0], dict):
        return batters
    return [batter for sublist in batters for batter in sublist]


def game_odds_key(game: dict) -> str:
    return f"{game['away_name']} @ {game['home_name']}"


def match_team_price(team_name: str, prices: dict):
    """Map StatsAPI team name to Odds API h2h outcome price (fuzzy fallback)."""
    if team_name in prices:
        return prices[team_name], team_name
    parts = team_name.split()
    if len(parts) >= 2:
        short = " ".join(parts[-2:])
        for label, price in prices.items():
            if short in label or label in team_name:
                return price, label
    for label, price in prices.items():
        if label in team_name or team_name in label:
            return price, label
    return None, None
