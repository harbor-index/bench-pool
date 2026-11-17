#!/usr/bin/env python3
"""Our own discovery sources, next to Benchmark Radar.

Each connector writes the day's records in the same shape as a Radar snapshot
({"evidence_items": [...]}), so scripts/candidates.py treats them exactly like
Radar records: the same rules, the same merging, the same gate. Records that
could never pass the rules are not written.

arXiv and HF Daily Papers can be fetched again for any past date, so they go to
data/raw/sources/ (git-ignored, cached by the workflow; `--days N` rebuilds
them). GitHub, blogs and HF Datasets only answer for a current window, so their
files are the only history and are committed under data/sources/.

Connectors
  arxiv   arXiv API: cs.* papers with a benchmark word in the title, or a
          benchmark about agents in the abstract, submitted on the day
  hf      Hugging Face Daily Papers for the day (with upvotes), and new datasets
          named *bench* that cite a paper or have likes
  github  repositories created in the last 30 days that look like a benchmark
          and have at least 10 stars
  blogs   lab and evaluation-group blog feeds; only posts that talk about a
          benchmark or an evaluation

OpenReview is not here: its API now answers anonymous clients with a
verification challenge, and we do not get around such checks. NeurIPS
Datasets & Benchmarks papers are nearly all on arXiv as well.

    python3 scripts/sources.py                  # every missing day since START, and redo the last two
    python3 scripts/sources.py --days 30        # window connectors: date items by creation (backfill)
    python3 scripts/sources.py --only arxiv,hf  # some connectors
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sources"            # window connectors: history exists only here, so committed
RAW = ROOT / "data" / "raw" / "sources"     # per-day connectors: can be fetched again for any date, so cached
REFETCHABLE = {"arxiv", "hf_papers"}
START = dt.date(2026, 10, 18)               # first day our own connectors cover
UA = "bench-pool/0.1 (benchmark discovery; https://github.com/harbor-index/bench-pool)"
SUMMARY_CHARS = 1500

sys.path.insert(0, str(Path(__file__).resolve().parent))
from candidates import AGENT_TITLE_RE  # noqa: E402  same agent words as the Radar rule


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


# ---------------------------------------------------------------- tagging
# The same two tags Radar gives: "benchmark" and "agentic". candidates.py's rule
# then keeps a record that is a benchmark and about agents, or that has traction.
BENCH_TITLE_RE = re.compile(r"bench|\barena\b|\bgym\b|testbed|leaderboard|evaluation suite|\bevals?\b|\bexam\b", re.I)
BENCH_ABS_RE = re.compile(r"\b(?:we|this paper|this work)\s+(?:introduce|present|propose|release|build|construct|curate)s?\b[^.]{0,120}\b(?:benchmark|evaluation suite|testbed|environment|leaderboard)", re.I)
AGENT_ABS_RE = re.compile(r"\b(?:llm|ai|language[- ]model|coding|web|gui|computer[- ]use|research|software)[- ]agents?\b|\bagentic\b|tool[- ](?:use|calling)|computer[- ]use|function[- ]calling|\bMCP\b", re.I)


def tag(title: str, summary: str) -> list[str]:
    cats = []
    if BENCH_TITLE_RE.search(title) or BENCH_ABS_RE.search(summary or ""):
        cats.append("benchmark")
    if AGENT_TITLE_RE.search(title) or (cats and AGENT_ABS_RE.search(summary or "")):
        cats.append("agentic")
    return cats


def record(source: str, title: str, url: str, summary: str = "", published: str | None = None, authors=None,
           orgs=None, links=None, metrics=None, tags=None) -> dict:
    title = re.sub(r"\s+", " ", title or "").strip()
    summary = re.sub(r"\s+", " ", summary or "").strip()
    return {
        "source": source, "title": title, "url": url, "summary": summary[:SUMMARY_CHARS],
        "published_at": published, "authors": list(authors or [])[:12], "organizations": list(orgs or []),
        "artifact_urls": [u for u in (links or []) if u and u != url], "metrics": metrics or {},
        "categories": tag(title, summary), "source_tags": list(tags or []), "event_kind": "released",
    }


# ---------------------------------------------------------------- http
def get(url: str, headers: dict | None = None, tries: int = 3, timeout: int = 60) -> bytes:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001  network errors of every kind: retry, then give up
            if i == tries - 1:
                raise
            time.sleep(5 * (i + 1))
            last = exc  # noqa: F841
    return b""


def get_json(url: str, headers: dict | None = None):
    return json.loads(get(url, headers))


# ---------------------------------------------------------------- arXiv
ARXIV_CATS = ["cs.AI", "cs.CL", "cs.LG", "cs.SE", "cs.MA", "cs.CV", "cs.RO", "cs.CR", "cs.IR", "cs.HC"]
ATOM = "{http://www.w3.org/2005/Atom}"


def arxiv(day: dt.date) -> list[dict]:
    cats = " OR ".join(f"cat:{c}" for c in ARXIV_CATS)
    words = "ti:benchmark OR ti:bench OR ti:arena OR ti:gym OR ti:testbed OR ti:leaderboard OR " \
            "(abs:benchmark AND (abs:agent OR abs:agents OR abs:agentic))"
    d = day.strftime("%Y%m%d")
    query = f"({cats}) AND ({words}) AND submittedDate:[{d}0000 TO {d}2359]"
    out, start = [], 0
    while True:
        url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
            {"search_query": query, "start": start, "max_results": 200, "sortBy": "submittedDate"})
        root = ET.fromstring(get(url))
        entries = root.findall(ATOM + "entry")
        for e in entries:
            aid = re.sub(r"v\d+$", "", (e.findtext(ATOM + "id") or "").rsplit("/abs/", 1)[-1])
            if not aid:
                continue
            links = [l.get("href") for l in e.findall(ATOM + "link") if l.get("title") == "pdf"]
            out.append(record("arXiv API", e.findtext(ATOM + "title"), f"https://arxiv.org/abs/{aid}",
                              e.findtext(ATOM + "summary"), e.findtext(ATOM + "published"),
                              [a.findtext(ATOM + "name") for a in e.findall(ATOM + "author")], links=links,
                              tags=[c.get("term") for c in e.findall(ATOM + "category")][:6]))
        total = int(root.findtext("{http://a9.com/-/spec/opensearch/1.1/}totalResults") or 0)
        start += len(entries)
        time.sleep(3.1)                       # arXiv asks for one request every three seconds
        if not entries or start >= total:
            return out


# ---------------------------------------------------------------- Hugging Face
def hf_headers() -> dict:
    tok = os.environ.get("HF_TOKEN")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


def hf(day: dt.date) -> list[dict]:
    out = []
    papers = get_json(f"https://huggingface.co/api/daily_papers?date={day.isoformat()}&limit=100", hf_headers())
    for item in papers:
        p = item.get("paper") or {}
        pid = p.get("id")
        if not pid:
            continue
        links = [f"https://arxiv.org/abs/{pid}", p.get("githubRepo"), p.get("projectPage")]
        out.append(record("HF Daily Papers", p.get("title"), f"https://huggingface.co/papers/{pid}", p.get("summary"),
                          p.get("publishedAt"), [a.get("name") for a in p.get("authors") or []],
                          links=links, metrics={"upvotes": p.get("upvotes") or 0}))
    return out


def hf_datasets(since: dt.date) -> list[dict]:
    out = []
    url = "https://huggingface.co/api/datasets?" + urllib.parse.urlencode(
        {"search": "bench", "sort": "createdAt", "direction": -1, "limit": 500, "full": "true"})
    for d in get_json(url, hf_headers()):
        created = (d.get("createdAt") or "")[:10]
        if created and created < since.isoformat():
            continue
        tags = d.get("tags") or []
        arx = [t.split(":", 1)[1] for t in tags if t.startswith("arxiv:")]
        likes = d.get("likes") or 0
        if not arx and likes < 3:             # most new *bench* datasets are personal copies
            continue
        card = (d.get("cardData") or {}).get("pretty_name") or ""
        desc = d.get("description") or card
        out.append(record("HF Datasets", d["id"], f"https://huggingface.co/datasets/{d['id']}", desc, d.get("createdAt"),
                          links=[f"https://arxiv.org/abs/{a}" for a in arx],
                          metrics={"likes": likes, "downloads": d.get("downloads") or 0}))
    return out


# ---------------------------------------------------------------- GitHub
GITHUB_QUERIES = [
    "bench in:name", "benchmark in:name,description", "topic:benchmark", "topic:benchmarks",
    "topic:evaluation topic:llm", "topic:llm-evaluation", "topic:agent-benchmark",
]


def github(since: dt.date) -> list[dict]:
    tok = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {tok}"} if tok else {})}
    seen, out = set(), []
    for q in GITHUB_QUERIES:
        for page in (1, 2, 3):
            url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
                {"q": f"{q} created:>={since.isoformat()} stars:>=10", "sort": "stars", "per_page": 100, "page": page})
            items = get_json(url, headers).get("items") or []
            for r in items:
                if r["full_name"] in seen or r.get("fork"):
                    continue
                seen.add(r["full_name"])
                topics = r.get("topics") or []
                summary = (r.get("description") or "") + (" Topics: " + ", ".join(topics) if topics else "")
                out.append(record("GitHub search", r["full_name"], r["html_url"], summary, r.get("created_at"),
                                  orgs=[r["owner"]["login"]], links=[r.get("homepage")],
                                  metrics={"stars": r.get("stargazers_count") or 0}, tags=topics[:8]))
            time.sleep(2.5)                   # search API: 30 requests a minute with a token
            if len(items) < 100:
                break
    return out


# ---------------------------------------------------------------- blogs
FEEDS = {
    "OpenAI": "https://openai.com/news/rss.xml",
    "Anthropic": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
    "Anthropic research": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_research.xml",
    "Google Research": "https://research.google/blog/rss/",
    "Hugging Face": "https://huggingface.co/blog/feed.xml",
    "METR": "https://metr.org/feed.xml",
    "Ai2": "https://allenai.org/rss.xml",
    "Microsoft Research": "https://www.microsoft.com/en-us/research/feed/",
    "Apple ML": "https://machinelearning.apple.com/rss.xml",
    "BAIR": "https://bair.berkeley.edu/blog/feed.xml",
    "Stanford CRFM": "https://crfm.stanford.edu/feed.xml",
    "Together AI": "https://www.together.ai/blog/rss.xml",
    "Epoch AI": "https://epochai.substack.com/feed",
    "Mistral": "https://mistral.ai/rss.xml",
    "Qwen": "https://qwenlm.github.io/blog/index.xml",
    "NVIDIA": "https://blogs.nvidia.com/feed/",
    "Latent Space": "https://www.latent.space/feed",
}
BLOG_RE = re.compile(r"bench|\bevals?\b|evaluation|leaderboard|\barena\b|testbed|\bgym\b", re.I)


def _date(text: str | None) -> str | None:
    if not text:
        return None
    try:
        return email.utils.parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError):
        return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else None


def blogs(since: dt.date) -> list[dict]:
    out = []
    for org, url in FEEDS.items():
        try:
            root = ET.fromstring(get(url, tries=2, timeout=30))
        except Exception as exc:  # noqa: BLE001  one broken feed must not stop the others
            print(f"  blogs: {org} skipped ({str(exc)[:60]})", file=sys.stderr)
            continue
        for e in root.findall(".//item") + root.findall(f".//{ATOM}entry"):
            title = e.findtext("title") or e.findtext(f"{ATOM}title") or ""
            link = e.findtext("link") or ""
            if not link:
                el = e.find(f"{ATOM}link")
                link = el.get("href") if el is not None else ""
            desc = re.sub(r"<[^>]+>", " ", e.findtext("description") or e.findtext(f"{ATOM}summary") or e.findtext(f"{ATOM}content") or "")
            day = _date(e.findtext("pubDate") or e.findtext(f"{ATOM}published") or e.findtext(f"{ATOM}updated"))
            if not day or day < since.isoformat() or not link:
                continue
            if not BLOG_RE.search(title + " " + desc[:600]):
                continue
            rec = record(f"Blog: {org}", title, link.strip(), desc, day, orgs=[org])
            if "benchmark" not in rec["categories"]:      # passed the evaluation-word filter above
                rec["categories"].insert(0, "benchmark")
            out.append(rec)
    return out


# ---------------------------------------------------------------- main
def can_pass(rec: dict) -> bool:
    """Only keep what candidates.py's rule could ever let in: tagged, or with traction."""
    from candidates import TRACTION
    m = rec.get("metrics") or {}
    return bool(rec["categories"]) or any((m.get(k) or 0) >= bar for k, bar in TRACTION.items())


def write(name: str, day: dt.date, items: list[dict]) -> int:
    items = [r for r in items if can_pass(r)]
    path = (RAW if name in REFETCHABLE else OUT) / name / f"{day.isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ",\n".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) for r in items)
    path.write_text(f'{{"connector":"{name}","date":"{day.isoformat()}","evidence_items":[\n{body}\n]}}\n')
    return len(items)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=2, help="per-day connectors: how many days back (default 2)")
    ap.add_argument("--only", default="arxiv,hf,github,blogs", help="comma-separated connectors")
    ap.add_argument("--redo", action="store_true", help="fetch days that already have a file again")
    args = ap.parse_args()
    load_env()
    only = set(args.only.split(","))
    today = dt.datetime.now(dt.timezone.utc).date()
    since = today - dt.timedelta(days=args.days - 1)
    # Per-day connectors fill every day since START that has no file (the cache may have been
    # cleared), and always fetch the last two days again, which may still be growing.
    days = [START + dt.timedelta(days=i) for i in range((today - START).days + 1)]
    failed = 0

    def run(name, day, fn, *a):
        nonlocal failed
        path = (RAW if name in REFETCHABLE else OUT) / name / f"{day.isoformat()}.json"
        if path.exists() and not args.redo and day < today - dt.timedelta(days=1):
            return
        try:
            n = write(name, day, fn(*a))
            print(f"  {name} {day}: {n} records")
        except Exception as exc:  # noqa: BLE001  report and carry on with the other connectors
            failed += 1
            print(f"  {name} {day}: FAILED {str(exc)[:100]}", file=sys.stderr)

    def run_window(name, fn, *a):
        # Window connectors return everything in a 7-30 day window. Keep only what no earlier
        # file has, so the repository grows by new items only and "first seen" stays true.
        # A backfill (--days > 2) dates each item by when it was created instead of today.
        nonlocal failed
        try:
            items = fn(*a)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  {name}: FAILED {str(exc)[:100]}", file=sys.stderr)
            return
        known = set()
        for f in (OUT / name).glob("*.json") if (OUT / name).exists() else []:
            if f.stem != today.isoformat():
                known.update(r["url"] for r in json.loads(f.read_text())["evidence_items"])
        fresh = [r for r in items if r["url"] not in known]
        by_day: dict[str, list] = {}
        for r in fresh:
            d = (r.get("published_at") or "")[:10] if args.days > 2 else today.isoformat()
            d = max(d or today.isoformat(), since.isoformat())
            by_day.setdefault(d, []).append(r)
        for d, rs in sorted(by_day.items()):
            write(name, dt.date.fromisoformat(d), rs)
        print(f"  {name}: {len(fresh)} new of {len(items)} in the window, over {len(by_day)} day files")

    for day in days:
        if "arxiv" in only:
            run("arxiv", day, arxiv, day)
        if "hf" in only:
            run("hf_papers", day, hf, day)
    # Window connectors: one file per run, covering the window.
    if "hf" in only:
        run_window("hf_datasets", hf_datasets, min(since, today - dt.timedelta(days=30)))
    if "github" in only:
        run_window("github", github, today - dt.timedelta(days=30))
    if "blogs" in only:
        run_window("blogs", blogs, min(since, today - dt.timedelta(days=7)))
    return 1 if failed and failed >= len(only) * 2 else 0


if __name__ == "__main__":
    sys.exit(main())
