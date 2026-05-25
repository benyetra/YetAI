#!/usr/bin/env python3
"""
Production ETL verification CLI.

Requires admin JWT (logged-in YetAI admin):
  export YETAI_ADMIN_JWT='...'   # from browser localStorage auth_token
  # or login:
  export YETAI_ADMIN_EMAIL='...'
  export YETAI_ADMIN_PASSWORD='...'

Usage:
  PYTHONPATH=. python3 scripts/prod_verify_etl.py
  PYTHONPATH=. python3 scripts/prod_verify_etl.py --enqueue-all --wait 600
  PYTHONPATH=. python3 scripts/prod_verify_etl.py --poll TASK_ID
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_API = "https://api.yetai.app"


def _request(
    method: str,
    url: str,
    token: str,
    body: dict | None = None,
    *,
    timeout: int = 300,
) -> dict:
    data = None
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:500]
        raise SystemExit(f"HTTP {e.code} {url}: {detail}") from e


def _login(api: str, email: str, password: str) -> str:
    payload = json.dumps({"email_or_username": email, "password": password}).encode()
    req = urllib.request.Request(
        f"{api}/api/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:500]
        raise SystemExit(f"HTTP {e.code} {api}/api/auth/login: {detail}") from e
    token = data.get("access_token") or data.get("token")
    if not token:
        raise SystemExit(f"login response missing token: {list(data.keys())}")
    return token.strip()


def _poll_tasks(api: str, token: str, task_ids: list[str], timeout_s: int) -> bool:
    deadline = time.time() + timeout_s
    pending = set(task_ids)
    while pending and time.time() < deadline:
        for tid in list(pending):
            st = _request("GET", f"{api}/api/admin/celery/task-status/{tid}", token)
            if st.get("ready"):
                pending.discard(tid)
                result = st.get("result") or {}
                status = result.get("status") if isinstance(result, dict) else None
                print(f"  {tid[:8]}... {st.get('state')} pipeline_status={status}")
        if pending:
            print(f"  waiting on {len(pending)} task(s)...")
            time.sleep(30)
    if pending:
        print(f"TIMEOUT: still pending: {pending}", file=sys.stderr)
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify YetAI ETL in production")
    parser.add_argument("--api", default=os.getenv("YETAI_API_URL", DEFAULT_API))
    parser.add_argument("--enqueue-all", action="store_true")
    parser.add_argument(
        "--wait", type=int, default=0, help="Seconds to wait after enqueue"
    )
    parser.add_argument("--poll", metavar="TASK_ID", help="Poll one task until ready")
    parser.add_argument("--poll-timeout", type=int, default=7200)
    args = parser.parse_args()

    token = (os.getenv("YETAI_ADMIN_JWT") or "").strip() or None
    if not token:
        email = os.getenv("YETAI_ADMIN_EMAIL")
        password = os.getenv("YETAI_ADMIN_PASSWORD")
        if email and password:
            print("Logging in...")
            token = _login(args.api, email, password)
        else:
            print(
                "Set YETAI_ADMIN_JWT or YETAI_ADMIN_EMAIL + YETAI_ADMIN_PASSWORD",
                file=sys.stderr,
            )
            return 2

    if args.poll:
        ok = _poll_tasks(args.api, token, [args.poll], args.poll_timeout)
        return 0 if ok else 1

    print(f"POST {args.api}/api/admin/celery/verify-etl")
    # Do not pass wait_seconds to the API: the server would block the HTTP
    # response for that duration while this CLI polls task-status locally.
    report = _request(
        "POST",
        f"{args.api}/api/admin/celery/verify-etl",
        token,
        {"enqueue_all": args.enqueue_all, "wait_seconds": 0},
    )
    print(json.dumps(report, indent=2, default=str))

    enqueued = report.get("enqueued") or []
    if enqueued and args.wait > 0:
        ids = [e["task_id"] for e in enqueued]
        print(f"\nPolling {len(ids)} pipelines (timeout {args.wait}s)...")
        _poll_tasks(args.api, token, ids, args.wait)
        print("\nRe-running verification...")
        report = _request(
            "POST",
            f"{args.api}/api/admin/celery/verify-etl",
            token,
            {"enqueue_all": False, "wait_seconds": 0},
        )
        print(json.dumps(report.get("verification"), indent=2, default=str))

    overall = (report.get("verification") or {}).get("overall", "unknown")
    return 0 if overall == "verified" else 1


if __name__ == "__main__":
    sys.exit(main())
