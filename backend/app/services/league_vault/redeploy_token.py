# Force Railway API rebuild after #52 deploy failure left prod on a stale image.
# This file is imported by the API process; bumping REDEPLOY_TOKEN changes the
# image layer and triggers a fresh deploy of auto-compute + draft hardening.
REDEPLOY_TOKEN = "2026-08-06-records-redeploy-1"
