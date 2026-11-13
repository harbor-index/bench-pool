#!/usr/bin/env python3
"""The benchmark pool: candidates the gate called a benchmark, one row per benchmark.

Shared by scripts/find_leaderboards.py (which searches for each benchmark's own
leaderboard) and scripts/build.py (which writes the site's data file), so both
agree on what "one benchmark" is and on its key.

Name matching
-------------
Two records are the same benchmark when their names give the same key.
`canon_key` is `norm_name` (letters and digits only) after three spelling rules:

- a trailing word "benchmark" or "leaderboard" is dropped
  ("Era by Eon Benchmark" = "Era by Eon")
- a "v" in front of a version number is dropped ("Terminal-Bench v2.1" = "2.1")
- a trailing ".0" on a version is dropped ("OSWorld 2.0" = "OSWorld 2")

Versions and variants stay separate benchmarks: "OSWorld" and "OSWorld 2.0",
"SWE-bench" and "SWE-bench Verified" have different keys. Spellings no rule can
catch are listed by hand in data/aliases.json.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from classify import load_labels
from leaderboards import norm_name

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ALIASES = DATA / "aliases.json"
ORIGIN_ORDER = ["snapshot", "adapter_list", "leaderboard"]
LEAD_ORDER = ["arXiv", "Hugging Face Papers", "XBsleepy", "Semantic Scholar", "OpenAlex", "DataCite", "Crossref"]


def load_aliases() -> dict[str, str]:
    """{variant spelling: canonical spelling}, both turned into keys."""
    if not ALIASES.exists():
        return {}
    pairs = json.loads(ALIASES.read_text()).get("same_benchmark", {})
    return {_rules(a): _rules(b) for a, b in pairs.items()}


def _rules(name: str) -> str:
    s = name.strip()
    s = re.sub(r"\s+\(?(benchmark|leaderboard)\)?$", "", s, flags=re.I)
    s = re.sub(r"(?<![A-Za-z])v(?=\d)", "", s, flags=re.I)
    s = re.sub(r"(\d)\.0\b", r"\1", s)
    return norm_name(s)


_ALIASES: dict[str, str] | None = None


def canon_key(name: str) -> str:
    global _ALIASES
    if _ALIASES is None:
        _ALIASES = load_aliases()
    key = _rules(name)
    return _ALIASES.get(key, key)


def lead_rank(cand: dict) -> tuple:
    ranks = [LEAD_ORDER.index(s) for s in cand["sources"] if s in LEAD_ORDER]
    return (ORIGIN_ORDER.index(cand["origin"]), min(ranks, default=99), -len(cand["summary"]))


def load() -> tuple[dict, dict[str, dict], dict[str, dict], list[dict]]:
    """Returns (candidates bundle, candidates by id, labels by id, benchmarks).

    Each benchmark is {"key", "name", "members", "labels"}: members are its
    candidate records, lead first; labels are the gate answers in the same order.
    """
    bundle = json.loads((DATA / "candidates.json").read_text())
    candidates = {c["id"]: c for c in bundle["candidates"]}
    labels = {cid: row for cid, row in load_labels(DATA / "labels.jsonl").items() if cid in candidates}

    kept = [cid for cid, lab in labels.items() if lab["bench"]]
    groups: dict[str, list[str]] = {}
    for cid in kept:
        if candidates[cid]["origin"] != "snapshot":
            # the curated table's own name, not the model's rewording
            key = canon_key(candidates[cid]["title"])
        else:
            key = canon_key(labels[cid]["name"])
            # Short names are too easy to collide, so they stay apart.
            if len(key) < 5:
                key = "id:" + cid
        groups.setdefault(key, []).append(cid)

    benchmarks = []
    for key, ids in groups.items():
        members = sorted((candidates[i] for i in ids), key=lead_rank)
        lead = members[0]
        member_labels = [labels[m["id"]] for m in members]
        name = lead["title"] if lead["origin"] != "snapshot" else member_labels[0]["name"]
        benchmarks.append({"key": key, "name": name, "members": members, "labels": member_labels})
    return bundle, candidates, labels, benchmarks


if __name__ == "__main__":
    # Show what the spelling rules and the alias list merge.
    _, _, labels, benchmarks = load()
    for bench in benchmarks:
        names = sorted({m["title"] if m["origin"] != "snapshot" else lab["name"]
                        for m, lab in zip(bench["members"], bench["labels"])})
        if len({norm_name(n) for n in names}) > 1:
            print(f"{bench['key']:32} <- {names}")
