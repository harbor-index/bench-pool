#!/usr/bin/env python3
"""Fetch popularity signals for every benchmark in the pool and keep their history.

For each benchmark, from the links it already has:
- GitHub repository  -> stars, forks, created, last push        (GITHUB_TOKEN)
- arXiv paper        -> citations, influential citations, date  (Semantic Scholar; S2_API_KEY optional)
- Hugging Face dataset -> likes, downloads                      (HF_TOKEN optional)

Appends one line per benchmark per run to data/signals.jsonl and never rewrites
old lines, so a later build can draw trends. A source that could not be read is
left out of the line: missing means "no data", never zero.

    python3 scripts/signals.py --limit 20         # try a few
    python3 scripts/signals.py                    # every source not asked in the last 7 days
    python3 scripts/signals.py --recheck-days 0   # everything

Keys are read from the environment, or from a `.env` file in the repository
root (git-ignored). They are sent only to the service they belong to and are
never printed or stored.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pool

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "signals.jsonl"
UA = "bench-pool (signals)"
GITHUB_RE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?]|$)", re.I)
ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})|10\.48550/arxiv\.(\d{4}\.\d{4,5})|huggingface\.co/papers/(\d{4}\.\d{4,5})", re.I)
HF_DATA_RE = re.compile(r"huggingface\.co/datasets/([\w.-]+/[\w.-]+)", re.I)
NOT_REPOS = {"orgs", "topics", "search", "features", "sponsors", "settings", "marketplace"}
# Repositories that list or host many benchmarks and are not any one benchmark's own.
SHARED_REPOS = {"evaleval/benchmark-saturation", "harbor-framework/harbor", "laude-institute/harbor",
                "laude-institute/terminal-bench", "openai/simple-evals", "openai/evals",
                "ukgovernmentbeis/inspect_evals"}
DISCOVERED = ROOT / "data" / "discovered_links.json"
AGGREGATORS = ("llm-stats.com", "artificialanalysis.ai", "evaleval", "paperswithcode.com")
PAGE_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", re.I)


def load_env(path: Path = ROOT / ".env") -> None:
    """KEY=value lines from .env into the environment, without overriding it."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            value = value.strip().strip("'\"")
            if value:
                os.environ.setdefault(key.strip(), value)


def get(url: str, headers: dict, data: bytes | None = None, tries: int = 3):
    """Parsed JSON, or None when the thing does not exist. Waits and retries on rate limits."""
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **headers})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as err:
            if err.code in (401, 404, 410, 451):   # gone, or gated/private
                return None
            if err.code in (403, 429) and attempt + 1 < tries:
                wait = int(err.headers.get("Retry-After") or 0) or 20 * (attempt + 1)
                time.sleep(min(wait, 90))
                continue
            raise
    return None


def own_repo(url: str) -> str | None:
    m = GITHUB_RE.search(url)
    if not m or m.group(1).lower() in NOT_REPOS:
        return None
    repo = f"{m.group(1)}/{m.group(2)}"
    return None if repo.lower() in SHARED_REPOS else repo


def targets(bench: dict, found: dict | None = None) -> dict:
    """What to look up for one benchmark, from its members' links and ids.

    Leaderboard links are skipped: an aggregator's page or data file is not the
    benchmark's repository. `found` holds links discovered on its project page.
    """
    repo = arxiv = hf = None
    for member in bench["members"]:
        if member["id"].startswith("arxiv-") and not arxiv:
            arxiv = member["id"][6:].replace("-", ".", 1)
        for link in member["links"]:
            url = link["url"]
            if link["kind"] == "leaderboard":
                continue
            repo = repo or own_repo(url)
            m = ARXIV_RE.search(url)
            if m and not arxiv:
                arxiv = next(g for g in m.groups() if g)
            m = HF_DATA_RE.search(url)
            if m and not hf:
                hf = m.group(1)
    found = found or {}
    return {"repo": repo or found.get("repo"), "arxiv": arxiv or found.get("arxiv"), "hf": hf}


def discover(benchmarks: list[dict]) -> dict[str, dict]:
    """For benchmarks with neither a repository nor an arXiv link, read their project
    page once and take the repository and paper it links to. Cached in DISCOVERED.

    A repository is taken only when its name resembles the benchmark's, or it is
    the one the page links most; shared repositories are never taken.
    """
    import difflib
    import urllib.request
    from collections import Counter
    cache = json.loads(DISCOVERED.read_text()) if DISCOVERED.exists() else {}
    changed = False
    for bench in benchmarks:
        if bench["key"] in cache:
            continue
        have = targets(bench)
        if have["repo"] and have["arxiv"]:
            continue
        pages = [l["url"] for m in bench["members"] for l in m["links"]
                 if l["kind"] in ("web", "paper") and not any(a in l["url"] for a in AGGREGATORS)
                 and "arxiv.org" not in l["url"] and "doi.org" not in l["url"]][:2]
        entry: dict = {"from": None}
        for url in pages:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (bench-pool signals)"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    html = resp.read(600000).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - a dead project page is common
                continue
            repos = Counter(r for r in (own_repo(u) for u in re.findall(r"https?://github\.com/[\w.-]+/[\w.-]+", html)) if r)
            papers = Counter(PAGE_ARXIV_RE.findall(html))
            if repos and not have["repo"]:
                key = re.sub(r"[^a-z0-9]", "", bench["key"])
                like = lambda r: difflib.SequenceMatcher(None, key, re.sub(r"[^a-z0-9]", "", r.split("/")[1].lower())).ratio()
                best = max(repos, key=lambda r: (like(r) >= 0.6, repos[r], like(r)))
                if like(best) >= 0.6 or (len(repos) == 1):
                    entry["repo"] = best
            if papers and not have["arxiv"] and len(papers) == 1:
                entry["arxiv"] = next(iter(papers))
            if entry.get("repo") or entry.get("arxiv"):
                entry["from"] = url
                break
        cache[bench["key"]] = entry
        changed = True
    if changed:
        DISCOVERED.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True))
    return cache


def github(repo: str, token: str) -> dict | None:
    d = get(f"https://api.github.com/repos/{repo}",
            {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    if not d or "stargazers_count" not in d:
        return None
    return {"repo": d["full_name"], "stars": d["stargazers_count"], "forks": d["forks_count"],
            "created": (d.get("created_at") or "")[:10], "pushed": (d.get("pushed_at") or "")[:10],
            "archived": bool(d.get("archived"))}


def semantic_scholar(ids: list[str], key: str | None) -> dict[str, dict]:
    """{arxiv id: {...}} for the ids Semantic Scholar knows, 400 per request."""
    out: dict[str, dict] = {}
    headers = {"Content-Type": "application/json", **({"x-api-key": key} if key else {})}
    fields = "citationCount,influentialCitationCount,publicationDate,venue"
    for i in range(0, len(ids), 400):
        chunk = ids[i:i + 400]
        body = json.dumps({"ids": ["ARXIV:" + a for a in chunk]}).encode()
        # Without a key the shared limit is hit often; wait it out rather than give up.
        rows = get(f"https://api.semanticscholar.org/graph/v1/paper/batch?fields={fields}", headers, body,
                   tries=3 if key else 8) or []
        for axv, row in zip(chunk, rows):
            if row:
                out[axv] = {"citations": row.get("citationCount"), "influential": row.get("influentialCitationCount"),
                            "published": row.get("publicationDate"), "venue": row.get("venue") or None}
        time.sleep(1.1 if key else 3)
    return out


def hugging_face(dataset: str, token: str | None) -> dict | None:
    d = get(f"https://huggingface.co/api/datasets/{dataset}", {"Authorization": f"Bearer {token}"} if token else {})
    if not d or "likes" not in d:
        return None
    return {"dataset": d.get("id") or dataset, "likes": d["likes"], "downloads": d.get("downloads"),
            "gated": bool(d.get("gated")), "private": bool(d.get("private"))}


def last_tried() -> dict[str, dict[str, str]]:
    """{benchmark key: {source: date it was last asked}} from the lines already written."""
    seen: dict[str, dict[str, str]] = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                for source in row.get("tried", []):
                    mine = seen.setdefault(row["key"], {})
                    mine[source] = max(mine.get(source, ""), row["date"])
    return seen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, help="fetch at most N benchmarks")
    parser.add_argument("--recheck-days", type=int, default=7)
    args = parser.parse_args()
    load_env()
    gh_token, s2_key, hf_token = (os.environ.get(k) for k in ("GITHUB_TOKEN", "S2_API_KEY", "HF_TOKEN"))

    today = dt.date.today().isoformat()
    cutoff = (dt.date.today() - dt.timedelta(days=args.recheck_days)).isoformat()
    seen = last_tried()
    benchmarks = pool.load()[3]
    found = discover(benchmarks)
    print(f"project pages read for missing links: {sum(bool(v.get('from')) for v in found.values())} of {len(found)} gave a repository or paper", flush=True)
    usable = {"repo": bool(gh_token), "arxiv": True, "hf": True}
    source_of = {"repo": "github", "arxiv": "s2", "hf": "hf"}
    wanted: dict[str, dict] = {}
    todo = []
    for bench in benchmarks:
        # Ask a source again only when it was last asked more than --recheck-days ago.
        # A source skipped for a missing key was not asked, so it is due next time.
        due = {kind: value for kind, value in targets(bench, found.get(bench["key"])).items()
               if value and usable[kind] and seen.get(bench["key"], {}).get(source_of[kind], "") <= cutoff
               and seen.get(bench["key"], {}).get(source_of[kind]) != today}
        if due:
            wanted[bench["key"]] = {"repo": None, "arxiv": None, "hf": None, **due}
            todo.append(bench)
    if args.limit:
        todo = todo[: args.limit]
        wanted = {b["key"]: wanted[b["key"]] for b in todo}
    print(f"{len(benchmarks)} benchmarks, {len(todo)} to fetch: "
          f"{sum(bool(t['repo']) for t in wanted.values())} repos, "
          f"{sum(bool(t['arxiv']) for t in wanted.values())} arXiv papers, "
          f"{sum(bool(t['hf']) for t in wanted.values())} HF datasets", flush=True)
    if not gh_token:
        print("GITHUB_TOKEN not set: GitHub is skipped (unauthenticated calls are limited to 60 an hour)", file=sys.stderr)

    papers: dict[str, dict] = {}
    ids = sorted({t["arxiv"] for t in wanted.values() if t["arxiv"]})
    s2_ok = True
    try:
        papers = semantic_scholar(ids, s2_key)
    except Exception as err:  # noqa: BLE001 - the other sources still run
        s2_ok = False
        print(f"Semantic Scholar failed, its papers stay due: {err}", file=sys.stderr)

    counts = {"github": 0, "s2": 0, "hf": 0, "errors": 0}
    with OUT.open("a") as fh:
        for n, bench in enumerate(todo, 1):
            want = wanted[bench["key"]]
            row = {"key": bench["key"], "date": today, "tried": []}
            try:
                if want["repo"]:
                    found = github(want["repo"], gh_token)
                    row["tried"].append("github")
                    if found:
                        row["github"] = found
                if want["hf"]:
                    found = hugging_face(want["hf"], hf_token)
                    row["tried"].append("hf")
                    if found:
                        row["hf"] = found
            except Exception as err:  # noqa: BLE001 - keep what was read, move on
                counts["errors"] += 1
                print(f"  {bench['name']}: {err}", file=sys.stderr, flush=True)
            if want["arxiv"] and s2_ok:
                row["tried"].append("s2")
                if want["arxiv"] in papers:
                    row["s2"] = dict(papers[want["arxiv"]], arxiv=want["arxiv"])
            if not row["tried"]:
                continue
            for source in ("github", "s2", "hf"):
                counts[source] += source in row
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            if n % 100 == 0:
                print(f"  {n}/{len(todo)}", flush=True)
    print(f"done: github {counts['github']}, semantic scholar {counts['s2']}, hugging face {counts['hf']}, "
          f"errors {counts['errors']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
