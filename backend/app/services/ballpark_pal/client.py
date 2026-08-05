from __future__ import annotations

import logging
import time
from typing import Any

import requests

from app.services.ballpark_pal.config import (
    ballpark_pal_base_url,
    get_ballpark_pal_api_key,
)

logger = logging.getLogger(__name__)


class BallparkPalClient:
    def __init__(
        self,
        api_key: str | None = None,
        session: requests.Session | None = None,
        timeout: int = 30,
    ):
        self.api_key = api_key if api_key is not None else get_ballpark_pal_api_key()
        self._session = session or requests.Session()
        self.timeout = timeout
        self.base_url = ballpark_pal_base_url()

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        caller: str = "bpp",
    ) -> dict | None:
        if not self.api_key:
            logger.warning("BallparkPal skip %s: no API key", caller)
            return None
        url = f"{self.base_url}{path}"
        headers = {"X-API-Key": self.api_key, "Accept": "application/json"}
        try:
            resp = self._session.get(
                url, params=params or {}, headers=headers, timeout=self.timeout
            )
        except requests.RequestException as exc:
            logger.warning("BallparkPal network error caller=%s: %s", caller, exc)
            return None
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "2") or 2)
            time.sleep(min(retry_after, 10))
            try:
                resp = self._session.get(
                    url, params=params or {}, headers=headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                logger.warning("BallparkPal retry failed caller=%s: %s", caller, exc)
                return None
        if resp.status_code >= 400:
            req_id = None
            try:
                body = resp.json()
                req_id = (body.get("error") or {}).get("requestId")
            except Exception:
                body = None
            logger.warning(
                "BallparkPal HTTP %s caller=%s requestId=%s",
                resp.status_code,
                caller,
                req_id,
            )
            return None
        try:
            body = resp.json()
        except ValueError:
            logger.warning("BallparkPal invalid JSON caller=%s", caller)
            return None
        if "error" in body:
            logger.warning(
                "BallparkPal error envelope caller=%s: %s",
                caller,
                body.get("error"),
            )
            return None
        return body.get("data", body)

    def games(self, date: str) -> dict | None:
        return self.get("/games", {"date": date}, caller="bpp.games")

    def projections_averages(self, game_id: int) -> dict | None:
        return self.get(
            "/projections/averages",
            {"gameId": game_id},
            caller="bpp.averages",
        )

    def projections_probabilities(self, game_id: int) -> dict | None:
        return self.get(
            "/projections/probabilities",
            {"gameId": game_id},
            caller="bpp.probs",
        )

    def parkfactors(self, date: str) -> dict | None:
        return self.get("/parkfactors", {"date": date}, caller="bpp.parkfactors")

    def parkfactors_hitters(
        self, *, date: str | None = None, game_id: int | None = None
    ) -> dict | None:
        params: dict[str, Any] = {}
        if date:
            params["date"] = date
        if game_id is not None:
            params["gameId"] = game_id
        return self.get("/parkfactors/hitters", params, caller="bpp.pf_hitters")

    def matchups(self, date: str, *, starters: bool = True) -> dict | None:
        params: dict[str, Any] = {"date": date}
        if starters:
            params["starters"] = "true"
        return self.get("/matchups", params, caller="bpp.matchups")
