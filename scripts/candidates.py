#!/usr/bin/env python3
"""Stage 1 of the gate: cheap rules, then merge duplicate records.

Reads every Radar snapshot in data/raw/snapshots, keeps records that look like
an agentic benchmark, and merges records that describe the same work (same
arXiv id, same title, or a shared artifact link). Then adds every benchmark in
Radar's leaderboard crawls and every row of the team's Adapter List.
Writes data/candidates.json.

A snapshot record needs an agent word, or else visible traction (TRACTION
below). Dropping the agent word outright would add about 12,500 records, and a
sample showed most are models, methods and datasets that Radar tagged
"benchmark". Non-agentic benchmarks therefore enter through the leaderboard
crawls, the Adapter List, and this traction bar.

This stage only removes records that cannot pass. The real decision is made by
scripts/classify.py.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOTS = ROOT / "data" / "raw" / "snapshots"
LEADERBOARDS = ROOT / "data" / "leaderboards.json"
ADAPTER_LIST = ROOT / "data" / "adapter_list.json"                 # full export, git-ignored
ESTABLISHED = ROOT / "data" / "established_benchmarks.json"       # the committed part of it
OUT = ROOT / "data" / "candidates.json"

# Rule: Radar tagged the record benchmark/evaluation, AND either Radar tagged it
# agentic or the title itself names something an agent does. Matching the same
# words anywhere in the abstract was tried and let in mostly noise.
AGENT_TITLE_RE = re.compile(
    r"\bagents?\b|agentic|tool[- ](use|call|calling)|function[- ]calling|computer[- ]use|"
    r"\bGUI\b|web navigation|browser|\bterminal\b|\bMCP\b|long[- ]horizon|embodied|"
    r"repository[- ]level|\bSWE[- ]|deep research",
    re.I,
)
# A record with no agent word still becomes a candidate when people have noticed
# it: any one of these counts on the Radar record itself. This is how new
# non-agentic benchmarks get in; without the bar the rule would add about
# 12,500 records, most of them not benchmarks at all.
TRACTION = {"upvotes": 10, "stars": 100, "citations": 10, "likes": 20, "downloads": 5000}


def has_traction(rec: dict) -> bool:
    metrics = rec.get("metrics") or {}
    return any(isinstance(metrics.get(k), (int, float)) and metrics[k] >= bar for k, bar in TRACTION.items())


ARXIV_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|arxiv[.:]|huggingface\.co/papers/)(\d{4}\.\d{4,5})", re.I)
SOURCE_RANK = {  # which record supplies the title and summary
    "arXiv": 0, "Hugging Face Papers": 1, "XBsleepy": 2, "Semantic Scholar": 3, "OpenAlex": 4,
    "DataCite": 5, "Crossref": 6, "First-party feed": 7, "GitHub": 8, "GitHub Organization": 8,
    "GitHub Release": 9, "Hugging Face": 9, "Kaggle Dataset": 10, "Zenodo": 10,
}


def arxiv_id(record: dict) -> str | None:
    for text in (record.get("url") or "", str(record.get("source_id") or "")):
        match = ARXIV_RE.search(text)
        if match:
            return match.group(1)
    if record.get("source") == "arXiv" and re.fullmatch(r"\d{4}\.\d{4,5}", str(record.get("source_id") or "")):
        return str(record["source_id"])
    return None


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def norm_url(url: str) -> str:
    url = re.sub(r"^https?://(www\.)?", "", url.strip().lower())
    return re.sub(r"(\.git)?/*$", "", url)


def link_kind(url: str) -> str:
    u = url.lower()
    if "arxiv.org" in u or "doi.org" in u or "openreview.net" in u or "huggingface.co/papers" in u \
            or "semanticscholar.org" in u or "openalex.org" in u:
        return "paper"
    if "github.com" in u or "gitlab.com" in u:
        return "code"
    if "huggingface.co/datasets" in u or "kaggle.com" in u or "zenodo.org" in u:
        return "data"
    if "huggingface.co/spaces" in u:
        return "space"
    return "web"


class Groups:
    """Union-find over record keys."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, key: str) -> str:
        self.parent.setdefault(key, key)
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def main() -> None:
    files = sorted(SNAPSHOTS.glob("*.json"))
    if not files:
        raise SystemExit("no snapshots; run scripts/fetch.py first")

    seen = Counter()
    groups = Groups()
    records: list[tuple[str, str, dict]] = []  # (record key, snapshot date, record)
    for path in files:
        day = path.stem
        for rec in json.loads(path.read_text()).get("evidence_items", []):
            seen["records"] += 1
            title = (rec.get("title") or "").strip()
            if not title:
                continue
            cats = rec.get("categories") or []
            tags = rec.get("source_tags") or []
            tagged = "agentic" in cats or any(t.startswith("xbsleepy:") for t in tags)
            if tagged:
                keep = "benchmark" in cats or "evaluation" in cats
            else:
                keep = "benchmark" in cats and bool(AGENT_TITLE_RE.search(title))
            if not keep and "benchmark" in cats:
                seen["benchmark tag, no agent word"] += 1
                keep = has_traction(rec)
                seen["admitted on traction"] += keep
            if not keep:
                continue
            seen["passed rules"] += 1
            url = rec.get("url") or ""
            key = "u:" + norm_url(url) if url else "t:" + norm_title(title)
            axv = arxiv_id(rec)
            if axv:
                groups.union(key, "a:" + axv)
            if len(norm_title(title)) >= 20 and "/" not in title:
                groups.union(key, "t:" + norm_title(title))
            for extra in rec.get("artifact_urls") or []:
                if link_kind(extra) in ("code", "data", "paper"):
                    groups.union(key, "u:" + norm_url(extra))
            records.append((key, day, rec))

    merged: dict[str, list[tuple[str, dict]]] = {}
    for key, day, rec in records:
        merged.setdefault(groups.find(key), []).append((day, rec))

    candidates = []
    for members in merged.values():
        members.sort(key=lambda m: (SOURCE_RANK.get(m[1].get("source"), 20), -len(m[1].get("summary") or "")))
        lead = members[0][1]
        axv = next((a for a in (arxiv_id(r) for _, r in members) if a), None)
        ident = "arxiv-" + axv.replace(".", "-") if axv else \
            "r-" + hashlib.sha1(norm_url(lead.get("url") or lead["title"]).encode()).hexdigest()[:10]
        links: dict[str, str] = {}
        for _, rec in members:
            for url in [rec.get("url")] + list(rec.get("artifact_urls") or []):
                if url and norm_url(url) not in {norm_url(u) for u in links}:
                    links[url] = link_kind(url)
        metrics: dict[str, float] = {}
        for _, rec in members:
            for name, value in (rec.get("metrics") or {}).items():
                if isinstance(value, (int, float)):
                    metrics[name] = max(metrics.get(name, 0), value)
        dates = sorted(r.get("published_at") for _, r in members if r.get("published_at"))
        summary = max((r.get("summary") or "" for _, r in members[:3]), key=len)
        candidates.append({
            "id": ident,
            "title": lead["title"].strip(),
            "summary": summary.strip(),
            "published": dates[0][:10] if dates else None,
            "first_seen": min(day for day, _ in members),
            "last_seen": max(day for day, _ in members),
            "sources": sorted({r.get("source") for _, r in members if r.get("source")}),
            "links": [{"url": u, "kind": k} for u, k in links.items()][:12],
            "authors": (lead.get("authors") or [])[:4],
            "author_count": len(lead.get("authors") or []),
            "organizations": sorted({o for _, r in members for o in (r.get("organizations") or [])})[:6],
            "metrics": metrics,
            "radar_categories": sorted({c for _, r in members for c in (r.get("categories") or [])}),
            "radar_tags": sorted({t.split(":", 1)[-1] for _, r in members for t in (r.get("source_tags") or [])}),
            "radar_score": max((r.get("total_score") or 0) for _, r in members),
            "updated": any(r.get("event_kind") == "updated" for _, r in members),
        })

    for cand in candidates:
        cand["origin"] = "snapshot"

    # Every benchmark that Radar's leaderboard crawls list. They go through the
    # same gate; scripts/build.py joins them to snapshot records by name.
    boards: dict[str, list[dict]] = {}
    if LEADERBOARDS.exists():
        for entry in json.loads(LEADERBOARDS.read_text()):
            boards.setdefault(entry["key"], []).append(entry)
    for key, entries in boards.items():
        lead = max(entries, key=lambda e: len(e["description"]))
        candidates.append({
            "id": "lb-" + key, "title": lead["name"], "summary": lead["description"],
            "published": min((e["released"] for e in entries if e["released"]), default=None),
            "first_seen": None, "last_seen": None,
            "sources": sorted({e["source"] for e in entries}),
            "links": [{"url": e["url"], "kind": "leaderboard"} for e in entries],
            "authors": [], "author_count": 0, "organizations": [], "metrics": {},
            "radar_categories": [], "radar_tags": sorted({c for e in entries for c in e["categories"]}),
            "radar_score": 0, "updated": False, "origin": "leaderboard",
        })

    # Mature benchmarks from the team's Adapter List (scripts/adapter_list.py).
    # Radar's snapshots only start in July 2026, so older benchmarks enter here.
    if ADAPTER_LIST.exists():
        seeds = json.loads(ADAPTER_LIST.read_text())["rows"]
    elif ESTABLISHED.exists():        # the committed list: names and links only
        seeds = [{"name": b["name"], "link": b["link"], "description": "", "domain": "",
                  "status": "Merged" if b["harbor_adapter"] else ""}
                 for b in json.loads(ESTABLISHED.read_text())["benchmarks"]]
    else:
        seeds = []
    for row in seeds:
        summary = ". ".join(t for t in (row["description"], "Domain: " + row["domain"] if row["domain"] else "") if t)
        candidates.append({
            "id": "al-" + norm_title(row["name"]), "title": row["name"], "summary": summary,
            "published": None, "first_seen": None, "last_seen": None,
            "sources": ["Harbor Adapter List"],
            "links": [{"url": row["link"], "kind": link_kind(row["link"])}] if row["link"] else [],
            "authors": [], "author_count": 0, "organizations": [], "metrics": {},
            "radar_categories": [], "radar_tags": [], "radar_score": 0, "updated": False,
            "origin": "adapter_list",
            "adapter": {k: row.get(k) or ("" if k != "mode" else None)
                        for k in ("mode", "saturated", "include", "priority", "status", "notes", "pr")},
        })

    candidates.sort(key=lambda c: (c["published"] or "", c["id"]), reverse=True)
    ids = Counter(c["id"] for c in candidates)
    assert max(ids.values()) == 1, [i for i, n in ids.items() if n > 1][:5]
    OUT.write_text(json.dumps({
        "snapshots": [files[0].stem, files[-1].stem, len(files)],
        "counts": {"records": seen["records"], "passed_rules": seen["passed rules"],
                   "candidates": len(candidates) - len(boards) - len(seeds), "leaderboard_candidates": len(boards),
                   "adapter_list_candidates": len(seeds),
                   "no_agent_word_records": seen["benchmark tag, no agent word"],
                   "traction_records": seen["admitted on traction"], "traction_bar": TRACTION},
        "candidates": candidates,
    }, ensure_ascii=False, indent=1))
    print(f"snapshots {files[0].stem}..{files[-1].stem} ({len(files)})")
    print(f"records {seen['records']} -> passed rules {seen['passed rules']} -> merged candidates "
          f"{len(candidates) - len(boards) - len(seeds)} (+ {len(boards)} from leaderboard crawls, "
          f"+ {len(seeds)} from the Adapter List)")
    print(f"no agent word: {seen['benchmark tag, no agent word']} records, {seen['admitted on traction']} admitted on traction")
    print("by lead source:", Counter(c["sources"][0] for c in candidates).most_common(8))


if __name__ == "__main__":
    main()
