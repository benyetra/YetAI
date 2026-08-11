"""Light GBM residual/calibration on hierarchical anytime-TD probabilities.

Hierarchical λ → P is the primary model. When a calibrated artifact is present
(or a model is injected), a HistGradientBoostingClassifier maps hierarchical
probability + usage/RZ features → calibrated P(anytime TD).
"""

from __future__ import annotations

import json
import logging
import os
import pickle  # nosec B403 - artifacts written by our own train script
import threading
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.etl.nfl.anytime_td_model import (
    anytime_td_probability,
    expected_tds,
)

logger = logging.getLogger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_MODEL_PATH = BACKEND_ROOT / "models" / "nfl" / "anytime_td_residual_gbm.pkl"
DEFAULT_META_PATH = BACKEND_ROOT / "models" / "nfl" / "anytime_td_residual_gbm.json"

MODEL_VERSION_HIER = "hierarchical_v1"
MODEL_VERSION_GBM = "hierarchical_v1_gbm_pos"

CALIBRATION_FEATURE_NAMES: tuple[str, ...] = (
    "hier_p",
    "expected_tds",
    "team_rz_trips",
    "player_rz_share",
    "conversion_rate",
    "defense_mult",
    "weather_mult",
    "script_mult",
    "snap_pct",
    "rz_targets",
    "gl_carries",
    "is_qb",
    "is_rb",
    "is_wr",
    "is_te",
)

# Position groups: RB (goal-line), WR+TE (pass catchers), QB (light).
CALIBRATION_GROUPS: tuple[str, ...] = ("rb", "pass", "qb")
_MIN_TRAIN_ROWS = 80
_MIN_TRAIN_ROWS_BY_GROUP: dict[str, int] = {"rb": 80, "pass": 80, "qb": 40}
_TRUTHY = frozenset({"1", "true", "yes", "on"})

_MODEL: Any | None = None
_METADATA: dict[str, Any] | None = None
_LOAD_FAILED = False
_LOCK = threading.Lock()


def calibration_group_for_position(position: str | None) -> str:
    pos = str(position or "").strip().upper()
    if pos == "RB":
        return "rb"
    if pos == "QB":
        return "qb"
    return "pass"


def calibration_enabled() -> bool:
    """GBM calibration on unless explicitly disabled via NFL_ANYTIME_TD_GBM=0."""
    raw = os.getenv("NFL_ANYTIME_TD_GBM", "1").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return raw in _TRUTHY or raw == ""


def hierarchical_probability(
    *,
    team_rz_trips: float,
    player_rz_share: float,
    conversion_rate: float,
    defense_mult: float = 1.0,
    weather_mult: float = 1.0,
    script_mult: float = 1.0,
) -> float:
    lam = expected_tds(
        team_rz_trips=team_rz_trips,
        player_rz_share=player_rz_share,
        conversion_rate=conversion_rate,
        defense_mult=defense_mult,
        weather_mult=weather_mult,
        script_mult=script_mult,
    )
    return float(anytime_td_probability(lam))


def _float(row: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    value = row.get(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_calibration_feature_vector(row: Mapping[str, Any]) -> list[float]:
    """Build ordered feature vector for residual GBM (includes hierarchical P)."""
    pos = str(row.get("position") or "").strip().upper()
    hier_p = row.get("td_probability")
    if hier_p is None:
        hier_p = hierarchical_probability(
            team_rz_trips=_float(row, "team_rz_trips", 3.2),
            player_rz_share=_float(row, "player_rz_share", 0.15),
            conversion_rate=_float(row, "conversion_rate", 0.25),
            defense_mult=_float(row, "defense_mult", 1.0),
            weather_mult=_float(row, "weather_mult", 1.0),
            script_mult=_float(row, "script_mult", 1.0),
        )
    expected = row.get("expected_tds")
    if expected is None:
        expected = expected_tds(
            team_rz_trips=_float(row, "team_rz_trips", 3.2),
            player_rz_share=_float(row, "player_rz_share", 0.15),
            conversion_rate=_float(row, "conversion_rate", 0.25),
            defense_mult=_float(row, "defense_mult", 1.0),
            weather_mult=_float(row, "weather_mult", 1.0),
            script_mult=_float(row, "script_mult", 1.0),
        )
    values = {
        "hier_p": float(hier_p),
        "expected_tds": float(expected),
        "team_rz_trips": _float(row, "team_rz_trips", 3.2),
        "player_rz_share": _float(row, "player_rz_share", 0.15),
        "conversion_rate": _float(row, "conversion_rate", 0.25),
        "defense_mult": _float(row, "defense_mult", 1.0),
        "weather_mult": _float(row, "weather_mult", 1.0),
        "script_mult": _float(row, "script_mult", 1.0),
        "snap_pct": _float(row, "snap_pct", 0.55),
        "rz_targets": _float(row, "rz_targets", 0.0),
        "gl_carries": _float(row, "gl_carries", 0.0),
        "is_qb": 1.0 if pos == "QB" else 0.0,
        "is_rb": 1.0 if pos == "RB" else 0.0,
        "is_wr": 1.0 if pos == "WR" else 0.0,
        "is_te": 1.0 if pos == "TE" else 0.0,
    }
    return [float(values[name]) for name in CALIBRATION_FEATURE_NAMES]


def fit_residual_gbm(
    rows: Sequence[Mapping[str, Any]],
    *,
    random_state: int = 42,
    min_rows: int = _MIN_TRAIN_ROWS,
) -> Any | None:
    """Fit HistGradientBoostingClassifier on hierarchical residuals features."""
    if len(rows) < min_rows:
        return None
    try:
        import numpy as np
        from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore
    except ImportError:
        logger.warning("sklearn unavailable; skipping anytime-TD GBM calibration")
        return None

    X = np.asarray([build_calibration_feature_vector(r) for r in rows], dtype=float)
    y = np.asarray([1 if r.get("scored_anytime_td") else 0 for r in rows], dtype=int)
    if y.min() == y.max():
        return None

    model = HistGradientBoostingClassifier(
        max_depth=4,
        learning_rate=0.08,
        max_iter=120,
        l2_regularization=0.1,
        random_state=random_state,
    )
    model.fit(X, y)
    return model


def fit_position_gbm_bundle(
    rows: Sequence[Mapping[str, Any]],
    *,
    random_state: int = 42,
    min_rows: Mapping[str, int] | None = None,
) -> dict[str, Any] | None:
    """Fit separate GBMs for rb / pass (WR+TE) / qb. Returns None if none fit."""
    caps = dict(_MIN_TRAIN_ROWS_BY_GROUP)
    if min_rows:
        caps.update({k: int(v) for k, v in min_rows.items()})
    by_group: dict[str, list[Mapping[str, Any]]] = {g: [] for g in CALIBRATION_GROUPS}
    for row in rows:
        by_group[calibration_group_for_position(str(row.get("position") or ""))].append(
            row
        )

    models: dict[str, Any] = {}
    for group, group_rows in by_group.items():
        # QB light: shallower tree / fewer iters when data is thin.
        if group == "qb":
            fitted = _fit_gbm_with_hyperparams(
                group_rows,
                random_state=random_state,
                min_rows=caps.get(group, 40),
                max_depth=3,
                max_iter=80,
            )
        else:
            fitted = fit_residual_gbm(
                group_rows,
                random_state=random_state,
                min_rows=caps.get(group, _MIN_TRAIN_ROWS),
            )
        if fitted is not None:
            models[group] = fitted
            logger.info("anytime-TD GBM group=%s n=%s fitted", group, len(group_rows))
        else:
            logger.info(
                "anytime-TD GBM group=%s n=%s skipped (insufficient)",
                group,
                len(group_rows),
            )
    return models or None


def _fit_gbm_with_hyperparams(
    rows: Sequence[Mapping[str, Any]],
    *,
    random_state: int,
    min_rows: int,
    max_depth: int,
    max_iter: int,
) -> Any | None:
    if len(rows) < min_rows:
        return None
    try:
        import numpy as np
        from sklearn.ensemble import HistGradientBoostingClassifier  # type: ignore
    except ImportError:
        return None
    X = np.asarray([build_calibration_feature_vector(r) for r in rows], dtype=float)
    y = np.asarray([1 if r.get("scored_anytime_td") else 0 for r in rows], dtype=int)
    if y.min() == y.max():
        return None
    model = HistGradientBoostingClassifier(
        max_depth=max_depth,
        learning_rate=0.08,
        max_iter=max_iter,
        l2_regularization=0.1,
        random_state=random_state,
    )
    model.fit(X, y)
    return model


def model_for_row(row: Mapping[str, Any], model_or_bundle: Any | None) -> Any | None:
    """Resolve per-position model from a bundle or legacy single estimator."""
    if model_or_bundle is None:
        return None
    if isinstance(model_or_bundle, dict):
        group = calibration_group_for_position(str(row.get("position") or ""))
        return model_or_bundle.get(group) or model_or_bundle.get("pass")
    return model_or_bundle


def apply_calibrated_probability(
    row: Mapping[str, Any],
    *,
    model: Any | None = None,
) -> float:
    """Return calibrated P(anytime) when ``model`` is set; else hierarchical P.

    ``model`` may be a single estimator or a position-group bundle dict.
    """
    hier = row.get("td_probability")
    if hier is None:
        hier = hierarchical_probability(
            team_rz_trips=_float(row, "team_rz_trips", 3.2),
            player_rz_share=_float(row, "player_rz_share", 0.15),
            conversion_rate=_float(row, "conversion_rate", 0.25),
            defense_mult=_float(row, "defense_mult", 1.0),
            weather_mult=_float(row, "weather_mult", 1.0),
            script_mult=_float(row, "script_mult", 1.0),
        )
    hier_f = float(hier)
    estimator = model_for_row(row, model)
    if estimator is None:
        return min(1.0, max(0.0, hier_f))

    try:
        import numpy as np

        vec = np.asarray([build_calibration_feature_vector(row)], dtype=float)
        if hasattr(estimator, "predict_proba"):
            proba = estimator.predict_proba(vec)[0]
            if len(proba) == 1:
                p = float(proba[0])
            else:
                classes = list(getattr(estimator, "classes_", [0, 1]))
                idx = classes.index(1) if 1 in classes else -1
                p = float(proba[idx])
        else:
            p = float(estimator.predict(vec)[0])
        # Shrink toward hierarchical so calibration doesn't scramble board ranking.
        blended = 0.55 * float(p) + 0.45 * hier_f
        return min(1.0, max(0.0, blended))
    except Exception as exc:
        logger.info("anytime-TD GBM predict failed; using hierarchical: %s", exc)
        return min(1.0, max(0.0, hier_f))


def save_calibration_artifact(
    model: Any,
    *,
    metadata: Mapping[str, Any] | None = None,
    model_path: str | Path | None = None,
    meta_path: str | Path | None = None,
) -> tuple[Path, Path]:
    mpath = Path(model_path or DEFAULT_MODEL_PATH)
    jpath = Path(meta_path or DEFAULT_META_PATH)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    with mpath.open("wb") as f:
        pickle.dump(model, f)
    payload = {
        "model_version": MODEL_VERSION_GBM,
        "features": list(CALIBRATION_FEATURE_NAMES),
        "groups": (
            sorted(model.keys()) if isinstance(model, dict) else ["legacy_single"]
        ),
        **dict(metadata or {}),
    }
    jpath.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return mpath, jpath


def load_calibration_model(
    *,
    model_path: str | Path | None = None,
    force: bool = False,
) -> Any | None:
    """Load pickled calibrator from disk (cached)."""
    global _MODEL, _METADATA, _LOAD_FAILED
    if not force and _MODEL is not None:
        return _MODEL
    if not force and _LOAD_FAILED:
        return None
    with _LOCK:
        if not force and _MODEL is not None:
            return _MODEL
        if not force and _LOAD_FAILED:
            return None
        path = Path(model_path or DEFAULT_MODEL_PATH)
        try:
            with path.open("rb") as f:
                _MODEL = pickle.load(f)  # nosec B301
            meta_path = Path(DEFAULT_META_PATH)
            if meta_path.is_file():
                _METADATA = json.loads(meta_path.read_text(encoding="utf-8"))
            else:
                _METADATA = {"model_version": MODEL_VERSION_GBM}
            _LOAD_FAILED = False
            return _MODEL
        except Exception as exc:
            logger.info("anytime-TD residual GBM unavailable: %s", exc)
            _LOAD_FAILED = True
            _MODEL = None
            _METADATA = None
            return None


def resolve_model_version(*, gbm_applied: bool) -> str:
    return MODEL_VERSION_GBM if gbm_applied else MODEL_VERSION_HIER


def calibrate_prediction_row(row: Mapping[str, Any]) -> tuple[float, bool]:
    """Apply loaded GBM when enabled; returns (probability, gbm_applied)."""
    hier = hierarchical_probability(
        team_rz_trips=_float(row, "team_rz_trips", 3.2),
        player_rz_share=_float(row, "player_rz_share", 0.15),
        conversion_rate=_float(row, "conversion_rate", 0.25),
        defense_mult=_float(row, "defense_mult", 1.0),
        weather_mult=_float(row, "weather_mult", 1.0),
        script_mult=_float(row, "script_mult", 1.0),
    )
    enriched = dict(row)
    enriched["td_probability"] = hier
    if not calibration_enabled():
        return hier, False
    bundle = load_calibration_model()
    if bundle is None:
        return hier, False
    estimator = model_for_row(enriched, bundle)
    if estimator is None:
        return hier, False
    return apply_calibrated_probability(enriched, model=bundle), True
