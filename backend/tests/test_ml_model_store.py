"""model_store: refreshing S3Object, champion-gated upload, rollback."""

from __future__ import annotations

import json

import pytest

from app.services.ml import model_store as ms
from tests.fake_s3 import FakeS3

KEY = "nba/ml_models/xgb_points.pkl"
META = "nba/ml_models/xgb_points_metadata.json"
MAN = "nba/ml_models/xgb_points_manifest.json"


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(ms.boto3, "client", lambda *_a, **_k: fake)
    monkeypatch.setattr(ms, "REFRESH_SECONDS", 0)  # recheck on every get()
    return fake


def _obj():
    return ms.S3Object(KEY, lambda b: b.decode())


def test_changed_etag_is_served_without_restart(s3):
    s3.put(KEY, b"old", "e1")
    o = _obj()
    assert o.get() == "old"
    s3.put(KEY, b"new", "e2")
    assert o.get() == "new"


def test_unchanged_etag_does_not_redownload(s3):
    s3.put(KEY, b"old", "e1")
    o = _obj()
    o.get()
    o.get()
    assert len(s3.names("get")) == 1  # body, first load only


def test_no_recheck_inside_the_refresh_interval(s3, monkeypatch):
    monkeypatch.setattr(ms, "REFRESH_SECONDS", 3600)
    s3.put(KEY, b"old", "e1")
    t = [0.0]
    o = ms.S3Object(KEY, lambda b: b.decode(), clock=lambda: t[0])
    o.get()
    s3.put(KEY, b"new", "e2")
    t[0] = 100
    assert o.get() == "old"
    t[0] = 3601
    assert o.get() == "new"


def test_s3_error_keeps_last_good_then_recovers(s3):
    s3.put(KEY, b"good", "e1")
    o = _obj()
    assert o.get() == "good"
    s3.fail_head = True
    assert o.get() == "good"
    s3.fail_head = False
    s3.put(KEY, b"better", "e2")
    assert o.get() == "better"


def test_corrupt_body_keeps_last_good_then_recovers(s3):
    def parse(b):
        if b == b"corrupt":
            raise ValueError("bad pickle")
        return b.decode()

    s3.put(KEY, b"good", "e1")
    o = ms.S3Object(KEY, parse)
    assert o.get() == "good"
    s3.put(KEY, b"corrupt", "e2")
    assert o.get() == "good"
    s3.put(KEY, b"fixed", "e3")
    assert o.get() == "fixed"


def test_first_load_failure_retries_after_backoff_not_full_interval(s3, monkeypatch):
    monkeypatch.setattr(ms, "REFRESH_SECONDS", 3600)  # the real interval
    t = [0.0]
    o = ms.S3Object(KEY, lambda b: b.decode(), clock=lambda: t[0])
    assert o.get() is None  # nothing in S3 yet
    s3.put(KEY, b"arrived", "e1")
    t[0] = ms.RETRY_BACKOFF_SECONDS / 2
    assert o.get() is None  # still inside the backoff: no hammering S3
    t[0] = ms.RETRY_BACKOFF_SECONDS + 1
    assert o.get() == "arrived"  # picked up long before REFRESH_SECONDS
    assert ms.RETRY_BACKOFF_SECONDS < 3600


def test_manifest_is_reread_each_interval_even_if_model_etag_same(s3):
    s3.put(KEY, b"m", "e1")
    s3.put(MAN, json.dumps({"version": "xgb-1"}).encode(), "e1")
    o = _obj()
    o.get()
    assert o.version == "xgb-1"
    s3.put(MAN, json.dumps({"version": "xgb-2"}).encode(), "e2")  # upload raced
    o.get()
    assert o.version == "xgb-2"


def test_model_overwritten_without_a_manifest_change_is_reloaded(s3):
    s3.put(KEY, b"m1", "e1")
    s3.put(MAN, json.dumps({"version": "xgb-1"}).encode(), "e1")
    o = _obj()
    assert o.get() == "m1"
    s3.put(KEY, b"m2", "e2")  # manual upload: manifest untouched
    assert o.get() == "m2"


def test_unreadable_manifest_keeps_last_good_set(s3):
    s3.put(KEY, b"m", "e1")
    s3.put(MAN, json.dumps({"version": "xgb-1"}).encode(), "e1")
    o = _obj()
    o.get()
    s3.put(KEY, b"m2", "e2")
    s3.put(MAN, b"{not json", "e2")
    assert o.get() == "m" and o.version == "xgb-1"  # no new model with old stamp


def test_failed_refresh_retries_on_short_backoff(s3, monkeypatch):
    monkeypatch.setattr(ms, "REFRESH_SECONDS", 3600)
    t = [0.0]
    s3.put(KEY, b"good", "e1")
    o = ms.S3Object(KEY, lambda b: b.decode(), clock=lambda: t[0])
    assert o.get() == "good"
    t[0] = 3601
    s3.fail_head = True
    o.get()
    s3.fail_head = False
    s3.put(KEY, b"better", "e2")
    t[0] = 3601 + ms.RETRY_BACKOFF_SECONDS + 1
    assert o.get() == "better"


def test_loader_s3_client_has_short_timeouts_and_two_attempts(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        ms.boto3, "client", lambda name, **kw: seen.update(kw) or FakeS3()
    )
    ms.S3Object(KEY, bytes).get()
    cfg = seen["config"]
    assert cfg.connect_timeout <= 5 and cfg.read_timeout <= 15
    assert cfg.retries["total_max_attempts"] == 2  # max_attempts=2 would mean 3 tries


def test_manifest_version_and_missing_manifest(s3):
    s3.put(KEY, b"m", "e1")
    o = _obj()
    o.get()
    assert o.manifest is None and o.version is None
    s3.put(MAN, json.dumps({"version": "xgb-1"}).encode(), "e1")
    s3.put(KEY, b"m2", "e2")
    o.get()
    assert o.version == "xgb-1"


def _upload(candidate, champion_score=lambda b: 5.0, **kw):
    return ms.gated_upload(
        KEY,
        b"CAND",
        candidate_metric=candidate,
        metric_name="holdout_mae",
        score_champion=champion_score,
        extra_files={"xgb_points_metadata.json": b"{}"},
        manifest_extra={"data_window": "2025-10-01..2026-11-01"},
        **kw,
    )


def test_first_upload_with_no_live_model(s3):
    out = _upload(4.0)
    assert out["status"] == "first_upload" and out["archive_stamp"] is None
    assert s3.objects[KEY] == b"CAND"
    man = json.loads(s3.objects[MAN])
    assert man["data_window"] and man["champion_metric"] is None
    assert len(man["version"]) <= 20


def test_worse_candidate_is_not_uploaded(s3):
    s3.put(KEY, b"LIVE", "e1")
    out = _upload(5.5)  # champion 5.0, tolerance 0.5%
    assert out["status"] == "rejected_by_champion"
    assert s3.names("put") == [] and s3.objects[KEY] == b"LIVE"


def test_candidate_not_strictly_better_is_not_uploaded(s3):
    s3.put(KEY, b"LIVE", "e1")
    for metric in (5.0, 5.0 * (1 + 0.001)):  # tie, tiny regression
        out = _upload(metric)
        assert out["status"] == "rejected_by_champion"
    assert s3.names("put") == [] and s3.objects[KEY] == b"LIVE"


def _live_with_window(s3, window):
    s3.put(KEY, b"LIVE", "e1")
    s3.put(
        MAN, json.dumps({"data_window": window, "holdout_metric": 5.0}).encode(), "e1"
    )


def test_unchanged_data_window_is_not_uploaded_even_if_better(s3):
    _live_with_window(s3, "2025-10-01..2026-11-01")  # same as _upload's window
    out = _upload(4.0)
    assert out["status"] == "rejected_by_champion"
    assert out["reason"] == "unchanged_data_window"
    assert s3.names("put") == [] and s3.objects[KEY] == b"LIVE"


def test_grown_data_window_with_better_candidate_ships(s3):
    """The NBA weekly retrain: window end moves forward each week."""
    _live_with_window(s3, "2025-10-01..2026-10-25")
    out = _upload(4.0)
    assert out["status"] == "uploaded"
    assert json.loads(s3.objects[MAN])["data_window"] == "2025-10-01..2026-11-01"


def test_weekly_nba_style_cycle_through_upload_gated_pickle(s3):
    from app.services.ml import upload_to_s3 as u

    def go(window, mae):
        return u.upload_gated_pickle(
            KEY,
            {"m": 1},
            {"data_window": window},
            candidate_metric=mae,
            score_champion=lambda b: 5.0,
        )["status"]

    assert go("2025-10-01..2026-11-01", 4.0) == "first_upload"
    assert (
        go("2025-10-01..2026-11-01", 3.0) == "rejected_by_champion"
    )  # rerun, same data
    assert go("2025-10-01..2026-11-08", 3.0) == "uploaded"  # a week later


def test_better_candidate_archives_champion_before_put(s3):
    s3.put(KEY, b"LIVE", "e1")
    s3.put(META, b'{"live":1}', "e1")
    out = _upload(4.0)
    assert out["status"] == "uploaded" and out["champion_metric"] == 5.0
    ops = [c[0] for c in s3.calls if c[0] in ("copy", "put")]
    assert ops.index("put") > max(i for i, o in enumerate(ops) if o == "copy")
    arch = f"nba/ml_models/archive/{out['archive_stamp']}"
    assert s3.objects[f"{arch}/xgb_points.pkl"] == b"LIVE"
    assert s3.objects[f"{arch}/xgb_points_metadata.json"] == b'{"live":1}'
    assert s3.objects[KEY] == b"CAND"


def test_unscorable_champion_falls_back_to_manifest_metric(s3):
    s3.put(KEY, b"LIVE", "e1")
    s3.put(MAN, json.dumps({"holdout_metric": 3.0}).encode(), "e1")

    def boom(_):
        raise RuntimeError("feature mismatch")

    assert _upload(4.0, boom)["status"] == "rejected_by_champion"


def test_unscorable_champion_without_manifest_uploads_with_reason(s3):
    s3.put(KEY, b"LIVE", "e1")

    def boom(_):
        raise RuntimeError("x")

    out = _upload(4.0, boom)
    assert out["status"] == "uploaded" and out["champion_metric"] is None
    assert out["reason"] == "champion_unscorable"


def test_higher_is_better_metric(s3):
    s3.put(KEY, b"LIVE", "e1")
    out = _upload(0.60, lambda b: 0.70, lower_is_better=False)
    assert out["status"] == "rejected_by_champion"


def test_rollback_dry_run_vs_apply(s3):
    s3.put(KEY, b"V1", "e1")
    first = _upload(4.0)  # live V1 exists -> archived on the next upload
    s3.put(KEY, b"V2-live", "e9")
    s3.put("nba/ml_models/archive/20260101T000000/xgb_points.pkl", b"V1", "e1")
    stamps = ms.list_archive_stamps(KEY)
    assert "20260101T000000" in stamps and first["archive_stamp"] in stamps

    dry = ms.rollback(KEY, "20260101T000000")
    assert dry["status"] == "dry_run" and s3.objects[KEY] == b"V2-live"

    done = ms.rollback(KEY, "20260101T000000", dry_run=False)
    assert s3.objects[KEY] == b"V1"
    # V1 predates manifests: the replaced model's manifest must not stay live
    assert ms.manifest_key(KEY) not in s3.objects
    # the replaced live copy is itself archived, so rollback is undoable
    assert (
        s3.objects[
            f"nba/ml_models/archive/{done['archived_current_as']}/xgb_points.pkl"
        ]
        == b"V2-live"
    )

    with pytest.raises(ValueError):
        ms.rollback(KEY, "19990101T000000")


def test_list_archive_stamps_only_those_holding_the_model(s3):
    base = "nba/ml_models/archive"
    s3.put(f"{base}/20260101T000000/xgb_points.pkl", b"x", "e1")
    s3.put(f"{base}/20260102T000000/xgb_rebounds.pkl", b"x", "e1")  # other model
    s3.put(f"{base}/20260103T000000/xgb_points_manifest.json", b"{}", "e1")  # no pkl
    assert ms.list_archive_stamps(KEY) == ["20260101T000000"]
    assert ms.list_archive_stamps("nba/ml_models/xgb_rebounds.pkl") == [
        "20260102T000000"
    ]
