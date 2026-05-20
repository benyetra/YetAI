#!/usr/bin/env python3
import argparse
import sys
import logging
from datetime import datetime
import time
import pytz
import pandas as pd
import requests
import os

# ---- S3 Support ----
import boto3
from io import StringIO


def smart_to_csv(df, path, **kwargs):
    """Write CSV to S3 or local path transparently."""
    if path.startswith("s3://"):
        bucket = path.split("/")[2]
        key = "/".join(path.split("/")[3:])
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False, **kwargs)
        boto3.client("s3").put_object(
            Bucket=bucket, Key=key, Body=csv_buffer.getvalue()
        )
        print(f"✅ Wrote {len(df)} rows → s3://{bucket}/{key}")
    else:
        df.to_csv(path, index=False, **kwargs)
        print(f"✅ Wrote {len(df)} rows → {path}")


# -------------------

THIS_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, "../../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from app.services.etl.mlb.data.stadium_zipcode import stadium_to_zip
import statsapi


def get_weather_by_gametime(game_time, stadium):
    WEATHER_API_KEY = os.getenv("OPENWEATHER_KEY")
    if not WEATHER_API_KEY:
        logging.error("OPENWEATHER_KEY is not set in .env")
        return None

    zip_code = stadium_to_zip.get(stadium)
    if not zip_code:
        logging.error(f"Stadium '{stadium}' not found in stadium_to_zip mapping.")
        return None

    if isinstance(game_time, str):
        game_time_obj = datetime.strptime(game_time, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=pytz.UTC
        )
    else:
        game_time_obj = game_time

    game_hour_utc = game_time_obj.hour

    url = (
        f"https://api.tomorrow.io/v4/weather/forecast"
        f"?location={zip_code}&timesteps=1h"
        f"&apikey={WEATHER_API_KEY}&units=imperial"
    )
    response = requests.get(url, timeout=10)
    time.sleep(4)
    if response.status_code != 200:
        logging.error(
            f"Failed to fetch weather for {stadium} at {game_time}: {response.status_code}"
        )
        return None

    weather_data = response.json()
    if "timelines" not in weather_data or "hourly" not in weather_data["timelines"]:
        logging.error(
            f"Invalid data format for weather API response for {stadium} at {game_time}"
        )
        return None

    forecast = None
    for hourly in weather_data["timelines"]["hourly"]:
        ts = hourly["time"]
        forecast_time = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=pytz.UTC
        )
        if forecast_time.hour == game_hour_utc:
            forecast = hourly["values"]
            break

    if not forecast:
        logging.warning(
            f"No matching hour found in forecast for {stadium} at {game_time}"
        )
        return None

    return {
        "temperature": forecast.get("temperature", None),
        "wind_speed": forecast.get("windSpeed", None),
    }


def get_todays_games():
    today = datetime.today().date().strftime("%Y-%m-%d")
    schedule = statsapi.schedule(date=today)
    games = []
    for game in schedule:
        games.append(
            {
                "game_id": game.get("game_id"),
                "game_datetime": game.get("game_datetime"),
                "venue_name": game.get("venue_name"),
                "home_name": game.get("home_name"),
                "away_name": game.get("away_name"),
            }
        )
    return games


def build_weather_csv(output_path: str):
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s — %(levelname)s — %(message)s"
    )
    logging.info("Fetching today’s MLB schedule…")

    games = get_todays_games()
    if not games:
        logging.error("No games found for today—exiting.")
        sys.exit(1)

    results = []
    for g in games:
        venue = g["venue_name"]
        dt_str = g["game_datetime"]
        if not venue or not dt_str:
            continue

        try:
            game_time_utc = datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=pytz.UTC
            )
        except Exception as e:
            logging.warning(f"Could not parse game_datetime '{dt_str}': {e}")
            continue

        if venue not in stadium_to_zip:
            logging.warning(f"Venue '{venue}' not in stadium_to_zip mapping; skipping.")
            continue

        weather_data = get_weather_by_gametime(game_time_utc, venue)
        if not weather_data:
            logging.warning(f"No weather returned for {venue} at {game_time_utc}")
            continue

        row = {
            "park": venue,
            "date": game_time_utc.date(),
            "tavg": weather_data.get("temperature", None),
            "wspd": weather_data.get("wind_speed", None),
        }
        results.append(row)
        logging.info(f"Fetched weather for {venue} on {game_time_utc.date()}: {row}")

    if not results:
        logging.error("No weather rows collected—exiting.")
        sys.exit(1)

    df_out = pd.DataFrame(results)
    df_out["date"] = pd.to_datetime(df_out["date"]).dt.date
    df_out = df_out[["park", "date", "tavg", "wspd"]]
    df_out.drop_duplicates(subset=["park", "date"], inplace=True)
    smart_to_csv(df_out, output_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch today’s MLB weather (via Tomorrow.io) and write to CSV."
    )
    parser.add_argument(
        "--output",
        default="weather_raw.csv",
        help="Output filename (e.g. weather_raw.csv or s3://yetibets/weather_raw.csv).",
    )
    args = parser.parse_args()

    build_weather_csv(args.output)
