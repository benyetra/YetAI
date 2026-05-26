from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import boto3


def base_prefix() -> str:
    return os.getenv(
        "MLB_STATCAST_S3_PREFIX", "s3://yetibets/mlb/statcast/pitches"
    ).rstrip("/")


def partition_uri(season: int, month: int) -> str:
    return f"{base_prefix()}/season={season}/month={month:02d}/part.parquet"


def manifest_key(season: int) -> str:
    rel = f"season={season}/_manifest.json"
    prefix = base_prefix()
    if prefix.startswith("s3://"):
        return f"{prefix}/{rel}"
    return str(Path(prefix) / rel)


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")
    return bucket, key


def partition_exists(uri: str) -> bool:
    if uri.startswith("s3://"):
        bucket, key = _parse_s3_uri(uri)
        try:
            boto3.client("s3").head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False
    return Path(uri).is_file()


def read_manifest(season: int) -> list[str]:
    path = manifest_key(season)
    if path.startswith("s3://"):
        bucket, key = _parse_s3_uri(path)
        try:
            obj = boto3.client("s3").get_object(Bucket=bucket, Key=key)
            return json.loads(obj["Body"].read().decode("utf-8"))
        except Exception:
            return []
    p = Path(path)
    if not p.is_file():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def write_manifest(season: int, partitions: list[str]) -> None:
    path = manifest_key(season)
    body = json.dumps(sorted(set(partitions)), indent=2)
    if path.startswith("s3://"):
        bucket, key = _parse_s3_uri(path)
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
