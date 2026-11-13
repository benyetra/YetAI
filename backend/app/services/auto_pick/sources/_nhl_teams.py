"""NHL team id -> full name for the NHL sources.

The NHL ETL stores place names ("Boston", "New York"); "New York" and "Los Angeles"
are ambiguous, so resolve by the NHL team id the same rows carry.
"""

from functools import lru_cache
from typing import Optional


@lru_cache(maxsize=1)
def _by_id() -> dict[int, str]:
    from app.services.etl.nhl.collect_historical_data import NHL_TEAMS

    names = {t["id"]: t["name"] for t in NHL_TEAMS.values()}
    # ESPN's displayName (what the grader matches) is "Utah Mammoth"; the ETL map
    # still says "Utah Hockey Club". 68 is the id some NHL endpoints return.
    names[59] = names[68] = "Utah Mammoth"
    return names


def nhl_full_name(team_id: Optional[int]) -> Optional[str]:
    return _by_id().get(team_id) if team_id is not None else None
