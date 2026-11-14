"""Shared S3 model store: refreshing loader, champion-gated upload, rollback.

Loaders used to download once per process and cache forever (and, on any
failure, give up for good), so a weekly retrain never reached a running
worker. Uploads overwrote the live model without checking it was better.

* ``S3Object``: in-memory object that re-checks S3 (ETag) at most once per
  ``REFRESH_SECONDS``, reloads on change, and keeps the last good object when
  S3 or the deserializer fails.
* ``gated_upload``: score the live model on the candidate's holdout, refuse a
  candidate that is not strictly better or whose data window is unchanged, archive the live objects, then write the new ones plus a
  manifest (``<model>_manifest.json``) carrying the version tag.
* ``rollback``: restore an archived set (itself archived first, so undoable).
  CLI: ``backend/scripts/ml_model_rollback.py``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

BUCKET = "yetibets"
REFRESH_SECONDS = int(os.getenv("ML_MODEL_REFRESH_SECONDS", "3600"))
# After a failed refresh, retry this soon instead of waiting a full interval.
RETRY_BACKOFF_SECONDS = 60
# The loader sits on pipeline paths: fail fast instead of boto3's 60s defaults.
_LOADER_S3_CONFIG = Config(
    connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 2}
)
MAX_VERSION_LEN = 20


def manifest_key(model_key: str) -> str:
    """``nba/ml_models/xgb_points.pkl`` -> ``nba/ml_models/xgb_points_manifest.json``."""
    return f"{model_key.rsplit('.', 1)[0]}_manifest.json"


def _is_missing(exc: Exception) -> bool:
    err = getattr(exc, "response", {}).get("Error", {}).get("Code")
    return err in ("NoSuchKey", "404", "NotFound")


def get_bytes(s3, bucket: str, key: str) -> bytes | None:
    """Object body, or None when the key does not exist."""
    try:
        return s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception as exc:
        if _is_missing(exc):
            return None
        raise


class S3Object:
    """Lazily loaded, periodically refreshed S3 object (see module docstring)."""

    def __init__(
        self,
        key: str,
        deserialize: Callable[[bytes], Any],
        *,
        bucket: str = BUCKET,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.key = key
        self.bucket = bucket
        self._deserialize = deserialize
        self._clock = clock
        self._lock = threading.Lock()
        self._obj: Any = None
        self._token: tuple | None = None
        self._checked: float | None = None
        self._last_ok = False
        self.manifest: dict | None = None

    @property
    def version(self) -> str | None:
        v = (self.manifest or {}).get("version")
        return str(v) if v else None

    def get(self) -> Any:
        """Last good object (None until a load has succeeded)."""
        with self._lock:
            now = self._clock()
            wait = REFRESH_SECONDS if self._last_ok else min(RETRY_BACKOFF_SECONDS, REFRESH_SECONDS)
            if self._checked is not None and now - self._checked < wait:
                return self._obj
            # Stamp first so concurrent callers do not all hit S3 on a slow refresh.
            self._checked = now
            try:
                self._refresh()
                self._last_ok = True
            except Exception as exc:
                self._last_ok = False
                logger.warning(
                    "model refresh failed for s3://%s/%s (keeping %s): %s",
                    self.bucket,
                    self.key,
                    "last good copy" if self._obj is not None else "nothing",
                    exc,
                )
            return self._obj

    def _refresh(self) -> None:
        """Object + manifest are one unit: swap both in only when both loaded.

        The change token is (object ETag, manifest ETag or None): a model written
        by a path that writes no manifest (manual upload, older workflow) is still
        noticed, and a manifest landing after the model is too.
        """
        s3 = boto3.client("s3", config=_LOADER_S3_CONFIG)
        mkey = manifest_key(self.key)
        m_token = self._head_token(s3, mkey)
        token = (self._head_token(s3, self.key), m_token)
        if self._obj is not None and token == self._token:
            return
        manifest = None
        if m_token:
            raw = get_bytes(s3, self.bucket, mkey)
            if raw is None:
                raise RuntimeError("manifest vanished mid-refresh")
            manifest = json.loads(raw)
        body = get_bytes(s3, self.bucket, self.key)
        if body is None:
            raise RuntimeError("object missing")
        self._obj, self._token, self.manifest = self._deserialize(body), token, manifest
        logger.info("loaded s3://%s/%s (version=%s)", self.bucket, self.key, self.version)

    def _head_token(self, s3, key: str) -> str | None:
        """ETag/LastModified, or None when the key does not exist."""
        try:
            head = s3.head_object(Bucket=self.bucket, Key=key)
        except Exception as exc:
            if _is_missing(exc):
                if key == self.key:
                    raise
                return None
            raise
        return str(head.get("ETag") or head.get("LastModified"))


def _dir(key: str) -> str:
    return key.rsplit("/", 1)[0] if "/" in key else ""


def _join(prefix: str, name: str) -> str:
    return f"{prefix}/{name}" if prefix else name


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")


def _copy(s3, bucket: str, src: str, dst: str) -> bool:
    """Copy within the bucket; False when the source does not exist."""
    try:
        s3.copy_object(
            Bucket=bucket, Key=dst, CopySource={"Bucket": bucket, "Key": src}
        )
        return True
    except Exception as exc:
        if _is_missing(exc):
            return False
        raise


def _not_better(candidate: float, champion: float, lower_is_better: bool) -> bool:
    """A tie is not better: re-shipping an equal model only fragments versions."""
    return candidate >= champion if lower_is_better else candidate <= champion


def gated_upload(
    model_key: str,
    body: bytes,
    *,
    candidate_metric: float,
    metric_name: str,
    score_champion: Callable[[bytes], float],
    lower_is_better: bool = True,
    extra_files: dict[str, bytes] | None = None,
    manifest_extra: dict[str, Any] | None = None,
    version_prefix: str = "xgb",
    bucket: str = BUCKET,
) -> dict[str, Any]:
    """Upload ``body`` only if it is strictly better than the live model and was
    trained on a different data window (``manifest_extra["data_window"]``, when
    both the live manifest and the candidate carry one).

    ``score_champion(live_body)`` scores the live model on the CANDIDATE's
    holdout (same rows, same metric). If it raises, the live manifest's
    ``holdout_metric`` is used; with neither, the upload proceeds with
    ``champion_metric=None`` and a reason. ``extra_files`` maps basename ->
    bytes written next to the model (e.g. the metadata JSON).
    """
    s3 = boto3.client("s3")
    prefix = _dir(model_key)
    extras = dict(extra_files or {})
    mkey = manifest_key(model_key)

    live = get_bytes(s3, bucket, model_key)
    champion: float | None = None
    reason: str | None = None
    window = (manifest_extra or {}).get("data_window")
    live_manifest: dict[str, Any] = {}
    if live is not None:
        try:
            raw = get_bytes(s3, bucket, mkey)
            live_manifest = json.loads(raw) if raw else {}
        except Exception:
            live_manifest = {}
    if window and live_manifest.get("data_window") == window:
        logger.warning("skipped %s: data window %s unchanged", model_key, window)
        return {
            "status": "rejected_by_champion",
            "reason": "unchanged_data_window",
            "data_window": window,
            "metric_name": metric_name,
            "candidate_metric": candidate_metric,
        }
    if live is None:
        status = "first_upload"
    else:
        status = "uploaded"
        try:
            champion = float(score_champion(live))
        except Exception as exc:
            logger.warning("could not score live %s on the holdout: %s", model_key, exc)
            try:
                champion = float(live_manifest["holdout_metric"])
            except Exception:
                champion = None
            reason = (
                "champion_unscorable_used_manifest_metric"
                if champion is not None
                else "champion_unscorable"
            )

    if champion is not None and _not_better(candidate_metric, champion, lower_is_better):
        logger.warning(
            "rejected %s: candidate %s=%.4f not better than champion %.4f",
            model_key,
            metric_name,
            candidate_metric,
            champion,
        )
        return {
            "status": "rejected_by_champion",
            "metric_name": metric_name,
            "candidate_metric": candidate_metric,
            "champion_metric": champion,
        }

    now = datetime.now(timezone.utc)
    stamp = _utc_stamp()
    archive_stamp = None
    if live is not None:
        archive_stamp = stamp
        for name in (model_key.rsplit("/", 1)[-1], *extras, mkey.rsplit("/", 1)[-1]):
            _copy(
                s3,
                bucket,
                _join(prefix, name),
                _join(_join(prefix, f"archive/{stamp}"), name),
            )

    version = f"{version_prefix[: MAX_VERSION_LEN - 13]}-{now:%Y%m%d%H%M}"
    manifest = {
        **(manifest_extra or {}),
        "version": version,
        "trained_at": now.isoformat(),
        "metric_name": metric_name,
        "holdout_metric": candidate_metric,
        "champion_metric": champion,
        "archive_stamp": archive_stamp,
        "gate_reason": reason,
    }
    keys = {"model_key": model_key, "manifest_key": mkey}
    s3.put_object(Bucket=bucket, Key=model_key, Body=body)
    for name, data in extras.items():
        s3.put_object(Bucket=bucket, Key=_join(prefix, name), Body=data)
    s3.put_object(
        Bucket=bucket, Key=mkey, Body=json.dumps(manifest, default=str).encode()
    )
    logger.info("uploaded %s (%s, version=%s)", model_key, status, version)
    return {
        "status": status,
        **keys,
        "version": version,
        "archive_stamp": archive_stamp,
        "metric_name": metric_name,
        "candidate_metric": candidate_metric,
        "champion_metric": champion,
        "reason": reason,
    }


def list_archive_stamps(model_key: str, *, bucket: str = BUCKET) -> list[str]:
    """Archive stamps holding a copy of ``model_key``, oldest first.

    ``archive/`` is shared by every model in the directory, so a stamp may
    belong only to a sibling model."""
    s3 = boto3.client("s3")
    prefix = _join(_dir(model_key), "archive/")
    out: list[str] = []
    kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix, "Delimiter": "/"}
    while True:
        page = s3.list_objects_v2(**kwargs)
        out += [
            p["Prefix"][len(prefix) :].strip("/") for p in page.get("CommonPrefixes", [])
        ]
        if not page.get("IsTruncated"):
            break
        kwargs["ContinuationToken"] = page["NextContinuationToken"]
    name = model_key.rsplit("/", 1)[-1]
    holding = []
    for stamp in sorted(out):
        try:
            s3.head_object(Bucket=bucket, Key=f"{prefix}{stamp}/{name}")
            holding.append(stamp)
        except Exception as exc:
            if not _is_missing(exc):
                raise
    return holding


def rollback(
    model_key: str,
    stamp: str,
    *,
    extra_basenames: tuple[str, ...] = (),
    dry_run: bool = True,
    bucket: str = BUCKET,
) -> dict[str, Any]:
    """Restore the archived model (+ extras + manifest) over the live keys.

    The current live objects are archived first under a fresh stamp, so a
    rollback can itself be rolled back. Dry run (default) only reports.
    """
    s3 = boto3.client("s3")
    prefix = _dir(model_key)
    arch = _join(prefix, f"archive/{stamp}")
    names = [
        model_key.rsplit("/", 1)[-1],
        *extra_basenames,
        manifest_key(model_key).rsplit("/", 1)[-1],
    ]
    present = []
    for name in names:
        try:
            s3.head_object(Bucket=bucket, Key=_join(arch, name))
            present.append(name)
        except Exception as exc:
            if not _is_missing(exc):
                raise
    if names[0] not in present:
        raise ValueError(f"no archived model for stamp {stamp!r} under {arch}/")
    result: dict[str, Any] = {
        "status": "dry_run" if dry_run else "rolled_back",
        "stamp": stamp,
        "restores": [_join(prefix, n) for n in present],
    }
    if dry_run:
        return result
    current = _utc_stamp()
    current_arch = _join(prefix, f"archive/{current}")
    for name in present:
        _copy(s3, bucket, _join(prefix, name), _join(current_arch, name))
    for name in present:
        _copy(s3, bucket, _join(arch, name), _join(prefix, name))
    # A model archived before manifests existed has none: drop the live one so
    # the restored model is not stamped with the replaced model's version.
    mname = names[-1]
    if mname not in present:
        _copy(s3, bucket, _join(prefix, mname), _join(current_arch, mname))
        s3.delete_object(Bucket=bucket, Key=_join(prefix, mname))
    result["archived_current_as"] = current
    logger.info("rolled %s back to %s (previous live: %s)", model_key, stamp, current)
    return result
