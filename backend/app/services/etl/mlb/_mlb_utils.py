"""Shared MLB helpers ported from YetiBets utilities.utilities_functions."""

from __future__ import annotations

import logging
import re
import unicodedata
from datetime import datetime
from io import BytesIO

import pandas as pd
import requests
import statsapi

from app.services.etl.mlb.data.special_characters_mapping import special_characters_mapping
from app.services.etl.mlb.data.stadium_zipcode import stadium_to_zip

logger = logging.getLogger(__name__)


def read_csv_anywhere(path: str, **kwargs) -> pd.DataFrame:
    if path.startswith("s3://"):
        import boto3

        parts = path.replace("s3://", "").split("/", 1)
        bucket, key = parts[0], parts[1]
        obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        return pd.read_csv(BytesIO(obj["Body"].read()), **kwargs)
    return pd.read_csv(path, **kwargs)


def replace_special_characters(name: str) -> str:
    normalized_name = unicodedata.normalize("NFC", name)
    return "".join(special_characters_mapping.get(char, char) for char in normalized_name)


def extract_numeric_value(fanduel_point_str: str) -> float | None:
    match = re.search(r"\d+(\.\d+)?", str(fanduel_point_str))
    return float(match.group(0)) if match else None


def get_weather_by_gametime(game_time, stadium: str):
    """Tomorrow.io hourly forecast for stadium zip (legacy YetiBets behavior)."""
    import os

    api_key = os.getenv("TOMORROW_IO_API_KEY") or os.getenv("WEATHER_API_KEY")
    if not api_key:
        logger.warning("No weather API key configured")
        return None
    zip_code = stadium_to_zip.get(stadium)
    if not zip_code:
        return None
    if isinstance(game_time, str):
        game_time_obj = datetime.strptime(game_time, "%Y-%m-%d %H:%M:%S")
    else:
        game_time_obj = game_time
    game_hour_utc = game_time_obj.hour
    url = (
        f"https://api.tomorrow.io/v4/weather/forecast?location={zip_code}"
        f"&timesteps=1h&apikey={api_key}&units=imperial"
    )
    response = requests.get(url, timeout=30)
    if response.status_code != 200:
        logger.error("Weather API error %s for zip %s", response.status_code, zip_code)
        return None
    weather_data = response.json()
    hourly = weather_data.get("timelines", {}).get("hourly", [])
    for entry in hourly:
        forecast_time = datetime.strptime(entry["time"], "%Y-%m-%dT%H:%M:%SZ")
        if forecast_time.hour == game_hour_utc:
            return entry["values"]
    return None


def convert_to_est(time_str: str, input_format: str = "%Y-%m-%dT%H:%M:%SZ") -> datetime:
    """Parse MLB statsapi game_datetime into naive local display time (legacy YetiBets)."""
    return datetime.strptime(time_str, input_format)


def isGameOver(game: dict) -> str:
    """Return 'future' or 'past' for slate filtering (ported from YetiBets utilities)."""
    est_time = convert_to_est(game["game_datetime"])
    return "future" if est_time > datetime.now() else "past"


def get_todays_games():
    today = datetime.today().date().strftime("%Y-%m-%d")
    schedule = statsapi.schedule(date=today)
    games = []
    for game in schedule:
        games.append(
            {
                "game_id": game["game_id"],
                "away_name": game["away_name"],
                "home_name": game["home_name"],
                "away_id": game["away_id"],
                "home_id": game["home_id"],
            }
        )
    return games
