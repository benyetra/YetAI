import sys
import os

import pandas as pd
from sqlalchemy import text

from app.services.etl.mlb.lineup_utils import (
    lineup_k_rate_vs_hand,
    lineup_matchup_adjusted_strikeouts,
    projected_lineup,
)
from app.services.etl.mlb.offsets import apply_shrunk_offsets
import numpy as np
import requests
import statsapi
from datetime import datetime, timedelta
from app.services.etl.mlb._db import db_session
from app.models.predictions_models import Pitcher
from app.services.etl.mlb._mlb_utils import *
from app.services.etl.mlb.regression_analysis import (
    calculate_performance_metrics,
    fetch_past_performance_metrics,
    perform_regression_analysis,
    project_at_bats_faced,
    project_innings_pitched,
)

from app.services.etl.mlb.classification_model import (
    load_classifier,
    park_factor_for_venue,
)
from app.services.etl.mlb.odds_utils import (
    american_to_break_even_prob,
    normalize_two_sided,
    expected_value,
)
from app.services.etl.mlb.offsets import apply_shrunk_offsets

# initialize the calibrated classifier once
over_under_clf = load_classifier()
if over_under_clf is None:
    raise RuntimeError(
        "Strikeout classifier failed to load. "
        "Run: python scripts/mlb/classification_model.py --retrain"
    )
from app.services.etl.mlb.mlb_matchup_analysis import (
    matchup_adjusted_strikeouts,
    fetch_last_start_date,
)


# Database configuration

ODDS_API_KEY = os.getenv("ODDS_API_KEY")
MIN_GAMES_THRESHOLD = 6  # Minimum number of games to calculate golden opportunities
BASE_URL = "https://api.the-odds-api.com/v4/sports/baseball_mlb"
HEADERS = {
    "Content-Type": "application/json",
}
# ————————————————
# PARK FACTORS
PARK_FACTORS_CSV = "s3://yetibets/mlb/park_factors.csv"
_pf_df = read_csv_anywhere(PARK_FACTORS_CSV)
PARK_FACTOR_MAP = {row["park_id"]: row["hr_factor"] for _, row in _pf_df.iterrows()}


def get_park_factor(park_id):
    return PARK_FACTOR_MAP.get(park_id, 1.0)


def get_team_id(team_name):
    url = "https://statsapi.mlb.com/api/v1/teams"
    response = requests.get(url)
    data = response.json()

    for team in data["teams"]:
        if team["name"] == team_name:
            return team["id"]
    return None


def get_last_5_games_k_per_9(player_id):
    end_date = datetime.today()
    start_date = end_date - timedelta(
        days=30
    )  # Approximate last 30 days to get last 5 games
    hydrate = f"stats(group=[pitching],type=[byDateRange],startDate={start_date.strftime('%Y-%m-%d')},endDate={end_date.strftime('%Y-%m-%d')})"

    url = f"https://statsapi.mlb.com/api/v1/people/{player_id}"
    params = {"hydrate": hydrate}
    response = requests.get(url, params=params)
    data = response.json()

    last_5_k_per_9 = []
    game_dates = set()  # To track unique game dates

    if (
        "people" in data
        and isinstance(data["people"], list)
        and len(data["people"]) > 0
    ):
        person = data["people"][0]
        if (
            "stats" in person
            and isinstance(person["stats"], list)
            and len(person["stats"]) > 0
        ):
            stats = person["stats"][0]["splits"]
            if isinstance(stats, list):
                for split in stats:
                    if "stat" in split:
                        stat = split["stat"]
                        game_date = split.get("date", "")
                        if game_date in game_dates:
                            continue  # Skip duplicate games
                        game_dates.add(game_date)
                        innings_pitched = float(stat.get("inningsPitched", 0))
                        strikeouts = float(stat.get("strikeOuts", 0))
                        if innings_pitched > 0:
                            k_per_9 = round((strikeouts / innings_pitched) * 9, 3)
                            last_5_k_per_9.append(k_per_9)
                            if len(last_5_k_per_9) >= 5:  # Only keep the last 5 games
                                break
            else:
                print(f"Unexpected 'splits' structure: {stats}")
        else:
            print(f"No valid 'stats' found for player_id {player_id}")
    else:
        print(f"No valid 'people' found in data for player_id {player_id}")

    if last_5_k_per_9:
        return round(sum(last_5_k_per_9) / len(last_5_k_per_9), 2)
    else:
        return 0.0


def get_todays_games():
    from app.services.etl.nba._espn import now_eastern

    today = now_eastern().date().strftime("%Y-%m-%d")
    return statsapi.schedule(date=today)


def strikeout_schedule_diagnostics() -> dict:
    """Why pred_pitcher might be empty (no probable starter in statsapi schedule)."""
    from app.services.etl.nba._espn import now_eastern

    schedule = get_todays_games() or []
    games_with_probable = 0
    for game in schedule:
        if game.get("home_probable_pitcher") or game.get("away_probable_pitcher"):
            games_with_probable += 1
    return {
        "date_et": str(now_eastern().date()),
        "schedule_games": len(schedule),
        "games_with_probable_pitcher": games_with_probable,
    }


def get_event_id_for_game(team1, team2):
    events_url = f"{BASE_URL}/events"
    params = {"apiKey": ODDS_API_KEY}
    response = requests.get(events_url, headers=HEADERS, params=params)
    if response.status_code == 200:
        events = response.json()
        for event in events:
            if (event["home_team"] == team1 and event["away_team"] == team2) or (
                event["home_team"] == team2 and event["away_team"] == team1
            ):
                return event["id"]
    else:
        print(
            f"Failed to fetch events: {response.status_code}, response body: {response.text}"
        )

    return None


def fetch_pitcher_data():
    EDGE_GATE = 0.02  # require ≥2% EV to call a side; otherwise neutral 'n'
    schedule = get_todays_games()
    pitchers = []
    build_stats = {
        "probables_seen": 0,
        "skipped_ab_projection": 0,
        "build_errors": 0,
    }

    for game in schedule:
        game_id = game["game_id"]
        venue_name = game["venue_name"]
        for team in ["home", "away"]:
            probable_pitcher_key = f"{team}_probable_pitcher"
            if probable_pitcher_key in game:
                build_stats["probables_seen"] += 1
                pitcher_name = game[probable_pitcher_key]
                team_name_key = f"{team}_name"
                opponent_team = "away" if team == "home" else "home"
                opponent_team_id = game[f"{opponent_team}_id"]
                pitcher_id = None
                game_time_utc = game["game_datetime"]
                print("Game time: " + game_time_utc)
                name = game[team_name_key]

                try:
                    game_time_utc = datetime.strptime(
                        game_time_utc, "%Y-%m-%dT%H:%M:%SZ"
                    )
                    game_time_est = game_time_utc
                except ValueError:
                    game_time_est = None
                try:
                    pitcher_id = statsapi.lookup_player(pitcher_name)[0]["id"]
                except IndexError:
                    print(f"Error finding pitcher ID for {pitcher_name}")
                    continue
                try:
                    pitcher_stats_data = statsapi.player_stat_data(
                        pitcher_id, group="pitching", type="career"
                    )
                    stats = pitcher_stats_data["stats"][0]["stats"]
                except (IndexError, KeyError):
                    print(f"Error finding stats data for pitcher {pitcher_name}")
                    continue
                try:
                    pitch_hand = pitcher_stats_data["pitch_hand"]
                except KeyError:
                    print(f"Error extracting pitch hand for {pitcher_name}")
                    pitch_hand = "Unknown"
                try:
                    innings_pitched = float(stats.get("inningsPitched", 0.0))
                except (KeyError, IndexError):
                    print(f"Error extracting inningsPitched for {pitcher_name}")
                    innings_pitched = 0.0
                try:
                    games_played = float(stats.get("gamesPlayed", 1))
                except (KeyError, IndexError):
                    print(f"Error extracting gamesPlayed for {pitcher_name}")
                    games_played = 1
                try:
                    pitches_per_innings = float(stats.get("pitchesPerInning", 0.0))
                except (KeyError, IndexError):
                    print(f"Error extracting pitches_per_innings for {pitcher_name}")
                    pitches_per_innings = 0.0
                try:
                    walks_per_9 = float(stats.get("walksPer9Inn", 0.0))
                except (KeyError, IndexError):
                    print(f"Error extracting walks_per_9 for {pitcher_name}")
                    walks_per_9 = 0.0
                try:
                    k_per_9 = float(stats.get("strikeoutsPer9Inn", 0.0))
                except (KeyError, IndexError):
                    k_per_9 = 0.0

                last_5_avg_k_per_9 = get_last_5_games_k_per_9(pitcher_id)

                sit_code = "vr" if pitch_hand == "R" else "vl"
                # Use current season, fall back to prior season if no data yet
                current_season = str(datetime.today().year)
                opponent_stats = statsapi.get(
                    "team_stats",
                    {
                        "teamId": opponent_team_id,
                        "season": current_season,
                        "group": "hitting",
                        "gameType": "R",
                        "stats": "statSplits",
                        "sitCodes": sit_code,
                    },
                )
                # Early season fallback: if no splits for current year, use prior season
                try:
                    _test = opponent_stats["stats"][0]["splits"][0]["stat"]["atBats"]
                except (KeyError, IndexError):
                    prior_season = str(datetime.today().year - 1)
                    opponent_stats = statsapi.get(
                        "team_stats",
                        {
                            "teamId": opponent_team_id,
                            "season": prior_season,
                            "group": "hitting",
                            "gameType": "R",
                            "stats": "statSplits",
                            "sitCodes": sit_code,
                        },
                    )

                try:
                    at_bats = opponent_stats["stats"][0]["splits"][0]["stat"]["atBats"]
                    strikeouts = opponent_stats["stats"][0]["splits"][0]["stat"][
                        "strikeOuts"
                    ]
                    if at_bats > 0:
                        opponent_k_rate = float(strikeouts) / float(at_bats)
                        opponent_k_rate = round(opponent_k_rate * 100, 2)
                    else:
                        opponent_k_rate = 0.0
                except (KeyError, IndexError, TypeError):
                    opponent_k_rate = 0.0

                combined_score = round(k_per_9 + opponent_k_rate, 2)

                # Fetch performance metrics for error calculation
                past_performance_df = fetch_past_performance_metrics(pitcher_id)
                (
                    mean_absolute_strikeout_error,
                    mean_absolute_innings_error,
                    mean_absolute_at_bats_error,
                ) = calculate_performance_metrics(past_performance_df)

                pitcher_data = {
                    "combined_score": combined_score,
                    "fanduel_point": 0.0,  # Initialize with default value
                    "fanduel_price": 0.0,  # Initialize with default value
                    "game_status": isGameOver(game),
                    "game_time": game_time_est,
                    "id": 1,
                    "k_per_9": k_per_9,
                    "last_5_avg_k_per_9": last_5_avg_k_per_9,  # Ensure last_5_avg_k_per_9 is included
                    "name": pitcher_name,
                    "opponent": game[f"{opponent_team}_name"],
                    "opponent_k_rate": opponent_k_rate,
                    "pitch_hand": pitch_hand,
                    "pitcher_id": pitcher_id,
                    "walks_per_9": walks_per_9,
                    "pitches_per_innings": pitches_per_innings,
                    "games_played": games_played,
                    "innings_pitched": innings_pitched,
                    "venue_name": venue_name,
                    "game_id": game_id,
                }

                # --- app.py (REPLACE the inner try: block after pitcher_data = {...}) ---
                try:
                    # 1) Project innings (baseline)
                    projected_innings = project_innings_pitched(
                        pitcher_data, mean_absolute_innings_error
                    )
                    print("Projected innings pitched:", projected_innings)

                    # 2) Opponent lineup → batter_ids and lineup K% vs hand
                    opponent_team_id = game[f"{opponent_team}_id"]
                    batter_ids = projected_lineup(opponent_team_id)
                    pitcher_hand_code = (
                        "R" if (pitch_hand or "R").startswith("R") else "L"
                    )
                    opp_k_rate_lineup = lineup_k_rate_vs_hand(
                        opponent_team_id, pitcher_hand_code
                    )
                    # keep your old team stat as fallback (opponent_k_rate was %); convert to fraction
                    opp_k_rate_frac = (
                        opp_k_rate_lineup
                        if opp_k_rate_lineup is not None
                        else (opponent_k_rate / 100.0)
                    )

                    # pick any batter id for APIs that require one (regression uses pitcher+batter)
                    batter_id = (
                        batter_ids[0]
                        if batter_ids
                        else statsapi.get(
                            "team_roster",
                            {"teamId": opponent_team_id, "rosterType": "active"},
                        )["roster"][0]["person"]["id"]
                    )

                    # 3) First pass ABs + Ks from baseline IP
                    recent_data_base = {
                        "innings_pitched": projected_innings,
                        "strikeouts": pitcher_data["k_per_9"] * projected_innings,
                        "walks": pitcher_data["walks_per_9"] * projected_innings,
                    }
                    projected_at_bats_base = project_at_bats_faced(
                        pitcher_id,
                        recent_data_base,
                        projected_innings,
                        mean_absolute_at_bats_error,
                    )
                    if projected_at_bats_base is None:
                        build_stats["skipped_ab_projection"] += 1
                        print(f"Not enough data to project AB for {pitcher_name}")
                        continue

                    projected_strikeouts_base = (
                        perform_regression_analysis(
                            pitcher_id,
                            batter_id,
                            projected_innings,
                            projected_at_bats_base,
                        )
                        or 0.0
                    )

                    # 4) Apply shrunk offsets (empirical-Bayes bias correction)
                    adj_k, adj_ip, meta = apply_shrunk_offsets(
                        projected_strikeouts_base, projected_innings, str(pitcher_id)
                    )

                    # 5) Re-project ABs at adjusted IP
                    recent_data = {
                        "innings_pitched": adj_ip,
                        "strikeouts": pitcher_data["k_per_9"] * adj_ip,
                        "walks": pitcher_data["walks_per_9"] * adj_ip,
                    }
                    projected_at_bats = project_at_bats_faced(
                        pitcher_id, recent_data, adj_ip, mean_absolute_at_bats_error
                    )
                    if projected_at_bats is None:
                        build_stats["skipped_ab_projection"] += 1
                        print(f"Not enough data to project AB (adj) for {pitcher_name}")
                        continue

                    # 6) Re-run K regression with adjusted IP/AB and blend with debiased K
                    proj_k_reg = (
                        perform_regression_analysis(
                            pitcher_id, batter_id, adj_ip, projected_at_bats
                        )
                        or 0.0
                    )
                    proj_k_final = 0.5 * adj_k + 0.5 * proj_k_reg

                    # 7) Odds (event_id)
                    event_id = get_event_id_for_game(
                        game[f"{team}_name"],
                        game["away_name"] if team == "home" else game["home_name"],
                    )
                    threshold, over_price, under_price = get_book_line(
                        event_id, pitcher_name
                    )

                    # 8) Build features (incl. matchup factor & days rest & distance-to-line)
                    last_start = fetch_last_start_date(pitcher_id)
                    days_rest = (
                        (datetime.today().date() - last_start).days if last_start else 7
                    )

                    # lineup-weighted matchup factor
                    matchup_factor = lineup_matchup_adjusted_strikeouts(
                        pitcher_id, batter_ids, pitcher_hand_code
                    )

                    park_factor = park_factor_for_venue(venue_name)
                    proj_minus_line = (proj_k_final - threshold) if threshold else 0.0

                    X_feature_df = pd.DataFrame(
                        [
                            {
                                "projected_strikeouts": proj_k_final,
                                "proj_ip": adj_ip,
                                "proj_ab": projected_at_bats,
                                "threshold": threshold,
                                "matchup_factor": matchup_factor,
                                "days_rest": days_rest,
                                "park_factor": park_factor,
                                "proj_minus_line": proj_minus_line,
                            }
                        ]
                    )

                    prob_over_clf = over_under_clf.predict_proba(X_feature_df)[0, 1]

                    # Optional recency/mix/velo deltas as future features (not fed into model here):
                    # delta_mix, delta_velo = 0.0, 0.0

                    # 9) Distributional overlay (Negative Binomial) and EV-based decision
                    # var proxy: use residual variance hint or simple over-dispersion factor
                    # here, assume variance = mu + 0.8*mu  (tweak with backtests)
                    from app.services.etl.mlb.kdist import negbin_prob_over

                    mu = max(0.01, proj_k_final)
                    var = mu * 1.8
                    prob_over_nb = (
                        negbin_prob_over(mu, var, threshold)
                        if threshold
                        else prob_over_clf
                    )

                    # ensemble
                    prob_over = 0.6 * prob_over_clf + 0.4 * prob_over_nb

                    # EV selection
                    EDGE_GATE = 0.02
                    from app.services.etl.mlb.odds_utils import (
                        american_to_break_even_prob,
                        normalize_two_sided,
                        expected_value,
                    )

                    if (
                        over_price is not None
                        and under_price is not None
                        and threshold
                        and threshold > 0
                    ):
                        p_over_raw = american_to_break_even_prob(over_price)
                        p_under_raw = american_to_break_even_prob(under_price)
                        _p_over_fair, _p_under_fair = normalize_two_sided(
                            p_over_raw, p_under_raw
                        )
                        ev_over = expected_value(prob_over, over_price)
                        ev_under = expected_value(1 - prob_over, under_price)

                        if ev_over >= ev_under and ev_over >= EDGE_GATE:
                            flag, price_to_show, edge = "o", over_price, ev_over
                        elif ev_under > ev_over and ev_under >= EDGE_GATE:
                            flag, price_to_show, edge = "u", under_price, ev_under
                        else:
                            flag, price_to_show, edge = "n", 0, max(ev_over, ev_under)
                    else:
                        flag, price_to_show, edge = (
                            ("o" if prob_over >= 0.5 else "u"),
                            (over_price or 0),
                            abs(prob_over - 0.5),
                        )

                    # store result for UI / DB
                    pitchers.append(
                        {
                            "name": pitcher_name,
                            "pitcher_id": pitcher_id,
                            "pitch_hand": pitch_hand,
                            "team": game[team_name_key],
                            "opponent": game[f"{opponent_team}_name"],
                            "display_game_time": game_time_est,
                            "game_status": isGameOver(game),
                            "last_5_avg_k_per_9": last_5_avg_k_per_9,
                            "k_per_9": k_per_9,
                            "opponent_k_rate": round(opp_k_rate_frac * 100.0, 2),
                            "combined_score": round(
                                k_per_9 + (opp_k_rate_frac * 100.0), 2
                            ),
                            "projected_innings": adj_ip,
                            "projected_at_bats": projected_at_bats,
                            "projected_strikeouts": proj_k_final,
                            "fanduel_point": threshold,
                            "fanduel_price": price_to_show,
                            "fanduel_flag": flag,
                            "edge": round(edge * 100, 1),
                            "k_bias": round(meta["k_bias"], 2),
                            "ip_bias": round(meta["ip_bias"], 2),
                            "bias_n": meta["n"],
                            "innings_pitched": innings_pitched,
                            "walks_per_9": walks_per_9,
                            "pitches_per_innings": pitches_per_innings,
                            "games_played": games_played,
                            "venue_name": venue_name,
                            "game_id": game_id,
                        }
                    )
                except Exception as e:
                    build_stats["build_errors"] += 1
                    db_session.rollback()
                    print(f"Error building projections for {pitcher_name}: {e}")

    pitchers.sort(key=lambda x: x["combined_score"], reverse=True)
    return pitchers, build_stats


def get_book_line(event_id, pitcher_name):
    """
    Return (threshold, over_price, under_price).
    """
    try:
        odds_url = f"{BASE_URL}/events/{event_id}/odds"
        params = {
            "regions": "us",
            "oddsFormat": "american",
            "apiKey": ODDS_API_KEY,
            "markets": "pitcher_strikeouts",
        }
        resp = requests.get(odds_url, headers=HEADERS, params=params)
        resp.raise_for_status()
        data = resp.json()

        for bm in data.get("bookmakers", []):
            key = (bm.get("key") or bm.get("title", "")).lower()
            if key != "fanduel":
                continue
            for market in bm.get("markets", []):
                if market.get("key") != "pitcher_strikeouts":
                    continue
                over_price = under_price = None
                threshold = None
                for outcome in market.get("outcomes", []):
                    if outcome.get("description") != pitcher_name:
                        continue
                    if threshold is None and "point" in outcome:
                        threshold = float(outcome["point"])
                    name = outcome.get("name", "").lower()
                    if name == "over":
                        over_price = int(outcome["price"])
                    elif name == "under":
                        under_price = int(outcome["price"])
                if (
                    threshold is not None
                    and over_price is not None
                    and under_price is not None
                ):
                    return threshold, over_price, under_price
        return 0.0, None, None
    except Exception as e:
        print(f"FD odds fetch error {pitcher_name}/{event_id}: {e}")
        return 0.0, None, None


def fetch_and_update_app_data():
    try:
        pitchers, build_stats = fetch_pitcher_data()
        built = len(pitchers)

        db_session.query(Pitcher).delete()
        db_session.commit()

        for pitcher_stats_data in pitchers:
            pitcher_id = pitcher_stats_data.get("pitcher_id")
            pitcher = Pitcher(
                pitcher_id=pitcher_id,
                name=pitcher_stats_data["name"],
                pitch_hand=pitcher_stats_data["pitch_hand"],
                team=pitcher_stats_data["team"],
                opponent=pitcher_stats_data["opponent"],
                game_time=pitcher_stats_data["display_game_time"],
                k_per_9=float(pitcher_stats_data["k_per_9"]),
                last_5_avg_k_per_9=float(pitcher_stats_data["last_5_avg_k_per_9"]),
                opponent_k_rate=float(pitcher_stats_data["opponent_k_rate"]),
                combined_score=float(pitcher_stats_data["combined_score"]),
                fanduel_point=float(pitcher_stats_data["fanduel_point"]),
                fanduel_price=float(pitcher_stats_data["fanduel_price"]),
                fanduel_flag=pitcher_stats_data["fanduel_flag"],
                game_status=pitcher_stats_data["game_status"],
                venue_name=pitcher_stats_data["venue_name"],
                projected_strikeouts=float(pitcher_stats_data["projected_strikeouts"]),
                projected_innings=float(pitcher_stats_data["projected_innings"]),
                projected_at_bats=float(pitcher_stats_data["projected_at_bats"]),
                game_id=pitcher_stats_data["game_id"],
            )

            db_session.add(pitcher)
            db_session.commit()
            print(
                f"Added pitcher {pitcher_stats_data['name']} to the session with projected at-bats {pitcher_stats_data['projected_at_bats']}."
            )

        print("Data updated successfully.")
        stored = db_session.query(Pitcher).count()
        return stored, built
    except Exception as e:
        db_session.rollback()
        print(f"Error fetching and storing data: {e}")
        raise


def run() -> dict:
    """Rebuild pred_pitcher (strikeout board) for today's slate."""
    from app.services.etl.mlb._db import init_session, close_session

    init_session()
    try:
        count, built = fetch_and_update_app_data()
        if not count:
            return {
                "status": "error",
                "task": "strikeouts",
                "error": (
                    "no pitchers stored — statsapi schedule may lack probable starters "
                    "or per-pitcher build failed (see worker logs)"
                ),
                "pred_pitcher_rows": 0,
                "pitchers_built": built,
                "schedule": strikeout_schedule_diagnostics(),
                "build_stats": build_stats,
            }
        return {
            "status": "ok",
            "task": "strikeouts",
            "pred_pitcher_rows": count,
            "pitchers_built": built,
            "build_stats": build_stats,
        }
    finally:
        close_session()
