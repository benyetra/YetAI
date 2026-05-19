"""Refresh pred_weather from pitcher/hitter game times (ported from YetiBets weather.py)."""

from __future__ import annotations

import logging

from app.models.predictions_models import Hitter, Pitcher, Weather
from app.services.etl.mlb._db import db_session
from app.services.etl.mlb._mlb_utils import get_weather_by_gametime
from app.services.etl.mlb.data.stadium_zipcode import stadium_to_zip

logger = logging.getLogger(__name__)


def _fetch_game_times() -> dict:
    game_times = {}
    for pitcher in db_session.query(Pitcher).all():
        game_times[pitcher.venue_name] = pitcher.game_time
    for batter in db_session.query(Hitter).all():
        game_times[batter.venue_name] = batter.game_time
    return game_times


def store_weather_data() -> int:
    """Upsert weather rows for venues with scheduled games today."""
    db_session.query(Weather).delete()
    db_session.commit()
    stored = 0
    game_times = _fetch_game_times()
    for stadium in stadium_to_zip:
        if stadium not in game_times:
            continue
        game_time = game_times[stadium]
        weather_data = get_weather_by_gametime(game_time, stadium)
        if not weather_data:
            logger.warning("No weather data for %s", stadium)
            continue
        db_session.add(
            Weather(
                stadium=stadium,
                game_time=game_time,
                weather_code=str(weather_data.get("weatherCode", "")),
                temperature=float(weather_data.get("temperature", 0) or 0),
                wind_speed=float(weather_data.get("windSpeed", 0) or 0),
                wind_direction=str(weather_data.get("windDirection", "")),
                humidity=float(weather_data.get("humidity", 0) or 0),
                venue_name=stadium,
                precipitation_probability=float(
                    weather_data.get("precipitationProbability", 0) or 0
                ),
                rain_intensity=float(weather_data.get("rainIntensity", 0) or 0),
            )
        )
        stored += 1
    db_session.commit()
    return stored


def run() -> dict:
    from app.services.etl.mlb._db import close_session, init_session

    init_session()
    try:
        n = store_weather_data()
        return {"status": "ok", "task": "weather", "rows": n}
    finally:
        close_session()
