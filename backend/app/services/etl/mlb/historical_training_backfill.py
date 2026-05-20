"""Point-in-time backfill for game-model training features.

Fills weather, bullpen fatigue, and injury impact into the SQLite training cache
used by ``game_model.build_historical_training_data``. Designed to avoid future
leakage: all values use only data strictly before the game date.
"""

import json
import logging
import sqlite3
from datetime import date, timedelta

import requests

from app.services.etl.mlb.bullpen_fatigue import (
    AVG_BP_IP_3DAY,
    AVG_BP_IP_5DAY,
    AVG_BP_IP_7DAY,
    W_3DAY,
    W_5DAY,
    W_7DAY,
    compute_fatigue_index,
    fetch_team_bullpen_usage,
)
from app.services.etl.mlb.dingerParlay.create_park_coords import PARK_COORDS
from app.services.etl.mlb.injury_tracker import POSITION_IMPACT
from app.services.etl.mlb.weather_enhanced import (
    DOMED_STADIUMS,
    compute_weather_run_adjustment,
    get_dynamic_park_factor,
)

logger = logging.getLogger(__name__)

# Venue name -> park_id (keep in sync with game_model.VENUE_PARK_ID_MAP)
VENUE_PARK_ID = {
    "Chase Field": "ari",
    "Truist Park": "atl",
    "Oriole Park at Camden Yards": "bal",
    "Fenway Park": "bos",
    "Wrigley Field": "chc",
    "Guaranteed Rate Field": "chw",
    "Great American Ball Park": "cin",
    "Progressive Field": "cle",
    "Coors Field": "col",
    "Comerica Park": "det",
    "Minute Maid Park": "hou",
    "Kauffman Stadium": "kc",
    "Angel Stadium": "laa",
    "Dodger Stadium": "lad",
    "loanDepot park": "mia",
    "American Family Field": "mil",
    "Target Field": "min",
    "Citi Field": "nym",
    "Yankee Stadium": "nyy",
    "Sutter Health Park": "oak",
    "Oakland Coliseum": "oak",
    "Citizens Bank Park": "phi",
    "PNC Park": "pit",
    "Petco Park": "sd",
    "Oracle Park": "sf",
    "T-Mobile Park": "sea",
    "Busch Stadium": "stl",
    "Tropicana Field": "tb",
    "Globe Life Field": "tex",
    "Rogers Centre": "tor",
    "Nationals Park": "wsh",
}

VENUE_COORDS = {
    venue: PARK_COORDS[park_id]
    for venue, park_id in VENUE_PARK_ID.items()
    if park_id in PARK_COORDS
}

MONTHLY_AVG_TEMP = {3: 55, 4: 62, 5: 70, 6: 78, 7: 84, 8: 82, 9: 75, 10: 65}

IL_TXN_KEYWORDS = ("injured list", "disabled list")
ACTIVATION_HINTS = ("reinstated", "activated from", "activated off the")


def _is_il_placement(desc_lower):
    return (
        any(k in desc_lower for k in IL_TXN_KEYWORDS)
        and "placed" in desc_lower
        and "activated" not in desc_lower
    )


def _is_il_activation(desc_lower):
    return any(h in desc_lower for h in ACTIVATION_HINTS) and any(
        k in desc_lower for k in IL_TXN_KEYWORDS
    )


def init_backfill_tables(conn):
    """Create cache tables for backfilled training features."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS venue_weather (
            venue_name TEXT, game_date TEXT,
            temperature REAL, wind_speed REAL, wind_direction REAL,
            humidity REAL, source TEXT,
            PRIMARY KEY (venue_name, game_date)
        )"""
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_bullpen_fatigue (
            team_id INTEGER, game_date TEXT, fatigue REAL,
            source TEXT,
            PRIMARY KEY (team_id, game_date)
        )"""
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_injury_impact (
            team_id INTEGER, game_date TEXT, impact REAL,
            PRIMARY KEY (team_id, game_date)
        )"""
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS team_txn_month (
            team_id INTEGER, year_month TEXT, payload TEXT,
            PRIMARY KEY (team_id, year_month)
        )"""
    )


def _monthly_weather_fallback(venue_name, game_date_str):
    gd = date.fromisoformat(game_date_str)
    if venue_name in DOMED_STADIUMS:
        return {
            "temperature": 72.0,
            "wind_speed": 0.0,
            "wind_direction": 0.0,
            "humidity": 50.0,
            "source": "dome",
        }
    return {
        "temperature": float(MONTHLY_AVG_TEMP.get(gd.month, 72)),
        "wind_speed": 8.0,
        "wind_direction": 225.0,
        "humidity": 55.0,
        "source": "monthly_avg",
    }


def _fetch_open_meteo(lat, lon, game_date_str):
    """Historical daily weather from Open-Meteo archive API."""
    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": game_date_str,
        "end_date": game_date_str,
        "daily": (
            "temperature_2m_mean,windspeed_10m_max,"
            "relativehumidity_2m_mean,winddirection_10m_dominant"
        ),
        "temperature_unit": "fahrenheit",
        "windspeed_unit": "mph",
        "timezone": "auto",
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    daily = resp.json().get("daily", {})
    if not daily.get("time"):
        return None
    temp_c = daily.get("temperature_2m_mean", [None])[0]
    if temp_c is None:
        return None
    # Open-Meteo returns Fahrenheit when temperature_unit=fahrenheit
    temp_f = float(temp_c)
    wind = daily.get("windspeed_10m_max", [8.0])[0] or 8.0
    humidity = daily.get("relativehumidity_2m_mean", [55.0])[0] or 55.0
    wind_dir = daily.get("winddirection_10m_dominant", [225.0])[0] or 225.0
    return {
        "temperature": round(temp_f, 1),
        "wind_speed": round(float(wind), 1),
        "wind_direction": float(wind_dir),
        "humidity": round(float(humidity), 1),
        "source": "open_meteo",
    }


def get_weather_as_of(conn, venue_name, game_date_str, use_api=True):
    """Weather snapshot for venue on game date (cached)."""
    row = conn.execute(
        "SELECT temperature, wind_speed, wind_direction, humidity, source "
        "FROM venue_weather WHERE venue_name=? AND game_date=?",
        (venue_name, game_date_str),
    ).fetchone()
    if row:
        return {
            "temperature": row[0],
            "wind_speed": row[1],
            "wind_direction": row[2],
            "humidity": row[3],
            "source": row[4],
        }

    if venue_name in DOMED_STADIUMS:
        w = _monthly_weather_fallback(venue_name, game_date_str)
    elif use_api:
        coords = VENUE_COORDS.get(venue_name)
        if coords:
            try:
                w = _fetch_open_meteo(coords[0], coords[1], game_date_str)
            except Exception as e:
                logger.debug(
                    "Open-Meteo failed for %s %s: %s", venue_name, game_date_str, e
                )
                w = None
        else:
            w = None
        if w is None:
            w = _monthly_weather_fallback(venue_name, game_date_str)
    else:
        w = _monthly_weather_fallback(venue_name, game_date_str)

    conn.execute(
        "INSERT OR REPLACE INTO venue_weather VALUES (?,?,?,?,?,?,?)",
        (
            venue_name,
            game_date_str,
            w["temperature"],
            w["wind_speed"],
            w["wind_direction"],
            w["humidity"],
            w["source"],
        ),
    )
    conn.commit()
    return w


def prewarm_weather(conn, venue_dates, use_api=True):
    """Batch-fetch weather for unique (venue, date) pairs."""
    for venue_name, game_date_str in venue_dates:
        get_weather_as_of(conn, venue_name, game_date_str, use_api=use_api)


def _fatigue_from_game_counts(conn, team_id, season, as_of_date_str):
    """Fast bullpen fatigue proxy from cached team_game_log (no boxscores)."""
    rows = conn.execute(
        "SELECT game_date FROM team_game_log "
        "WHERE team_id=? AND season=? AND game_date < ? "
        "ORDER BY game_date DESC LIMIT 12",
        (team_id, season, as_of_date_str),
    ).fetchall()
    if not rows:
        return 0.5

    as_of = date.fromisoformat(as_of_date_str)
    n3 = n5 = n7 = 0
    for (gd_str,) in rows:
        gd = date.fromisoformat(gd_str)
        days_ago = (as_of - gd).days
        if days_ago <= 0:
            continue
        if days_ago <= 3:
            n3 += 1
        if days_ago <= 5:
            n5 += 1
        if days_ago <= 7:
            n7 += 1

    ip3, ip5, ip7 = n3 * 3.0, n5 * 3.0, n7 * 3.0
    weighted = (
        W_3DAY * (ip3 / (AVG_BP_IP_3DAY * 2.0))
        + W_5DAY * (ip5 / (AVG_BP_IP_5DAY * 2.0))
        + W_7DAY * (ip7 / (AVG_BP_IP_7DAY * 2.0))
    )
    return round(max(0.0, min(1.0, weighted)), 3)


def get_bullpen_fatigue_as_of(
    conn,
    team_id,
    season,
    as_of_date_str,
    accurate=False,
):
    """Bullpen fatigue index as of game_date (cached)."""
    row = conn.execute(
        "SELECT fatigue, source FROM team_bullpen_fatigue "
        "WHERE team_id=? AND game_date=?",
        (team_id, as_of_date_str),
    ).fetchone()
    if row:
        return row[0]

    source = "schedule_proxy"
    if accurate:
        usage = fetch_team_bullpen_usage(
            team_id,
            target_date=date.fromisoformat(as_of_date_str),
        )
        if usage:
            fatigue = compute_fatigue_index(
                usage["ip_last_3_days"],
                usage["ip_last_5_days"],
                usage["ip_last_7_days"],
            )
            source = "boxscore"
        else:
            fatigue = _fatigue_from_game_counts(conn, team_id, season, as_of_date_str)
    else:
        fatigue = _fatigue_from_game_counts(conn, team_id, season, as_of_date_str)

    conn.execute(
        "INSERT OR REPLACE INTO team_bullpen_fatigue VALUES (?,?,?,?)",
        (team_id, as_of_date_str, fatigue, source),
    )
    conn.commit()
    return fatigue


def _fetch_team_transactions_month(team_id, year, month):
    """Fetch MLB transactions for one team-month."""
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)

    url = "https://statsapi.mlb.com/api/v1/transactions"
    params = {
        "teamId": team_id,
        "startDate": start.strftime("%m/%d/%Y"),
        "endDate": end.strftime("%m/%d/%Y"),
    }
    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json().get("transactions", [])


def _load_team_transactions(conn, team_id, start_date, end_date):
    """Load transactions between dates using monthly cache."""
    txns = []
    cursor = date(start_date.year, start_date.month, 1)
    while cursor <= end_date:
        ym = f"{cursor.year}-{cursor.month:02d}"
        row = conn.execute(
            "SELECT payload FROM team_txn_month WHERE team_id=? AND year_month=?",
            (team_id, ym),
        ).fetchone()
        if row:
            month_txns = json.loads(row[0])
        else:
            try:
                month_txns = _fetch_team_transactions_month(
                    team_id,
                    cursor.year,
                    cursor.month,
                )
            except Exception as e:
                logger.debug("txn fetch failed team=%s %s: %s", team_id, ym, e)
                month_txns = []
            conn.execute(
                "INSERT OR REPLACE INTO team_txn_month VALUES (?,?,?)",
                (team_id, ym, json.dumps(month_txns)),
            )
            conn.commit()

        txns.extend(month_txns)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)

    filtered = []
    for txn in txns:
        raw = txn.get("date", "")[:10]
        if not raw:
            continue
        try:
            td = date.fromisoformat(raw)
        except ValueError:
            continue
        if start_date <= td <= end_date:
            filtered.append(txn)
    return filtered


def _txn_person(txn):
    person = txn.get("person") or txn.get("player") or {}
    if isinstance(person, dict):
        return person.get("id"), person.get("fullName")
    return None, None


def _position_from_description(description):
    """Parse leading position token from MLB transaction text (e.g. RHP, SS)."""
    if not description:
        return "Unknown"
    parts = description.split()
    for token in parts[:6]:
        clean = token.strip(".,")
        if clean in POSITION_IMPACT:
            return clean
    return "Unknown"


def _injury_impact_from_transactions(txns, as_of_date):
    """Reconstruct IL burden from transactions strictly before game day."""
    active = {}
    for txn in sorted(txns, key=lambda t: t.get("date", "")):
        raw = txn.get("date", "")[:10]
        if not raw:
            continue
        try:
            td = date.fromisoformat(raw)
        except ValueError:
            continue
        if td >= as_of_date:
            continue

        desc_raw = txn.get("description") or ""
        desc = desc_raw.lower()
        pid, _ = _txn_person(txn)
        if not pid:
            continue

        if _is_il_activation(desc):
            active.pop(pid, None)
            continue

        if not _is_il_placement(desc):
            continue

        pos = _position_from_description(desc_raw)
        active[pid] = POSITION_IMPACT.get(pos, 0.05)

    total = sum(active.values())
    return round(min(total, 1.0), 3)


def get_injury_impact_as_of(conn, team_id, as_of_date_str, lookback_days=60):
    """Team injury impact score as of game_date (cached)."""
    row = conn.execute(
        "SELECT impact FROM team_injury_impact WHERE team_id=? AND game_date=?",
        (team_id, as_of_date_str),
    ).fetchone()
    if row:
        return row[0]

    as_of = date.fromisoformat(as_of_date_str)
    start = as_of - timedelta(days=lookback_days)
    end = as_of - timedelta(days=1)
    if end < start:
        impact = 0.0
    else:
        txns = _load_team_transactions(conn, team_id, start, end)
        impact = _injury_impact_from_transactions(txns, as_of)

    conn.execute(
        "INSERT OR REPLACE INTO team_injury_impact VALUES (?,?,?)",
        (team_id, as_of_date_str, impact),
    )
    conn.commit()
    return impact


def enrich_context_features(
    conn,
    venue_name,
    game_date_str,
    home_team_id,
    away_team_id,
    season,
    base_park_factor,
    use_weather_api=True,
    accurate_bullpen=False,
):
    """Build weather, bullpen, injury, and derived park_factor for one game."""
    weather = get_weather_as_of(
        conn,
        venue_name,
        game_date_str,
        use_api=use_weather_api,
    )
    try:
        wx_adj = compute_weather_run_adjustment(
            temperature_f=weather["temperature"],
            wind_speed_mph=weather["wind_speed"],
            wind_direction_deg=weather.get("wind_direction", 225),
            humidity_pct=weather.get("humidity", 50),
            venue_name=venue_name,
        )
        weather_run_adj = wx_adj["total_adjustment"]
        park_factor = get_dynamic_park_factor(
            venue_name,
            base_park_factor,
            weather_run_adj,
        )
    except Exception:
        weather_run_adj = 0.0
        park_factor = base_park_factor

    home_bp = get_bullpen_fatigue_as_of(
        conn,
        home_team_id,
        season,
        game_date_str,
        accurate=accurate_bullpen,
    )
    away_bp = get_bullpen_fatigue_as_of(
        conn,
        away_team_id,
        season,
        game_date_str,
        accurate=accurate_bullpen,
    )
    home_inj = get_injury_impact_as_of(conn, home_team_id, game_date_str)
    away_inj = get_injury_impact_as_of(conn, away_team_id, game_date_str)

    return {
        "home_bullpen_fatigue": home_bp,
        "away_bullpen_fatigue": away_bp,
        "temperature": weather["temperature"],
        "wind_speed": weather["wind_speed"],
        "injury_impact_home": home_inj,
        "injury_impact_away": away_inj,
        "weather_run_adj": weather_run_adj,
        "park_factor": park_factor,
    }
