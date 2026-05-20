#!/usr/bin/env python3
from datetime import date, datetime, timedelta
import os
import sys
import math
import logging

import click
import requests
import statsapi as mlbstatsapi
import pandas as pd

# S3 reading utility
try:
    import boto3
    from io import BytesIO
except ImportError:
    boto3 = None

def read_csv_anywhere(path, **kwargs):
    """Read CSV from local path or S3 URI (s3://bucket/key)."""
    if path.startswith("s3://"):
        if boto3 is None:
            raise ImportError("boto3 required for S3 support")
        bucket = path.split("/")[2]
        key = "/".join(path.split("/")[3:])
        s3 = boto3.client("s3")
        obj = s3.get_object(Bucket=bucket, Key=key)
        return pd.read_csv(BytesIO(obj["Body"].read()), **kwargs)
    else:
        return pd.read_csv(path, **kwargs)

# your project imports
from app.services.etl.mlb._db import db_session

from app.models.predictions_models import ValueBet

# ─── FLASK APP & DB SETUP ──────────────────────────────────────────────────────

# ─── CONSTANTS & CONFIG ─────────────────────────────────────────────────────────
SPORT             = 'baseball_mlb'
ODDS_API_KEY      = os.getenv('ODDS_API_KEY')
BASE_URL          = 'https://api.the-odds-api.com/v4/sports/'
CURRENT_SEASON    = datetime.today().year
HOME_FIELD_EDGE   = float(os.getenv('EV_HOME_FIELD_EDGE', 0.04))
K_LOGISTIC        = float(os.getenv('EV_K', 5.0))

# Path to your normalized park factors CSV (columns: park_id,hr_factor)
PARK_FACTORS_CSV = "s3://yetibets/mlb/park_factors.csv"
park_factors_df  = read_csv_anywhere(PARK_FACTORS_CSV)
PARK_FACTOR_MAP  = {row['park_id']: row['hr_factor'] for _, row in park_factors_df.iterrows()}

# ─── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# ─── HELPER: PLAYER ID LOOKUP ──────────────────────────────────────────────────
def get_player_id_by_name(full_name):
    if not full_name:
        return None
    try:
        results = mlbstatsapi.lookup_player(full_name)
        if isinstance(results, list) and results:
            return results[0].get('id')
    except Exception:
        logging.warning(f"lookup_player failed for {full_name}")
    return None

# ─── ODDS ──────────────────────────────────────────────────────────────────────
def convert_american_to_implied(odds):
    o = float(odds)
    return abs(o) / (abs(o) + 100) if o < 0 else 100 / (o + 100)

# ─── FETCH TODAY’S GAMES ───────────────────────────────────────────────────────
def get_todays_games():
    today_str = datetime.today().date().strftime('%Y-%m-%d')
    sched = mlbstatsapi.schedule(date=today_str)
    games = []
    for g in sched:
        home_pid = g.get('home_probable_pitcher_id') or get_player_id_by_name(g.get('home_probable_pitcher'))
        away_pid = g.get('away_probable_pitcher_id') or get_player_id_by_name(g.get('away_probable_pitcher'))
        if not home_pid or not away_pid:
            logging.warning(f"Skipping {g['away_name']} @ {g['home_name']}—missing pitcher ID")
            continue
        try:
            info = mlbstatsapi.boxscore_data(g['game_id'])
            park_id = info.get('venue', {}).get('id')
        except Exception:
            park_id = None
        games.append({
            'game_id': g['game_id'],
            'away_name': g['away_name'],
            'home_name': g['home_name'],
            'away_id': g['away_id'],
            'home_id': g['home_id'],
            'home_pitcher_id': home_pid,
            'away_pitcher_id': away_pid,
            'park_id': park_id
        })
    return games


# ─── FETCH ODDS ─────────────────────────────────────────────────────────────────
def get_lineup_ids(team_id):
    data = mlbstatsapi.get('team_roster', {'teamId': team_id, 'rosterType': 'active'})
    roster = data.get('roster', [])
    return [p['person']['id'] for p in roster[:9]]


def bullpen_usage_7d(team_id):
    today = datetime.today().date()
    week_ago = today - timedelta(days=7)
    games = mlbstatsapi.schedule(
        start_date=week_ago.strftime('%Y-%m-%d'),
        end_date=today.strftime('%Y-%m-%d'),
        team=team_id
    )
    total_ip = 0.0
    for g in games:
        bs = mlbstatsapi.boxscore_data(g['game_id'])
        side = 'home' if g['home_id'] == team_id else 'away'
        pen = bs[f"{side}Pitchers"][1:-1]
        for p in pen:
            total_ip += float(p.get('ip', 0) or 0)
    if total_ip > 15:
        return -0.02
    if total_ip < 10:
        return 0.01
    return 0.0


# ─── FETCH ODDS ─────────────────────────────────────────────────────────────────
def get_odds(schedule):
    ev_url = f"{BASE_URL}{SPORT}/events"
    params = {'apiKey': ODDS_API_KEY, 'regions': 'us'}
    ev_resp = requests.get(ev_url, params=params)
    ev_resp.raise_for_status()
    all_events = ev_resp.json()

    today_iso = datetime.utcnow().date().isoformat()
    todays_events = [e for e in all_events if e.get('commence_time', '').startswith(today_iso)]
    lookup = {f"{e['away_team']} @ {e['home_team']}": e['id'] for e in todays_events}

    odds_map = {}
    for g in schedule:
        key = f"{g['away_name']} @ {g['home_name']}"
        eid = lookup.get(key)
        if not eid:
            logging.warning(f"no event ID for {key}")
            continue
        url = (
            f"{BASE_URL}{SPORT}/events/{eid}/odds"
            f"?regions=us&oddsFormat=american&apiKey={ODDS_API_KEY}" 
            "&bookmakers=fanatics"
        )
        r = requests.get(url)
        if r.status_code != 200:
            logging.warning(f"odds failed for {key}: {r.status_code}")
            continue
        data = r.json()
        for bm in data.get('bookmakers', []):
            if bm.get('key') != 'fanatics':
                continue
            for m in bm.get('markets', []):
                if m.get('key') != 'h2h':
                    continue
                odds_map[key] = {o['name']: o['price'] for o in m['outcomes']}
                logging.info(f"{key} → {odds_map[key]}")
    return odds_map

# ─── LINEUP OPS (weighted by PA) ───────────────────────────────────────────────
def weighted_lineup_ops(batter_ids):
    total_ops = 0.0
    total_pa  = 0.0
    for pid in batter_ids:
        try:
            res = mlbstatsapi.player_stat_data(pid, group='hitting', type='season', season=str(CURRENT_SEASON))
            stats = {}
            if isinstance(res, list):
                entry = next((r for r in res if r.get('season') == str(CURRENT_SEASON)), None)
                stats = entry.get('stats', {}) if entry else {}
            elif isinstance(res, dict):
                raw = res.get('stats')
                if isinstance(raw, list):
                    entry = next((r for r in raw if r.get('season') == str(CURRENT_SEASON)), None)
                    stats = entry.get('stats', {}) if entry else {}
                elif isinstance(raw, dict):
                    stats = raw
            ops = float(stats.get('ops', 0.700))
            pa  = float(stats.get('plateAppearances', 1))
            total_ops += ops * pa
            total_pa  += pa
        except Exception:
            continue
    return (total_ops / total_pa) if total_pa else 0.700

# ─── BULLPEN/STATS & UTILITIES ─────────────────────────────────────────────────
def get_bullpen_stats(team_id):
    params = {'teamId': team_id, 'hydrate': 'stats(group=pitching,type=season)', 'fields': 'teams,id,stats'}
    try:
        splits = mlbstatsapi.get('team', params)['teams'][0]['stats'][0]['splits']
        current = next((s for s in splits if s.get('season') == str(CURRENT_SEASON)), None)
        stat = current['stat'] if current else {}
        era = float(stat.get('era', 4.5))
        ip  = float(stat.get('inningsPitched', 1))
        whip = (float(stat.get('hitsAllowed', 0)) + float(stat.get('baseOnBalls', 0))) / max(ip, 1)
        return {'era': era, 'whip': whip}
    except Exception:
        return {'era': 4.5, 'whip': 1.4}

def bullpen_adjustment(era):
    if era < 3.5: return 0.01
    if era > 4.5: return -0.01
    return 0.0

def bullpen_usage_7d(team_id):
    today = datetime.today().date()
    week_ago = today - timedelta(days=7)
    games = mlbstatsapi.schedule(
        start_date=week_ago.strftime('%Y-%m-%d'),
        end_date=today.strftime('%Y-%m-%d'),
        team=team_id
    )
    total_ip = 0.0
    for g in games:
        bs = mlbstatsapi.boxscore_data(g['game_id'])
        side = 'home' if g['home_id'] == team_id else 'away'
        pen = bs[f"{side}Pitchers"][1:-1]
        for p in pen:
            total_ip += float(p.get('ip', 0) or 0)
    if total_ip > 15:
        return -0.02
    if total_ip < 10:
        return 0.01
    return 0.0

# ─── PITCHER EVALUATION ────────────────────────────────────────────────────────
def evaluate_pitcher(pid):
    if not pid:
        return {'xfip': 4.50}
    try:
        ystats = mlbstatsapi.player_stat_data(pid, group='pitching', type='yearByYear')
        if isinstance(ystats, list):
            rec = next((r for r in ystats if r.get('season') == str(CURRENT_SEASON)), None)
            stats = rec.get('stats', {}) if rec else {}
            if stats.get('fip') is not None:
                return {'xfip': float(stats['fip'])}
    except Exception:
        pass
    try:
        sstats = mlbstatsapi.player_stat_data(pid, group='pitching', type='season', season=str(CURRENT_SEASON))
        stats = {}
        if isinstance(sstats, list):
            rec = next((r for r in sstats if r.get('season') == str(CURRENT_SEASON)), None)
            stats = rec.get('stats', {}) if rec else {}
        elif isinstance(sstats, dict):
            raw = sstats.get('stats')
            if isinstance(raw, list):
                rec = next((r for r in raw if r.get('season') == str(CURRENT_SEASON)), None)
                stats = rec.get('stats', {}) if rec else {}
            elif isinstance(raw, dict):
                stats = raw
        return {'xfip': float(stats.get('era', 4.50))}
    except Exception:
        return {'xfip': 4.50}

# ─── MAIN EV CALCULATION ───────────────────────────────────────────────────────
def run_ev() -> int:
    """Compute +EV moneyline value bets for today's slate. Returns rows stored."""
    today = date.today()
    # delete any stale rows for today
    db_session.query(ValueBet) \
            .filter(ValueBet.date == today) \
            .delete(synchronize_session=False)
    db_session.flush()
    # today = datetime.today().date()
    # db_session.query(ValueBet).filter(ValueBet.date == today).delete()
    db_session.commit()

    schedule = get_todays_games()
    odds_map = get_odds(schedule)
    stored = []
    seen = set()   # <— track which pairs we’ve added
    
    for g in schedule:
        key = f"{g['away_name']} @ {g['home_name']} (#{g['game_id']})"
        if key not in odds_map:
            continue

        # intermediate logs
        h_ops   = weighted_lineup_ops(get_lineup_ids(g['home_id']))
        a_ops   = weighted_lineup_ops(get_lineup_ids(g['away_id']))
        h_xfip  = evaluate_pitcher(g['home_pitcher_id'])['xfip']
        a_xfip  = evaluate_pitcher(g['away_pitcher_id'])['xfip']
        pf      = PARK_FACTOR_MAP.get(g.get('park_id'), 0.0)

        logging.debug(f"{key}: h_ops={h_ops:.3f}, a_ops={a_ops:.3f}, "
                      f"h_xfip={h_xfip:.2f}, a_xfip={a_xfip:.2f}, park_factor={pf:.3f}")

        # logistic base
        h_ratio = h_ops / a_xfip
        a_ratio = a_ops / h_xfip
        diff    = h_ratio - a_ratio + pf
        base    = 1.0 / (1.0 + math.exp(-diff * K_LOGISTIC))
        h_prob  = min(1.0, max(0.0, base + HOME_FIELD_EDGE))
        a_prob  = 1.0 - h_prob

        # bullpen mods
        h_prob = max(0, min(1, h_prob + bullpen_adjustment(get_bullpen_stats(g['home_id'])['era'])
                             + bullpen_usage_7d(g['home_id'])))
        a_prob = 1 - h_prob

        logging.debug(f"{key}: h_prob={h_prob:.3f}, a_prob={a_prob:.3f}")

        for team_name, prob in ((g['home_name'], h_prob), (g['away_name'], a_prob)):
            # skip exact duplicates within this run
            if (key, team_name) in seen:
                continue
            odds = odds_map[key].get(team_name)
            if odds is None:
                continue
            imp = convert_american_to_implied(odds)
            ev  = (prob - imp) * 100
            if ev <= 0:
                continue

            seen.add((key, team_name))
            vb = ValueBet(
                date=today,
                game=key,
                team=team_name,
                estimated_prob=prob,
                implied_prob=imp,
                expected_value=ev
            )
            db_session.add(vb)
            stored.append(vb)

    db_session.commit()
    logging.info("Stored %s value bets for %s", len(stored), today)
    return len(stored)


def run() -> dict:
    """Celery entry: refresh pred_value_bets for today."""
    from app.services.etl.mlb._db import close_session, init_session

    init_session()
    try:
        count = run_ev()
        return {
            "status": "ok",
            "task": "mlb_ev",
            "date": str(date.today()),
            "value_bets_stored": count,
        }
    finally:
        close_session()


if __name__ == "__main__":
    from app.services.etl.mlb._db import init_session, close_session

    init_session()
    try:
        n = run_ev()
        print(f"[DONE] stored {n} value bets for {date.today()}.")
    finally:
        close_session()
