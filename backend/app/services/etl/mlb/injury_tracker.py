"""MLB Injury & IL Tracker.

Fetches current injured list placements and roster transactions to assess
team-level injury impact. Used as a feature input for game-level projections.

PRD v2.0 §5.2 — Injury/IL Feed (P0, Phase 1).
"""
import sys
import os

import logging
from datetime import date, timedelta
import requests
import statsapi as mlbstatsapi

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

CURRENT_SEASON = date.today().year

# Injury impact weights by position (how much a player's absence affects game outcome)
POSITION_IMPACT = {
    'SP': 0.0,    # Starting pitcher absence handled by replacement pitcher stats
    'RP': 0.05,
    'CP': 0.15,   # Closer
    'C': 0.08,
    '1B': 0.07,
    '2B': 0.06,
    '3B': 0.07,
    'SS': 0.07,
    'LF': 0.06,
    'CF': 0.07,
    'RF': 0.06,
    'DH': 0.06,
    'OF': 0.06,
    'IF': 0.06,
    'P': 0.05,
}


def fetch_team_roster_il(team_id):
    """Fetch IL players from the team's 40-man roster.

    Returns list of dicts with player info and IL status.
    """
    il_players = []
    try:
        data = mlbstatsapi.get('team_roster', {
            'teamId': team_id,
            'rosterType': '40Man'
        })
        for player in data.get('roster', []):
            status = player.get('status', {})
            status_code = status.get('code', '')
            # IL status codes: IL10, IL15, IL60, IL7, D7, D10, D15, D60
            if status_code in ('IL10', 'IL15', 'IL60', 'IL7', 'D7', 'D10', 'D15', 'D60'):
                person = player.get('person', {})
                position = player.get('position', {})
                il_players.append({
                    'player_id': person.get('id'),
                    'player_name': person.get('fullName', 'Unknown'),
                    'position': position.get('abbreviation', 'Unknown'),
                    'status_code': status_code,
                    'status_description': status.get('description', ''),
                })
    except Exception as e:
        logger.warning(f"Failed to fetch roster for team {team_id}: {e}")

    return il_players


def fetch_recent_transactions(lookback_days=7):
    """Fetch recent transactions (IL placements, activations, DFA, options).

    Returns dict keyed by team name with transaction lists.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)

    url = (
        f"https://statsapi.mlb.com/api/v1/transactions"
        f"?startDate={start_date.strftime('%m/%d/%Y')}"
        f"&endDate={end_date.strftime('%m/%d/%Y')}"
    )

    transactions = {}
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        for txn in data.get('transactions', []):
            txn_type = txn.get('typeCode', '')
            # Filter to IL-related transactions
            if txn_type not in ('DL', 'ASG', 'SC', 'REL', 'DFA', 'FA'):
                description = txn.get('description', '')
                if 'injured list' not in description.lower() and 'disabled list' not in description.lower():
                    continue

            team = txn.get('team', {})
            team_name = team.get('name', 'Unknown')
            player = txn.get('player', {})

            if team_name not in transactions:
                transactions[team_name] = []

            transactions[team_name].append({
                'player_name': player.get('fullName', 'Unknown'),
                'player_id': player.get('id'),
                'type': txn.get('typeDesc', ''),
                'description': txn.get('description', ''),
                'date': txn.get('date', ''),
            })
    except Exception as e:
        logger.warning(f"Failed to fetch transactions: {e}")

    return transactions


def get_team_injury_impact(team_id):
    """Compute aggregate injury impact score for a team.

    Returns a float 0.0 (no impact) to 1.0 (severe).
    Based on number and importance of IL players.
    """
    il_players = fetch_team_roster_il(team_id)

    if not il_players:
        return 0.0

    total_impact = 0.0
    for player in il_players:
        pos = player.get('position', 'Unknown')
        impact = POSITION_IMPACT.get(pos, 0.05)
        total_impact += impact

    # Cap at 1.0 and scale — even heavy injuries rarely eliminate a team
    return round(min(total_impact, 1.0), 3)


def get_active_injuries(team_id):
    """Get list of current IL players for a team.

    Returns list of dicts with player_name, position, status.
    """
    return fetch_team_roster_il(team_id)


def get_all_teams_injury_impact():
    """Compute injury impact scores for all 30 MLB teams.

    Returns dict: {team_id: {'team_name': str, 'impact': float, 'il_count': int, 'players': list}}
    """
    teams = mlbstatsapi.get('teams', {'sportId': 1, 'season': CURRENT_SEASON})
    results = {}

    for team in teams.get('teams', []):
        if team.get('sport', {}).get('id') != 1:
            continue

        team_id = team['id']
        team_name = team['name']
        logger.info(f"Checking injuries for {team_name}")

        il_players = fetch_team_roster_il(team_id)
        impact = get_team_injury_impact(team_id)

        results[team_id] = {
            'team_name': team_name,
            'impact': impact,
            'il_count': len(il_players),
            'players': il_players
        }

    return results


if __name__ == '__main__':
    impacts = get_all_teams_injury_impact()
    for team_id, data in sorted(impacts.items(), key=lambda x: -x[1]['impact']):
        if data['il_count'] > 0:
            print(f"{data['team_name']}: impact={data['impact']:.3f}, "
                  f"IL={data['il_count']} players")
            for p in data['players']:
                print(f"  - {p['player_name']} ({p['position']}) [{p['status_code']}]")
