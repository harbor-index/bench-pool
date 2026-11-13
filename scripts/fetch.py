#!/usr/bin/env python3
"""Download Benchmark Radar daily snapshots and leaderboard crawls.

Source: https://github.com/ktwu01/benchmark-radar (content CC BY-NC-SA 4.0).
Files already on disk are kept, so a daily run only fetches the new day.

    python3 scripts/fetch.py            # everything since the first snapshot
    python3 scripts/fetch.py --days 7   # only the last 7 days
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
BASE = "https://raw.githubusercontent.com/ktwu01/benchmark-radar/main/data"
FIRST_SNAPSHOT = dt.date(2026, 7, 23)
LEADERBOARDS = [
    "llm_stats_benchmarks_2026-08-17.csv",
    "llm_stats_benchmark_scores_2026-08-17.csv",
    "artificial_analysis_benchmarks_2026-08-25.csv",
    "artificial_analysis_benchmark_scores_2026-08-25.csv",
    "benchmark_saturation_benchmarks_2026-11-04.csv",
    "benchmark_saturation_benchmark_scores_2026-11-04.csv",
]


def get(url: str, dest: Path, check_json: bool = False) -> str:
    if dest.exists() and dest.stat().st_size > 0:
        return "kept"
    req = urllib.request.Request(url, headers={"User-Agent": "bench-pool-mvp"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read()
    except urllib.error.HTTPError as err:
        return "missing" if err.code == 404 else f"http {err.code}"
    except OSError as err:
        return f"error {err}"
    if check_json:
        try:
            json.loads(body)
        except ValueError:
            return "not json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return "new"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, help="only the last N days")
    args = parser.parse_args()

    today = dt.datetime.now(dt.timezone.utc).date()
    start = FIRST_SNAPSHOT
    if args.days:
        start = max(start, today - dt.timedelta(days=args.days - 1))
    days = [start + dt.timedelta(days=i) for i in range((today - start).days + 1)]

    jobs = [
        (f"{BASE}/snapshots/{d}.json", RAW / "snapshots" / f"{d}.json", True) for d in days
    ] + [
        (f"{BASE}/leaderboard_snapshots/{name}", RAW / "leaderboards" / name, False)
        for name in LEADERBOARDS
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda job: get(*job), jobs))

    counts: dict[str, int] = {}
    for (url, _, _), status in zip(jobs, results):
        counts[status] = counts.get(status, 0) + 1
        if status not in ("kept", "new", "missing"):
            print(f"  {status}: {url}", file=sys.stderr)
    print("fetch:", ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
    have = sorted(p.stem for p in (RAW / "snapshots").glob("*.json"))
    print(f"snapshots on disk: {len(have)} ({have[0]} .. {have[-1]})" if have else "no snapshots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
