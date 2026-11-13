#!/usr/bin/env python3
"""Look for the paper behind every benchmark that has nothing to read.

A benchmark that came in from a leaderboard or a hand-kept list often has no
paper or repository link, so the judge has nothing to go on. This step searches
arXiv for it by name, lets a model pick the paper that introduces it (or say
that none does), and records what was searched either way.

Reads  web/data/benchmarks.json        (run scripts/build.py first)
Writes data/source_search.json         {benchmark key: what was searched and found}

    python3 scripts/find_sources.py --limit 20
    python3 scripts/find_sources.py                    # every benchmark not searched in the last 30 days
    python3 scripts/find_sources.py --only "FrontierMath"

A match is kept only if the model names one of the listed papers AND the
benchmark's name appears in that paper's title or abstract. Otherwise the
benchmark stays without a source, and the site says that a search was made and
found nothing. arXiv is asked one question every three seconds.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import llm

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "web" / "data" / "benchmarks.json"
OUT = ROOT / "data" / "source_search.json"
ATOM = "{http://www.w3.org/2005/Atom}"
GITHUB_RE = re.compile(r"https?://github\.com/[\w.-]+/[\w.-]+")

PROMPT = """A catalogue of AI benchmarks has an entry with a name but no paper. Below are papers that an arXiv search for the name returned. Decide which one, if any, is the paper that INTRODUCES this benchmark.

Rules
- Pick a paper only if it presents a benchmark, dataset or evaluation suite with this name (or an obvious spelling of it). A paper that merely uses, extends or mentions it is not a match. A different benchmark with a similar name is not a match.
- If none of them introduces it, answer null. Most searches for sub-scores, leaderboard column names or product names find nothing; null is the expected answer then.

Reply with one JSON object and nothing else: {"match": "<arXiv id from the list>" or null, "why": "at most 20 words"}

ENTRY
"""


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def search_terms(name: str) -> str:
    """The benchmark's name as arXiv can search it: without brackets, versions in brackets or odd symbols."""
    name = re.sub(r"\([^)]*\)", " ", name)
    return re.sub(r"[^\w .+-]+", " ", name).strip()


def arxiv(query: str, last: list[float]) -> list[dict]:
    wait = 3.0 - (time.time() - last[0])
    if wait > 0:
        time.sleep(wait)
    url = "http://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": query, "max_results": 6, "sortBy": "relevance"})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bench-pool (source search)"}), timeout=40) as resp:
            root = ET.fromstring(resp.read())
    except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError):
        return []
    finally:
        last[0] = time.time()
    papers = []
    for entry in root.findall(f"{ATOM}entry"):
        ident = (entry.findtext(f"{ATOM}id") or "").rsplit("/abs/", 1)[-1]
        ident = re.sub(r"v\d+$", "", ident)
        if not re.fullmatch(r"\d{4}\.\d{4,5}", ident):
            continue
        papers.append({
            "id": ident,
            "title": " ".join((entry.findtext(f"{ATOM}title") or "").split()),
            "abstract": " ".join((entry.findtext(f"{ATOM}summary") or "").split()),
            "published": (entry.findtext(f"{ATOM}published") or "")[:10],
        })
    return papers


def look_up(item: dict, last: list[float]) -> dict:
    name = search_terms(item["name"])
    today = dt.date.today().isoformat()
    record = {"name": item["name"], "date": today, "searched": "arXiv", "query": name,
              "arxiv": None, "title": None, "repo": None, "considered": [], "why": ""}
    if len(squash(name)) < 3:
        record["why"] = "the name is too short to search for"
        return record
    papers = arxiv(f'ti:"{name}"', last)
    if not papers:
        papers = arxiv(f'all:"{name}" AND (all:benchmark OR all:evaluation)', last)
    record["considered"] = [p["title"][:120] for p in papers]
    if not papers:
        record["why"] = "no arXiv paper mentions this name"
        return record
    entry = {"name": item["name"], "what_the_catalogue_says": item.get("does") or "", "class": item.get("class_name")}
    listing = [{"id": p["id"], "title": p["title"], "abstract": p["abstract"][:700], "published": p["published"]} for p in papers]
    try:
        reply = llm.complete(PROMPT + json.dumps(entry, ensure_ascii=False) + "\n\nPAPERS\n" + json.dumps(listing, ensure_ascii=False, indent=0),
                             "You match catalogue entries to papers. You reply with JSON only.")
        answer = json.loads(re.search(r"\{.*\}", reply, re.S).group(0))
    except Exception as err:  # noqa: BLE001 - leave it unsearched so the next run tries again
        record["error"] = str(err)[:160]
        return record
    record["why"] = str(answer.get("why") or "")[:160]
    chosen = next((p for p in papers if p["id"] == answer.get("match")), None)
    if chosen and squash(name) not in squash(chosen["title"] + " " + chosen["abstract"]):
        record["why"] = "the paper the model picked does not contain the benchmark's name; not used"
        chosen = None
    if chosen:
        record.update(arxiv=chosen["id"], title=chosen["title"], published=chosen["published"])
        repo = GITHUB_RE.search(chosen["abstract"])
        if repo:
            record["repo"] = repo.group(0).rstrip(".").split("github.com/", 1)[1]
    return record


def load() -> dict[str, dict]:
    return json.loads(OUT.read_text()) if OUT.exists() else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="search at most N benchmarks")
    parser.add_argument("--only", help="one benchmark, by name")
    parser.add_argument("--recheck-days", type=int, default=30)
    args = parser.parse_args()

    data = json.loads(POOL.read_text())
    names = {c["id"]: c["name"] for c in data["meta"]["classes"]}
    done = load()
    cutoff = (dt.date.today() - dt.timedelta(days=args.recheck_days)).isoformat()

    def needs(item: dict) -> bool:
        has_paper = item["id"].startswith("arxiv-") or any("arxiv.org" in l["url"] or "10.48550" in l["url"] for l in item["links"])
        has_repo = bool((item.get("sig") or {}).get("repo")) or any(l["kind"] == "code" for l in item["links"])
        if has_paper or has_repo:
            return False
        old = done.get(item["key"])
        return not old or "error" in old or (old["arxiv"] is None and old["date"] <= cutoff)

    todo = [i for i in data["items"] if needs(i)]
    if args.only:
        todo = [i for i in data["items"] if i["name"].lower() == args.only.lower()]
    # Candidates before covered ones, then the ones with the most attention.
    todo.sort(key=lambda i: (bool(i.get("covered")), -(i.get("agg") or {}).get("models", 0) if i.get("agg") else 0))
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} benchmarks with nothing to read to search for", flush=True)

    last = [0.0]
    found = 0
    for n, item in enumerate(todo, 1):
        item["class_name"] = names[item["cls"]]
        record = look_up(item, last)
        if "error" in record:
            print(f"  {item['name']}: {record['error']}", file=sys.stderr, flush=True)
        done[item["key"]] = record
        found += record["arxiv"] is not None
        if n % 20 == 0 or n == len(todo):
            OUT.write_text(json.dumps(done, ensure_ascii=False, indent=0, sort_keys=True))
            print(f"  searched {n}/{len(todo)}, paper found for {found}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
