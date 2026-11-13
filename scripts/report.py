#!/usr/bin/env python3
"""Write the day's report: what is new, what was recommended, what changed tier.

Reads  web/data/benchmarks.json   (run scripts/build.py first)
Writes reports/<date>.md          one file per day; a later run on the same day replaces it

"New" means first seen by Radar after the snapshot the previous report ended on.
With no earlier report, it means first seen on the latest snapshot day.

    python3 scripts/report.py
    python3 scripts/report.py --since 2026-11-10    # everything first seen after this day
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "web" / "data" / "benchmarks.json"
OUT = ROOT / "reports"
SITE = "https://harbor-index.github.io/bench-pool/"
MARK = re.compile(r"<!-- snapshot: (\d{4}-\d{2}-\d{2}) -->")
SINCE = re.compile(r"<!-- since: (\d{4}-\d{2}-\d{2}) -->")
TIER = {"recommend": "Recommend", "hold": "Hold", "no": "No", None: "Not judged yet"}
ORDER = ["recommend", "hold", "no", None]
MODE = {"agentic": "agentic", "modified": "modified-agentic", "non": "non-agentic"}


def previous_snapshot(today: str) -> str | None:
    """Where this report's window starts: the snapshot day the newest earlier report ended on.

    A second run on the same day keeps the window the first one used, so the
    day's report does not shrink to the last few hours.
    """
    mine = OUT / f"{today}.md"
    if mine.exists():
        found = SINCE.search(mine.read_text())
        if found:
            return found.group(1)
    marks = []
    for path in sorted(OUT.glob("*.md")):
        if path.stem < today:
            found = MARK.search(path.read_text())
            if found:
                marks.append(found.group(1))
    return marks[-1] if marks else None


def cell(text: str | None) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ").strip()


def link(item: dict) -> str:
    return f"[{cell(item['name'])}]({SITE}#/b/{item['id']})"


def score(item: dict) -> str:
    if item.get("best") is None:
        return "—"
    return f"{item['best']:g}% ({ {'own': 'own board', 'aggregator': 'public board', 'paper': 'paper'}[item['basis']] })"


def tier_of(item: dict) -> str | None:
    return item["tier"]["tier"] if item.get("tier") else None


def table(items: list[dict]) -> list[str]:
    lines = ["| Benchmark | Type | Class | Best score | Why |", "|---|---|---|---|---|"]
    for it in items:
        why = it["tier"]["reason"] if it.get("tier") else it.get("does")
        lines.append(f"| {link(it)} | {MODE[it['mode']]} | {cell(it['class_name'])} | {score(it)} | {cell(why)} |")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", help="report everything first seen after this day (YYYY-MM-DD)")
    args = parser.parse_args()

    data = json.loads(POOL.read_text())
    meta, items = data["meta"], data["items"]
    names = {c["id"]: c["name"] for c in meta["classes"]}
    for it in items:
        it["class_name"] = names[it["cls"]]
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    last = meta["snapshots"]["last"]
    since = args.since or previous_snapshot(today)
    candidates = [i for i in items if not i["covered"]]

    if since:
        new = [i for i in candidates if i.get("seen") and since < i["seen"] <= last]
        window = f"first seen by Radar after {since}, up to {last}"
    else:
        new = [i for i in candidates if i.get("seen") == last]
        window = f"first seen by Radar on {last}"
    new.sort(key=lambda i: (ORDER.index(tier_of(i)), i["name"].lower()))
    moved = [i for i in candidates if len(i["tier_trail"]) > 1 and i["tier_trail"][-1][0] == today]
    waiting = [i for i in candidates if not i.get("tier")]
    tiering = meta["tiering"]
    by_tier = Counter(tier_of(i) for i in new)

    out = [
        f"<!-- snapshot: {last} -->" + (f"\n<!-- since: {since} -->" if since else ""),
        f"# bench-pool, {today}",
        "",
        f"Site: <{SITE}>",
        "",
        "## Today",
        "",
        f"- **{len(new)} new benchmarks** ({window}): "
        + ", ".join(f"{by_tier[t]} {TIER[t].lower()}" for t in ORDER if by_tier[t]) + ("." if new else "none."),
        f"- {len(moved)} changed tier today.",
        f"- {len(waiting)} candidates are waiting to be judged.",
        "",
        "## The pool",
        "",
        "| | Count |",
        "|---|---|",
        f"| Benchmarks in the pool | {len(items):,} |",
        f"| Already covered by Harbor Index v1 or a Harbor adapter | {len(items) - len(candidates):,} |",
        f"| New candidates | {len(candidates):,} |",
        f"| Recommend | {tiering['tiers'].get('recommend', 0):,} |",
        f"| Hold | {tiering['tiers'].get('hold', 0):,} |",
        f"| No | {tiering['tiers'].get('no', 0):,} |",
        "",
    ]
    for tier in ORDER:
        group = [i for i in new if tier_of(i) == tier]
        if group:
            out += [f"## New: {TIER[tier]} ({len(group)})", "", *table(group), ""]
    if not new:
        out += ["## New", "", "Nothing new in this window.", ""]
    if moved:
        out += ["## Changed tier today", "", "| Benchmark | Was | Now | Why |", "|---|---|---|---|"]
        for it in moved:
            out.append(f"| {link(it)} | {TIER[it['tier_trail'][-2][1]]} | **{TIER[tier_of(it)]}** | {cell(it['tier']['reason'])} |")
        out.append("")
    out += ["Verdicts are made by a language model from the paper and the repository, and have not been "
            "checked by a person. \"Why\" is the model's one-line reason; each benchmark's page has the quotes behind it.", ""]

    OUT.mkdir(exist_ok=True)
    path = OUT / f"{today}.md"
    path.write_text("\n".join(out))
    print(f"wrote {path.relative_to(ROOT)}: {len(new)} new ({window}), {len(moved)} changed tier, {len(waiting)} waiting")


if __name__ == "__main__":
    main()
