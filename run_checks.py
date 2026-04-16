#!/usr/bin/env python3
"""Run scheduled product checks without needing the web UI open."""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

import server


DEFAULT_INTERVAL_SECONDS = 6 * 60 * 60


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check all watched products on a fixed interval."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check pass and exit.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.getenv("CHECK_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)),
        help="Seconds between automated check runs. Defaults to 21600 (6 hours).",
    )
    return parser.parse_args()


def run_once() -> int:
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{started_at}] Starting automated product check...")
    result = server.refresh_all_products(all_scopes=True)

    updated = len(result["updated"])
    drops = len(result["drops"])
    increases = len(result["increases"])
    errors = len(result["errors"])

    print(
        "Completed check: "
        f"{updated} updated, {drops} drops, {increases} increases, {errors} errors."
    )

    if errors:
        for error in result["errors"]:
            print(
                f"  - {error['product_id']}: {error['error']}",
                file=sys.stderr,
            )

    return 1 if errors else 0


def main() -> int:
    args = parse_args()

    if args.interval_seconds <= 0:
        raise ValueError("--interval-seconds must be greater than zero.")

    if args.once:
        return run_once()

    print(
        "Running scheduled checks every "
        f"{args.interval_seconds} seconds "
        f"({args.interval_seconds / 3600:.1f} hours)."
    )

    while True:
        run_once()
        print(f"Sleeping for {args.interval_seconds} seconds...")
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
