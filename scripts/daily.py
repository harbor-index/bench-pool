#!/usr/bin/env python3
"""Run the whole pipeline once, in order. Meant to be started once a day.

    python3 scripts/daily.py              # the daily run
    python3 scripts/daily.py --weekly     # also search for each benchmark's own leaderboard
    python3 scripts/daily.py --dry-run    # print the steps, run nothing
    python3 scripts/daily.py --from signals
    python3 scripts/daily.py --days 1 --tier-limit 10   # a small trial: one snapshot, ten verdicts

Every step only does what is new: fetch skips snapshots already on disk,
classify labels only unlabelled candidates, signals asks a source again after
7 days, tier judges only benchmarks without a verdict under the current
standard. So a normal day costs one snapshot, a few gate calls and one tiering
call per new benchmark.

A failed step stops the run; the site keeps its last good data, because
build.py is what writes it. Output goes to data/daily.log (appended) and to the
terminal. The exit code is 0 only if every step succeeded.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "data" / "daily.log"
POOL = ROOT / "web" / "data" / "benchmarks.json"

# (name, script and arguments, what it does)
STEPS = [
    ("fetch", ["fetch.py"], "new Radar snapshots and leaderboard crawls"),
    ("leaderboards", ["leaderboards.py"], "top score per benchmark from the crawls"),
    ("candidates", ["candidates.py"], "rules, leaderboards, Adapter List, merge duplicates"),
    ("classify", ["classify.py"], "benchmark gate, mode and class for new candidates"),
    ("find_leaderboards", ["find_leaderboards.py"], "each benchmark's own leaderboard (weekly)"),
    ("signals", ["signals.py"], "stars, citations, likes"),
    ("build", ["build.py"], "join everything for the site"),
    ("tier", ["tier.py"], "judge benchmarks that have no verdict under the current standard"),
    ("publish", ["build.py"], "put the new verdicts on the site"),
]
WEEKLY_ONLY = {"find_leaderboards"}
# classify and tier exit with 2 when some records got no answer; the next run retries those.
SOFT_FAIL = {"classify": {2}, "tier": {2}}


def summary() -> dict:
    if not POOL.exists():
        return {}
    meta = json.loads(POOL.read_text())["meta"]
    return {"benchmarks": meta["funnel"]["benchmarks"], "candidates": meta["tiering"].get("candidates"),
            "tiers": meta["tiering"].get("tiers"), "last_snapshot": meta["snapshots"]["last"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--weekly", action="store_true", help="also run the own-leaderboard search")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, help="only fetch the last N days of Radar snapshots (default: all)")
    parser.add_argument("--tier-limit", type=int, help="judge at most N benchmarks in this run")
    parser.add_argument("--from", dest="start", choices=[s[0] for s in STEPS], help="start at this step")
    args = parser.parse_args()

    extra = {"fetch": ["--days", str(args.days)] if args.days else [],
             "tier": ["--limit", str(args.tier_limit)] if args.tier_limit else []}
    steps = [(name, command + extra.get(name, []), what) for name, command, what in STEPS
             if args.weekly or name not in WEEKLY_ONLY]
    if args.start:
        steps = steps[[s[0] for s in steps].index(args.start):]
    if args.dry_run:
        for name, command, what in steps:
            print(f"{name:18} python3 scripts/{' '.join(command):24} {what}")
        return 0

    before = summary()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as log:
        def say(text: str) -> None:
            print(text, flush=True)
            log.write(text + "\n")
            log.flush()

        say(f"\n=== daily run {dt.datetime.now().isoformat(timespec='seconds')} ===")
        for name, command, what in steps:
            started = time.time()
            say(f"--- {name}: {what}")
            proc = subprocess.run([sys.executable, str(ROOT / "scripts" / command[0]), *command[1:]],
                                  cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            tail = "\n".join(proc.stdout.strip().splitlines()[-6:])
            say(tail)
            took = f"{time.time() - started:.0f}s"
            if proc.returncode in SOFT_FAIL.get(name, ()):
                say(f"    {name} left some records unanswered ({took}); they are retried next run")
            elif proc.returncode != 0:
                say(f"!!! {name} failed with exit code {proc.returncode} after {took}; stopping. The site keeps its previous data.")
                return 1
            else:
                say(f"    ok ({took})")
        after = summary()
        say(f"=== done. before: {json.dumps(before, ensure_ascii=False)}")
        say(f"          after:  {json.dumps(after, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
