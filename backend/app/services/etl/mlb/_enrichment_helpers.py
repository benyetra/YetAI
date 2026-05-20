"""Lightweight helpers for MLB enrichment tasks (no heavy imports)."""


def flatten_batters(batters):
    if not batters:
        return []
    if isinstance(batters[0], dict):
        return batters
    return [batter for sublist in batters for batter in sublist]


def game_odds_key(game: dict) -> str:
    return f"{game['away_name']} @ {game['home_name']}"
