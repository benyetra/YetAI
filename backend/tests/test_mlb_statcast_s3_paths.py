from app.services.etl.mlb.statcast_ingest.s3_paths import manifest_key, partition_uri


def test_partition_uri():
    assert partition_uri(2024, 5).endswith("season=2024/month=05/part.parquet")


def test_manifest_key():
    assert manifest_key(2024).endswith("season=2024/_manifest.json")
