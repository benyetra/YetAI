"""Refreshing S3 loader shared by the NHL goalie / player-shots / team-totals models.

The old per-module loader downloaded to a temp dir once per process and, on any
failure, never tried again. ``ModelPair`` rides on ``S3Object`` (ETag re-check at
most hourly, keeps the last good copy, no sticky failure). A ``*_MODEL_LOCAL``
directory still wins and is read once (dev / tests).
"""

from __future__ import annotations

import json
import logging
import os
import pickle  # nosec B403 - artifacts from our own private bucket
from pathlib import Path
from typing import Any

from app.services.ml.model_store import S3Object

logger = logging.getLogger(__name__)


class ModelPair:
    def __init__(self, prefix: str, key: str, local_env: str):
        self._local_env = local_env
        self._key = key
        self._local: tuple[Any, dict] | None = None
        self._local_failed = False
        self._objs = (
            S3Object(f"{prefix}/{key}.pkl", pickle.loads),  # nosec B301
            S3Object(f"{prefix}/{key}_metadata.json", json.loads),
        )

    def get(self) -> tuple[Any, dict] | None:
        """(model, metadata) or None when no usable model is available."""
        base = os.getenv(self._local_env, "").strip()
        if base:
            return self._get_local(Path(base))
        model, meta = (o.get() for o in self._objs)
        if model is None or meta is None:
            return None
        return model, meta

    def _get_local(self, root: Path) -> tuple[Any, dict] | None:
        if self._local is None and not self._local_failed:
            try:
                with (root / f"{self._key}.pkl").open("rb") as f:
                    model = pickle.load(f)  # nosec B301
                meta = json.loads((root / f"{self._key}_metadata.json").read_text())
                self._local = (model, meta)
            except Exception as exc:
                logger.info("%s unavailable under %s: %s", self._key, root, exc)
                self._local_failed = True
        return self._local
