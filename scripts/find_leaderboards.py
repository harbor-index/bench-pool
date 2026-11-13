#!/usr/bin/env python3
"""Look for each benchmark's own public leaderboard and read its top score.

For every benchmark in the pool this script starts from the links Radar gives
(arXiv, GitHub, project page, Hugging Face) and looks in four places:

1. the paper's metadata: arXiv comment line, links in the abstract, and the
   Hugging Face paper page (linked GitHub repo, project page, datasets, spaces);
   a benchmark with no arXiv id is looked up on Hugging Face Papers by name and
   accepted only if the paper title starts with exactly that name
2. the GitHub repository's README
3. the project page, and pages it links to as its leaderboard
4. Hugging Face dataset cards and spaces

Papers with Code is not searched: the site was closed in 2025 and every address
now redirects to Hugging Face's trending papers.

A page that never says "leaderboard" is not read further. Pages that do are
handed to a model (`claude -p`), which answers whether the page shows a
leaderboard for this benchmark and quotes the top row. A score is kept only if
the quoted words are really on the page and contain both the number and the
system's name; anything else is recorded as "leaderboard exists, score not read"
with the reason. Nothing is ever filled in from the model's memory.

Results go to data/leaderboard_search.jsonl (one line per benchmark, newest
line wins). A run searches benchmarks that have no line yet, then re-checks
lines older than --recheck-days.

    python3 scripts/find_leaderboards.py --limit 20      # try a few
    python3 scripts/find_leaderboards.py                 # new + due for re-check
    python3 scripts/find_leaderboards.py --only swebench # one benchmark, forced
    python3 scripts/find_leaderboards.py --report        # counts only
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path

import llm
import pool
from leaderboards import norm_name

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "leaderboard_search.jsonl"
PAGES = ROOT / "data" / "raw" / "pages"
SEARCH_VERSION = 1
UA = "bench-pool-mvp (leaderboard search)"
MAX_PAGES = 10          # pages read per benchmark
MAX_BYTES = 3_000_000   # per page
PAGE_CHARS = 10_000     # per page, sent to the model
TOTAL_CHARS = 36_000    # per benchmark, sent to the model

LB_RE = re.compile(r"leader[\s-]?board|排行榜", re.I)
HOME_RE = re.compile(r"project\s*page|website|home\s*page|homepage|\bsite\b", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"'\]\)}|`]+")
ARXIV_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|huggingface\.co/papers/)(\d{4}\.\d{4,5})", re.I)
DATA_FILE_RE = re.compile(r"""["'(]([^"'()\s]*(?:leaderboard|results?|scores?)[^"'()\s]*\.(?:json|csv|tsv))["')]""", re.I)
SKIP_HOSTS = ("arxiv.org", "doi.org", "shields.io", "twitter.com", "youtube.com", "youtu.be",
              "linkedin.com", "openreview.net", "semanticscholar.org", "scholar.google", "discord.",
              "slack.com", "creativecommons.org", "fonts.g", "googletagmanager", "wikipedia.org",
              "colab.research.google.com", "medium.com", "paperswithcode.com", "llm-stats.com",
              "artificialanalysis.ai", "pypi.org", "docker.com", "anonymous.4open.science")
SKIP_EXT = re.compile(r"\.(png|jpe?g|gif|svg|webp|pdf|zip|gz|tar|mp4|mov|ico|css|js|bib|ipynb|parquet)(\?|$)", re.I)

PROMPT = """You check whether a benchmark has its OWN PUBLIC LEADERBOARD and, if so, read the top entry. You are given excerpts of pages belonging to the benchmark (its repository README, project page, Hugging Face pages, data files). Use ONLY the text given. Never use what you remember about the benchmark. Do not use tools. Reply with one JSON object and nothing else.

BENCHMARK: {name}
PAPER TITLE: {title}

A leaderboard counts when a page presents a ranked table or list of several systems scored on THIS benchmark and calls it a leaderboard (or ranking/排行榜), or links to such a page or site for this benchmark. These do NOT count: a results or ablation table that is not presented as a leaderboard; a leaderboard of a different benchmark that the page merely mentions or builds on; a promise that a leaderboard is "coming soon"; a table of this benchmark's task statistics.

Return:
- "leaderboard": "yes" if a leaderboard for this benchmark is shown or linked, "no" if the pages give no sign of one, "unclear" if you cannot tell
- "leaderboard_url": the address of the leaderboard as written in the text (the page it is on, or the link it points to), or null
- "page": the number of the page ([P1], [P2] ...) that shows the leaderboard rows, or null if only a link was found
- "entries": how many systems the visible leaderboard lists (a number), or null
- "score": the top system's score on the leaderboard's MAIN metric (its overall / headline / default-sort column), as the number written on the page. null if no rows are visible, if the excerpt is cut before you can be sure which row is best, if several tracks or metrics compete with no clear main one, or if anything else is ambiguous. Never compute, average or guess.
  Reference rows are not systems: skip rows for humans, experts, an oracle, a random or upper-bound baseline, and take the best real system below them.
  If the visible table covers only part of the benchmark (one tier, split, track, tab or "Lite" subset) and no overall table is visible, score is null.
- "model": the top system's name exactly as written, or null
- "metric": the metric's name as written (1-4 words), or null
- "unit": "percent" for a rate or score on a 0-100 scale (success rate, accuracy, pass rate; e.g. 45.2 or 45.2%), "fraction" for the same on a 0-1 scale, or "other" for everything else (Elo, points, reward, dollars, time, rank, and any gain, improvement or difference such as +12.5%)
- "higher_better": true or false
- "quote": the exact text of the row or sentence that contains BOTH the top system's name and that score, copied character for character from the page (at most 300 characters), or null
- "note": at most 20 words. If score is null, say why (e.g. "table is rendered by script, no rows in text", "three tracks, no overall").

PAGES
"""


# ---------------------------------------------------------------- fetching

_host_lock = threading.Lock()
_host_next: dict[str, float] = {}
# Hugging Face allows 500 API calls and 50 paper searches per 5 minutes.
_host_gap = {"huggingface.co": 0.65, "huggingface.co/api/papers/search": 6.2, "export.arxiv.org": 3.1, "arxiv.org": 1.0, "raw.githubusercontent.com": 0.05}


def _wait(host: str) -> None:
    gap = _host_gap.get(host, 0.25)
    with _host_lock:
        now = time.time()
        start = max(now, _host_next.get(host, 0))
        _host_next[host] = start + gap
    if start > now:
        time.sleep(start - now)


def fetch(url: str, max_age_days: float, accept_json: bool = False) -> dict:
    """GET a page through the on-disk cache. Returns {"url", "status", "final", "body"}.
    status is 200, an HTTP error code, or "error: ..."."""
    PAGES.mkdir(parents=True, exist_ok=True)
    path = PAGES / (hashlib.sha1(url.encode()).hexdigest() + ".json")
    if path.exists() and (time.time() - path.stat().st_mtime) < max_age_days * 86400:
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    host = urllib.parse.urlparse(url).netloc.lower()
    if "huggingface.co/api/papers/search" in url:
        host = "huggingface.co/api/papers/search"
    out = {"url": url, "status": None, "final": url, "body": ""}
    for attempt in range(4):
        _wait(host)
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": "application/json" if accept_json else "text/html,text/plain,*/*"})
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read(MAX_BYTES + 1)
                ctype = resp.headers.get("Content-Type", "")
                out["final"] = resp.geturl()
                out["status"] = 200
                if not re.search(r"text|json|xml|csv|javascript", ctype, re.I) and b"\x00" in raw[:2000]:
                    out["status"] = "error: not text"
                else:
                    charset = (re.search(r"charset=([\w-]+)", ctype) or [None, "utf-8"])[1]
                    try:
                        out["body"] = raw[:MAX_BYTES].decode(charset, "replace")
                    except LookupError:
                        out["body"] = raw[:MAX_BYTES].decode("utf-8", "replace")
                    out["cut"] = len(raw) > MAX_BYTES
            break
        except urllib.error.HTTPError as err:
            out["status"] = err.code
            if err.code in (429, 500, 502, 503) and attempt < 3:
                wait = err.headers.get("Retry-After", "") if err.headers else ""
                time.sleep(min(int(wait) + 2, 310) if wait.isdigit() else 8 * (attempt + 1))
                continue
            break
        except Exception as err:  # noqa: BLE001 - timeouts, DNS, TLS, bad URLs
            out["status"] = f"error: {type(err).__name__}"
            if attempt < 1:
                continue
            break
    # Do not cache "try again later" answers.
    if out["status"] == 200 or out["status"] in (401, 403, 404, 410):
        path.write_text(json.dumps(out, ensure_ascii=False))
    return out


class _Text(HTMLParser):
    """HTML to plain text. Table rows become "a | b | c" lines; links are collected."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.links: list[tuple[str, str]] = []
        self._skip = 0
        self._href: str | None = None
        self._anchor: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg", "template"):
            self._skip += 1
        elif tag in ("td", "th"):
            self.out.append(" | ")
        elif tag in ("tr", "p", "div", "br", "li", "h1", "h2", "h3", "h4", "section", "table"):
            self.out.append("\n")
        elif tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg", "template"):
            self._skip = max(0, self._skip - 1)
        elif tag == "a" and self._href:
            self.links.append((" ".join("".join(self._anchor).split()), self._href))
            self._href = None
        elif tag in ("tr", "h1", "h2", "h3", "h4"):
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)
            if self._href is not None:
                self._anchor.append(data)


def to_text(body: str, base: str) -> tuple[str, list[tuple[str, str]]]:
    """Returns (plain text, [(anchor text, absolute url)]). Handles HTML and Markdown."""
    links: list[tuple[str, str]] = []
    looks_html = bool(re.search(r"<(html|body|div|table|head)\b", body[:5000], re.I))
    if looks_html:
        parser = _Text()
        try:
            parser.feed(body)
        except Exception:  # noqa: BLE001 - broken markup
            pass
        text = "".join(parser.out)
        links = parser.links
    else:
        text = body
        links = [(m.group(1), m.group(2).split()[0]) for m in re.finditer(r"\[([^\]]*)\]\(([^)\s]+[^)]*)\)", body)]
        # badges: [![Website](image)](address)
        links += [(m.group(1), m.group(2)) for m in re.finditer(r"\[!\[([^\]]*)\]\([^)]*\)\]\(([^)\s]+)\)", body)]
        links += [(re.sub(r"<[^>]+>", " ", m.group(2)), m.group(1))
                  for m in re.finditer(r"""<a\s[^>]*href=["']([^"']+)["'][^>]*>(.*?)</a>""", body, re.S | re.I)]
    seen = {u for _, u in links}
    links += [("", m.group(0).rstrip(".,;:")) for m in URL_RE.finditer(text) if m.group(0).rstrip(".,;:") not in seen]
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    absolute = []
    for anchor, href in links:
        href = html.unescape(href.strip())
        if href.startswith(("#", "mailto:", "javascript:")):
            continue
        try:
            absolute.append((anchor.strip(), urllib.parse.urljoin(base, href)))
        except ValueError:
            pass
    return text, absolute


def load_extra() -> dict[str, list[str]]:
    """Start links added by hand in data/extra_links.json, by benchmark key."""
    path = ROOT / "data" / "extra_links.json"
    if not path.exists():
        return {}
    return {pool.canon_key(name): urls for name, urls in json.loads(path.read_text()).get("links", {}).items()}


EXTRA = load_extra()


def github_repo(url: str) -> tuple[str, str] | None:
    m = re.match(r"https?://(?:www\.)?github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?(?:[/#?].*)?$", url.strip(), re.I)
    if not m or m.group(1).lower() in ("orgs", "topics", "sponsors", "features", "marketplace", "user-attachments"):
        return None
    return m.group(1), m.group(2)


def hf_repo(url: str) -> tuple[str, str] | None:
    """("datasets" | "spaces", "owner/name")"""
    m = re.match(r"https?://(?:www\.)?huggingface\.co/(datasets|spaces)/([\w.-]+/[\w.-]+)", url.strip(), re.I)
    return (m.group(1).lower(), m.group(2)) if m else None


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "", text.lower())


# ---------------------------------------------------------------- one benchmark

class Search:
    def __init__(self, bench: dict, max_age: float) -> None:
        self.bench = bench
        self.max_age = max_age
        self.name = bench["name"]
        self.name_key = norm_name(self.name)
        self.pages: list[dict] = []     # {"url", "kind", "text", "links"}
        self.tried: list[dict] = []     # {"url", "kind", "status"}
        self.done: set[str] = set()
        self.exists_hint: list[str] = []  # leaderboard addresses seen but not readable
        self.metadata_ok = False
        self.paper_read = False

    # -- helpers
    def mentions(self, text: str) -> bool:
        """Does the page talk about this benchmark by name?"""
        if len(self.name_key) < 5:
            return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(self.name) + r"(?![A-Za-z0-9])", text))
        return self.name_key in norm_name(text[:400_000])

    def add(self, url: str, kind: str, must_mention: bool = False) -> dict | None:
        key = re.sub(r"^https?://(www\.)?", "", url.split("#")[0]).rstrip("/").lower()
        if key in self.done or len(self.done) >= MAX_PAGES * 2 or len(self.pages) >= MAX_PAGES:
            return None
        self.done.add(key)
        got = fetch(url, self.max_age)
        self.tried.append({"url": url, "kind": kind, "status": got["status"]})
        if got["status"] != 200 or not got["body"].strip():
            return None
        if "paperswithcode.com" in url or "huggingface.co/papers/trending" in got["final"]:
            self.tried[-1]["status"] = "closed (Papers with Code)"
            return None
        text, links = to_text(got["body"], got["final"])
        # Pages drawn by script may carry the name only in their markup.
        if must_mention and not (self.mentions(text) or self.mentions(got["body"])):
            self.tried[-1]["status"] = "skipped: does not name the benchmark"
            return None
        page = {"url": url, "kind": kind, "text": text, "links": links, "raw": got["body"], "cut": got.get("cut", False)}
        self.pages.append(page)
        return page

    # -- places
    def readme(self, owner: str, repo: str, must_mention: bool = False) -> dict | None:
        for name in ("README.md", "readme.md", "README.rst", "README", "Readme.md", "README_EN.md"):
            raw = f"https://raw.githubusercontent.com/{owner}/{repo}/HEAD/{name}"
            got = fetch(raw, self.max_age)
            if got["status"] == 200 and got["body"].strip():
                key = f"github.com/{owner}/{repo}".lower()
                if key in self.done:
                    return None
                self.done.add(key)
                self.tried.append({"url": f"https://github.com/{owner}/{repo}", "kind": "GitHub README", "status": 200})
                text, links = to_text(got["body"], f"https://github.com/{owner}/{repo}/blob/HEAD/")
                if must_mention and not (self.mentions(text) or self.in_address(f"{owner}/{repo}")):
                    self.tried[-1]["status"] = "skipped: does not name the benchmark"  # someone else's repository
                    return None
                page = {"url": f"https://github.com/{owner}/{repo}", "kind": "GitHub README", "text": text,
                        "links": links, "raw": got["body"], "cut": got.get("cut", False)}
                self.pages.append(page)
                return page
            if isinstance(got["status"], str):  # network trouble, not a missing file
                break
        self.tried.append({"url": f"https://github.com/{owner}/{repo}", "kind": "GitHub README", "status": got["status"]})
        return None

    def hf_dataset(self, repo_id: str) -> dict | None:
        return self.add(f"https://huggingface.co/datasets/{repo_id}/raw/main/README.md", "Hugging Face dataset card")

    def hf_space(self, repo_id: str) -> None:
        info = fetch(f"https://huggingface.co/api/spaces/{repo_id}", self.max_age, accept_json=True)
        if info["status"] != 200:
            self.tried.append({"url": f"https://huggingface.co/spaces/{repo_id}", "kind": "Hugging Face space",
                               "status": info["status"]})
            return
        try:
            files = [s["rfilename"] for s in json.loads(info["body"]).get("siblings", [])]
        except ValueError:
            files = []
        if LB_RE.search(repo_id):
            self.exists_hint.append(f"https://huggingface.co/spaces/{repo_id}")
        wanted = [f for f in files if f == "README.md" or f == "index.html"]
        wanted += [f for f in files if re.search(r"(leaderboard|result|score)[^/]*\.(csv|json|jsonl|md|tsv)$", f, re.I)][:3]
        for name in wanted:
            self.add(f"https://huggingface.co/spaces/{repo_id}/raw/main/{urllib.parse.quote(name)}",
                     "Hugging Face space file")

    def route(self, url: str, kind: str, must_mention: bool) -> dict | None:
        """Fetch a link in the way its host needs."""
        url = url.strip().rstrip(".,;")
        host = urllib.parse.urlparse(url).netloc.lower()
        if not host or host in ("x.com", "www.x.com") or any(s in host for s in SKIP_HOSTS) or SKIP_EXT.search(url):
            return None
        hf = hf_repo(url)
        if hf:
            if hf[0] == "datasets":
                return self.hf_dataset(hf[1])
            self.hf_space(hf[1])
            return None
        if "huggingface.co" in host:
            return None
        blob = re.match(r"https?://github\.com/([\w.-]+)/([\w.-]+)/(?:blob|tree)/([^/]+)/(.+\.(?:md|csv|json|tsv))$", url, re.I)
        if blob:
            return self.add(f"https://raw.githubusercontent.com/{blob[1]}/{blob[2]}/{blob[3]}/{blob[4]}", kind, must_mention)
        repo = github_repo(url)
        if repo:
            return self.readme(*repo, must_mention=must_mention) if re.fullmatch(r"https?://(www\.)?github\.com/[\w.-]+/[\w.-]+?(\.git)?/?", url, re.I) else None
        if "github.com" in host or "raw.githubusercontent.com" in host:
            return None
        return self.add(url, kind, must_mention)

    def in_address(self, url: str) -> bool:
        return len(self.name_key) >= 5 and self.name_key in norm_name(url)

    def own_site(self, url: str) -> bool:
        """os-world.github.io is OSWorld's site; osworld-mcp.github.io is another benchmark's."""
        strip = lambda k: re.sub(r"(bench|benchmark|leaderboard|\d+)+$", "", k)
        parts = urllib.parse.urlparse(url)
        names = [parts.netloc.split(".")[0]] + [seg for seg in parts.path.split("/") if seg][:1]
        return len(self.name_key) >= 5 and strip(self.name_key) in {strip(norm_name(n)) for n in names}

    def follow(self, page: dict, depth: int) -> None:
        """From a page, follow links that claim to be the leaderboard or the project's home.

        A README often links its authors' homepages and other benchmarks'
        leaderboards, so a link is followed only if it is labelled as this
        project's site or leaderboard, and the page it leads to must name the
        benchmark. A leaderboard page is an end point: its own links (usually
        the host's other leaderboards) are not followed."""
        if depth > 2 or page["kind"] == "leaderboard link":
            return
        boards: list[str] = []
        homes: list[str] = []
        for anchor, href in page["links"]:
            if href.split("#")[0].rstrip("/") == page["url"].rstrip("/"):
                continue
            if LB_RE.search(anchor) or LB_RE.search(href):
                boards.append(href)
            elif page["kind"] in ("GitHub README", "Hugging Face dataset card") and (
                    HOME_RE.search(anchor) or (re.search(r"\.github\.io", href) and self.own_site(href))):
                homes.append(href)
        boards = sorted(dict.fromkeys(boards), key=lambda u: not self.in_address(u))[:3]
        for href in boards:
            self.route(href, "leaderboard link", must_mention=True)
        for href in list(dict.fromkeys(homes))[:2]:
            nxt = self.route(href, "project page", must_mention=True)
            if nxt:
                self.follow(nxt, depth + 1)
        # Tables drawn by script: pick up data files the page names.
        if page["kind"] == "project page" and LB_RE.search(page["raw"]):
            for m in list(DATA_FILE_RE.finditer(page["raw"]))[:2]:
                self.add(urllib.parse.urljoin(page["url"], m.group(1)), "leaderboard data file")

    def paper_links(self, axv: str) -> list[str]:
        """Links to the benchmark's own pages in the paper's full text (arXiv's HTML version).

        Many papers give their repository only in a first-page footnote. Kept:
        links before section 2 (title, abstract, introduction), and links anywhere
        whose address contains the benchmark's name. Reference-list links to
        other people's projects are thereby left out."""
        got = fetch(f"https://arxiv.org/html/{axv}", self.max_age)
        self.tried.append({"url": f"https://arxiv.org/html/{axv}", "kind": "paper full text", "status": got["status"]})
        if got["status"] != 200 or len(got["body"]) < 5000:
            return []
        self.paper_read = True
        body = got["body"]
        cut = body.find('id="S2"')
        front = cut if cut > 0 else len(body) // 4
        out: list[str] = []
        for m in re.finditer(r"https?://[^\s<>\"'\]\)}|`\\]+", body):
            url = html.unescape(m.group(0)).rstrip(".,;:")
            host = urllib.parse.urlparse(url).netloc.lower()
            if any(s in host for s in SKIP_HOSTS + ("w3.org", "mathjax", "jsdelivr", "latexml", "ar5iv", "cloudflare",
                                                    "googleapis", "gstatic", "orcid.org", "acm.org", "aclanthology",
                                                    "nist.gov", "purl.org", "schema.org", "springer", "ieee.org")):
                continue
            if re.search(r"github\.com/(arXiv|brucemiller)/", url, re.I) or SKIP_EXT.search(url):
                continue
            own_host = "github.com" in host or host.endswith("github.io") or "huggingface.co" in host
            if m.start() < front or (own_host and self.in_address(url)):
                out.append(url)
        return list(dict.fromkeys(out))[:5]

    # -- the search
    def run(self, arxiv_meta: dict[str, dict]) -> None:
        members = self.bench["members"]
        links: list[tuple[str, str]] = []
        arxiv_ids: list[str] = []
        for member in members:
            if member["id"].startswith("arxiv-"):
                arxiv_ids.append(member["id"][len("arxiv-"):].replace("-", ".", 1))
            for link in member["links"]:
                m = ARXIV_RE.search(link["url"])
                if m:
                    arxiv_ids.append(m.group(1))
                elif link["kind"] in ("code", "data", "space", "web"):
                    links.append((link["url"], "Radar link"))
            for url in URL_RE.findall(member["summary"] or ""):
                links.append((url.rstrip(".,;"), "link in abstract"))
        arxiv_ids = list(dict.fromkeys(arxiv_ids))[:2]
        for url in EXTRA.get(self.bench["key"], []):
            links.append((url, "link added by hand"))

        # 1. paper metadata
        if not arxiv_ids and len(self.name_key) >= 5:
            found = fetch("https://huggingface.co/api/papers/search?q=" + urllib.parse.quote(self.name),
                          self.max_age, accept_json=True)
            self.tried.append({"url": "huggingface.co/papers search: " + self.name, "kind": "paper lookup by name",
                               "status": found["status"]})
            if found["status"] == 200:
                try:
                    hits = json.loads(found["body"])
                except ValueError:
                    hits = []
                for hit in hits:
                    title = (hit.get("paper") or {}).get("title") or ""
                    head = re.split(r":| - | — ", title, maxsplit=1)[0]
                    if pool.canon_key(head) == self.bench["key"]:
                        arxiv_ids.append(hit["paper"]["id"])
                        self.metadata_ok = True
                        self.tried[-1]["status"] = f"matched arXiv {hit['paper']['id']}"
                        break
        for axv in arxiv_ids:
            meta = arxiv_meta.get(axv)
            if meta:
                self.metadata_ok = True
                for url in URL_RE.findall(meta.get("comment", "") + " " + meta.get("summary", "")):
                    links.append((url.rstrip(".,;"), "link in arXiv record"))
            paper = fetch(f"https://huggingface.co/api/papers/{axv}", self.max_age, accept_json=True)
            self.tried.append({"url": f"https://huggingface.co/papers/{axv}", "kind": "Hugging Face paper page",
                               "status": paper["status"]})
            if paper["status"] in (200, 404):
                self.metadata_ok = True
            if paper["status"] != 200:
                continue
            try:
                info = json.loads(paper["body"])
            except ValueError:
                continue
            for field in ("githubRepo", "projectPage"):
                if info.get(field):
                    links.append((info[field], "linked from Hugging Face paper page"))
            linked = {"datasets": info.get("linkedDatasets") or [], "spaces": info.get("linkedSpaces") or []}
            if (info.get("numTotalDatasets") or 0) > len(linked["datasets"]) or \
                    (info.get("numTotalSpaces") or 0) > len(linked["spaces"]):
                more = fetch(f"https://huggingface.co/api/arxiv/{axv}/repos", self.max_age, accept_json=True)
                if more["status"] == 200:
                    try:
                        body = json.loads(more["body"])
                        linked = {"datasets": body.get("datasets") or [], "spaces": body.get("spaces") or []}
                    except ValueError:
                        pass
            # Hundreds of repos can cite a paper; keep those named after the benchmark.
            for kind, cap in (("datasets", 2), ("spaces", 3)):
                named = [r["id"] for r in linked[kind] if len(self.name_key) >= 5 and self.name_key in norm_name(r["id"])]
                named.sort(key=lambda rid: (not LB_RE.search(rid), len(rid)))
                for rid in named[:cap]:
                    links.append((f"https://huggingface.co/{kind}/{rid}", "linked from Hugging Face paper page"))

        # 2-4. repository, project page, Hugging Face
        for url, kind in dict.fromkeys(links):
            repo = github_repo(url)
            hf = hf_repo(url)
            if repo and not hf:
                page = self.readme(*repo)
            elif hf:
                page = self.route(url, kind, must_mention=False)
            else:
                page = self.route(url, "project page", must_mention=False)
            if page:
                self.follow(page, 1)

        # Nothing found so far: read the paper itself for links to its own pages.
        if not self.pages:
            for axv in arxiv_ids[:1]:
                for url in self.paper_links(axv):
                    repo = github_repo(url)
                    page = self.readme(*repo, must_mention=True) if repo and not hf_repo(url) else \
                        self.route(url, "project page", must_mention=True)
                    if page:
                        self.follow(page, 1)


def excerpt(page: dict) -> str:
    """The parts of a page around the word leaderboard, within the size limit."""
    text = page["text"]
    if page["kind"] in ("leaderboard data file", "Hugging Face space file") and not page["url"].endswith((".md", ".html")):
        return text[:PAGE_CHARS] + ("\n[... file cut here ...]" if len(text) > PAGE_CHARS else "")
    spans: list[list[int]] = []
    for m in LB_RE.finditer(text):
        lo, hi = max(0, m.start() - 400), min(len(text), m.end() + 5000)
        if spans and lo <= spans[-1][1]:
            spans[-1][1] = hi
        else:
            spans.append([lo, hi])
    parts, used = [text[:300]], 300
    for lo, hi in spans:
        if used >= PAGE_CHARS:
            parts.append("[... page cut here ...]")
            break
        hi = min(hi, lo + PAGE_CHARS - used)
        parts.append(text[max(lo, 300 if lo < 300 else lo):hi])
        used += hi - lo
    return "\n[...]\n".join(p for p in parts if p.strip())


def ask(model: str, name: str, title: str, pages: list[dict], workdir: str) -> dict:
    body, used = [], 0
    for n, page in enumerate(pages, 1):
        chunk = excerpt(page)[: max(0, TOTAL_CHARS - used)]
        if not chunk:
            break
        used += len(chunk)
        body.append(f"[P{n}] {page['kind']}: {page['url']}\n{chunk}\n")
    text = llm.complete(PROMPT.replace("{name}", name).replace("{title}", title) + "\n".join(body),
                        "You are a careful data extractor. You reply with JSON only.")
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise RuntimeError(f"no JSON object in reply: {text[:200]!r}")
    return json.loads(match.group(0))


def judge(answer: dict, pages: list[dict]) -> dict:
    """Turn the model's answer into a result, keeping a score only if its quote checks out."""
    out: dict = {"note": str(answer.get("note") or "")[:200]}
    if answer.get("leaderboard") != "yes":
        out["status"] = "none" if answer.get("leaderboard") == "no" else "unclear"
        return out
    out["status"] = "listed"
    page_no = answer.get("page")
    if isinstance(page_no, str) and re.search(r"\d+", page_no):
        page_no = int(re.search(r"\d+", page_no).group(0))
    page = pages[page_no - 1] if isinstance(page_no, int) and 1 <= page_no <= len(pages) else None
    url = answer.get("leaderboard_url")
    seen = {p["url"] for p in pages} | {u for p in pages for _, u in p["links"]}
    blob = " ".join(p["text"] for p in pages)
    if isinstance(url, str) and re.match(r"https?://[\w-]+(\.[\w-]+)+", url) and (url in seen or url.rstrip("/") in blob):
        out["url"] = url
    elif page:
        out["url"] = page["url"]
    else:
        out["url"] = next((p["url"] for p in pages if LB_RE.search(p["text"])), pages[0]["url"])
    if isinstance(answer.get("entries"), (int, float)):
        out["entries"] = int(answer["entries"])

    score, quote, model = answer.get("score"), answer.get("quote"), answer.get("model")
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return out
    if not (isinstance(quote, str) and isinstance(model, str) and model.strip()):
        out["note"] = "score given without a quote or system name; not kept"
        return out
    number = f"{score:g}"
    where = [p for p in ([page] if page else []) + pages if squash(quote) and squash(quote) in squash(p["text"])]
    if not where:
        out["note"] = "quoted row is not on the page; score not kept"
        return out
    if number not in quote.replace(",", ""):
        out["note"] = "quoted row does not contain the score; not kept"
        return out
    if squash(model) not in squash(quote):
        out["note"] = "quoted row does not name the system; score not kept"
        return out
    if re.search(r"[+\u2212]\s*" + re.escape(number), quote.replace(",", "")):
        out["note"] = "top value is written as a signed change, not a level; not kept"
        return out
    if re.search(r"\b(oracle|human|expert|random|upper[- ]bound)\b", model, re.I):
        out["note"] = "top row is a reference (" + model.strip()[:40] + "), not a system; score not kept"
        return out
    unit = answer.get("unit") if answer.get("unit") in ("percent", "fraction", "other") else "other"
    higher = answer.get("higher_better") is not False
    pct = None
    if higher and unit == "percent" and 0 <= score <= 100:
        pct = round(float(score), 1)
    elif higher and unit == "fraction" and 0 <= score <= 1:
        pct = round(float(score) * 100, 1)
    out.update({
        "status": "found", "raw": float(score), "pct": pct, "unit": unit, "higher_better": higher,
        "model": model.strip()[:100], "metric": (str(answer.get("metric"))[:60] if answer.get("metric") else None),
        "quote": quote[:300], "quote_page": where[0]["url"],
    })
    if not page:
        out["url"] = out.get("url") or where[0]["url"]
    return out


def search_one(bench: dict, arxiv_meta: dict, args, workdir: str, today: str, old: dict | None) -> dict:
    s = Search(bench, args.recheck_days)
    s.run(arxiv_meta)
    row = {
        "key": bench["key"], "name": bench["name"], "search_version": SEARCH_VERSION, "checked": today,
        "pages_read": len(s.pages),
        "tried": [{"url": t["url"], "kind": t["kind"], "status": t["status"]} for t in s.tried][:20],
    }
    flagged = [p for p in s.pages if LB_RE.search(p["text"]) or p["kind"] in ("leaderboard link", "leaderboard data file")]
    row["paper_read"] = s.paper_read
    if not s.pages and not s.paper_read and not s.exists_hint:
        # Nothing of the benchmark's own could be opened, so nothing can be said.
        failed = [t for t in s.tried if t["status"] not in (200, 404) and not str(t["status"]).startswith(("matched", "skipped"))]
        row.update(status="unchecked", note=(
            "pages could not be opened" if failed else
            "paper record links no repository or project page, and its full text is not readable" if s.metadata_ok else
            "no paper, repository or project link to start from"))
    elif not flagged and not s.exists_hint:
        row.update(status="none", note="" if s.pages else "paper links no repository or project page")
    elif not flagged:
        row.update(status="listed", url=s.exists_hint[0], note="leaderboard space found; its scores are not in a readable file")
    else:
        # Leaderboard-looking pages first, so they survive the size limit.
        order = {"leaderboard link": 0, "leaderboard data file": 1, "Hugging Face space file": 2, "project page": 3,
                 "GitHub README": 5}
        flagged.sort(key=lambda p: order.get(p["kind"], 6))
        title = bench["members"][0]["title"]
        answer, err = None, ""
        for _ in (1, 2):
            try:
                answer = ask(args.model, bench["name"], title, flagged, workdir)
                break
            except Exception as exc:  # noqa: BLE001 - report and retry once
                err = str(exc)[:160]
        if answer is None:
            row.update(status="unchecked", note="model call failed: " + err)
        else:
            row.update(judge(answer, flagged))
            row["model_used"] = llm.model()
            if row["status"] == "none" and s.exists_hint:
                row.update(status="listed", url=s.exists_hint[0],
                           note="leaderboard space found; its scores are not in a readable file")
    if row["status"] in ("found", "listed"):
        row["first_found"] = (old or {}).get("first_found") or today
    return row


# ---------------------------------------------------------------- driver

def load_rows() -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("search_version") == SEARCH_VERSION:
                    rows[row["key"]] = row
    return rows


def arxiv_records(ids: list[str], max_age: float) -> dict[str, dict]:
    """arXiv comment line and abstract for many ids, 50 per request."""
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        got = fetch("http://export.arxiv.org/api/query?max_results=50&id_list=" + ",".join(chunk), max_age)
        if got["status"] != 200:
            print(f"  arXiv lookup failed ({got['status']}) for {len(chunk)} ids", file=sys.stderr, flush=True)
            continue
        for entry in re.findall(r"<entry>(.*?)</entry>", got["body"], re.S):
            ident = re.search(r"<id>https?://arxiv\.org/abs/(\d{4}\.\d{4,5})", entry)
            if not ident:
                continue
            grab = lambda tag: html.unescape((re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", entry, re.S) or [None, ""])[1])
            out[ident.group(1)] = {"comment": grab("arxiv:comment"), "summary": grab("summary")}
    return out


def report(rows: dict[str, dict], keys: set[str]) -> None:
    mine = [r for k, r in rows.items() if k in keys]
    by = Counter(r["status"] for r in mine)
    print(f"pool {len(keys)} benchmarks; searched {len(mine)}; never searched {len(keys) - len(mine)}")
    print(f"  own leaderboard, top score read : {by['found']}  (as a percentage: {sum(r.get('pct') is not None for r in mine)})")
    print(f"  own leaderboard, score not read : {by['listed']}")
    print(f"  searched, none found            : {by['none']}  "
          f"(of these, only the paper could be read; it links no page: {sum(r['status'] == 'none' and not r['pages_read'] for r in mine)})")
    print(f"  could not be checked            : {by['unchecked'] + by['unclear']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--recheck-days", type=float, default=7, help="search again after this many days")
    parser.add_argument("--limit", type=int, help="search at most N benchmarks")
    parser.add_argument("--only", help="search benchmarks whose key or name contains this text, even if fresh")
    parser.add_argument("--redo", default="", help="also search again benchmarks with these results, "
                        "comma-separated: found, listed, none, unchecked, unclear")
    parser.add_argument("--report", action="store_true", help="print counts and stop")
    args = parser.parse_args()

    _, _, _, benchmarks = pool.load()
    rows = load_rows()
    keys = {b["key"] for b in benchmarks}
    if args.report:
        report(rows, keys)
        return 0

    today = dt.datetime.now(dt.timezone.utc).date()
    due = lambda r: (today - dt.date.fromisoformat(r["checked"])).days >= args.recheck_days

    redo = {x.strip() for x in args.redo.split(",") if x.strip()}

    def wanted(b: dict) -> bool:
        row = rows.get(b["key"])
        if args.only:
            return args.only.lower() in b["key"] or args.only.lower() in b["name"].lower()
        return row is None or due(row) or row["status"] in redo

    # New benchmarks first, then the ones longest unchecked.
    todo = sorted((b for b in benchmarks if wanted(b)),
                  key=lambda b: rows.get(b["key"], {}).get("checked", ""))
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(benchmarks)} benchmarks, {len(rows.keys() & keys)} searched before, {len(todo)} to search now", flush=True)
    if not todo:
        report(rows, keys)
        return 0

    ids = []
    for bench in todo:
        for member in bench["members"]:
            if member["id"].startswith("arxiv-"):
                ids.append(member["id"][len("arxiv-"):].replace("-", ".", 1))
            ids += [m.group(1) for link in member["links"] if (m := ARXIV_RE.search(link["url"]))]
    arxiv_meta = arxiv_records(sorted(set(ids)), args.recheck_days)
    print(f"arXiv records: {len(arxiv_meta)} of {len(set(ids))}", flush=True)

    lock = threading.Lock()
    workdir = tempfile.mkdtemp(prefix="bench-pool-leaderboards-")
    stats = Counter()

    def run(bench: dict) -> None:
        try:
            row = search_one(bench, arxiv_meta, args, workdir, today.isoformat(), rows.get(bench["key"]))
        except Exception as exc:  # noqa: BLE001 - one bad benchmark must not stop the run
            row = {"key": bench["key"], "name": bench["name"], "search_version": SEARCH_VERSION,
                   "checked": today.isoformat(), "pages_read": 0, "tried": [], "status": "unchecked",
                   "note": f"search crashed: {type(exc).__name__}: {str(exc)[:120]}"}
        with lock:
            rows[row["key"]] = row
            with OUT.open("a") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            stats[row["status"]] += 1
            n = sum(stats.values())
            if n % 25 == 0 or n == len(todo):
                print(f"  {n}/{len(todo)}  " + ", ".join(f"{k} {v}" for k, v in sorted(stats.items())), flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        list(executor.map(run, todo))

    # Keep the file to one line per benchmark.
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for _, r in sorted(rows.items())))
    report(rows, keys)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
