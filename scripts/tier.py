#!/usr/bin/env python3
"""Tier every benchmark in the pool against docs/tiering-standard.md.

Reads  web/data/benchmarks.json (run scripts/build.py first), data/candidates.json,
       docs/tiering-standard.md
Writes data/tiers.jsonl   (one line per judgement, appended, never rewritten)

Per benchmark:
1. Reading. The whole paper (arXiv HTML, else the PDF through `pdftotext`), the
   repository README and the top-level file list are fetched here and cached in
   data/raw/tier_pages/. The model does not browse. How much was read is stored
   with the verdict. With neither a paper nor a repository there is nothing to
   judge on: rule T0, hold, no model call.
2. Judging. One benchmark per call, with the standard, the pool's facts and the
   texts. The `new` flag (under 15 days old, no leaderboard, attention under
   the bar) is computed here and passed along.
3. Checking. A quote that is not in the text the model was given is dropped
   and its dimension becomes no_evidence; a tier its own dimensions no longer
   support is lowered to hold.

    python3 scripts/tier.py --pilot             # 30 benchmarks: Harbor Index v1 sources and a spread
    python3 scripts/tier.py                     # everything not judged under the current standard
    python3 scripts/tier.py --only "SWE-Lancer"
    python3 scripts/tier.py --report            # counts only

Backend: scripts/llm.py (the endpoint in .env, else the local `claude`
command), at medium reasoning effort. GITHUB_TOKEN (from .env) is used to read READMEs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import llm
from signals import get, load_env

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "web" / "data" / "benchmarks.json"
CANDIDATES = ROOT / "data" / "candidates.json"
STANDARD = ROOT / "docs" / "tiering-standard.md"
OUT = ROOT / "data" / "tiers.jsonl"
PAGES = ROOT / "data" / "raw" / "tier_pages"
MODEL = "claude-sonnet-5-5"
EFFORT = "medium"
TIERS = ("recommend", "hold", "no")
# A standard whose rules did not change for model-made judgements keeps the older ones.
CARRIES = {"0.3": ("0.2",)}     # 0.4 changed what is read; 0.5 re-derives tiers with --rerule
BLOCKING = ("B1", "B2", "B3", "B4", "B5", "B6")

DIMENSIONS = ("real", "diverse", "difficult", "valuable", "solid", "attention")
VERDICTS = ("strong", "ok", "weak", "no_evidence")
COVERAGE = ("data", "scores", "task_scores", "trajectories", "process", "infra")
# Section 3.0 of the standard: facts looked up before any verdict, and their allowed values.
CHECKS = {
    "data_released": ("yes", "partial", "no"),
    "provenance": ("real_artifacts", "expert_written", "generated", "mixed"),
    "human_review": ("yes", "no"),
    "domain_expertise": ("yes", "no"),
    "verifier": ("executable", "exact_match", "llm_judge", "human", "mixed"),
    "judge_validated": ("yes", "no", "not_applicable"),
    "solvable": ("yes", "no"),
    "environment": ("container", "live_web", "simulator", "hardware"),
    "gaming": ("yes", "no"),
    "variance": ("yes", "no"),
}
HARD_AT_MOST, EASY_FROM = 60.0, 80.0     # best score, percent of the maximum: Difficult strong / weak
NEW_DAYS = 15
PAPER_LIMIT = 160_000     # characters of paper text handed to the judge; longer papers are cut and marked
README_LIMIT = 20_000
ATTENTION_BAR = {"stars": 100, "upvotes": 20, "citations": 5}
SATURATED = 90.0

INSTRUCTIONS = """You tier benchmarks for Harbor Index by the standard below. Judge only from the FACTS and TEXT given for each benchmark. Do not use tools. Do not use what you remember about a benchmark as evidence.

{standard}

HOW TO ANSWER
Reply with one JSON array and nothing else, one object per benchmark:
{{"key": "...", "tier": "recommend|hold|no", "rule": "B1..B6 or T2|T3|T4", "reason": "one sentence, at most 30 words, that a person can check",
  "dimensions": {{"real": {{"verdict": "strong|ok|weak|no_evidence", "quote": "..."}}, "diverse": {{...}}, "difficult": {{...}}, "valuable": {{...}}, "solid": {{...}}, "attention": {{...}}}},
  "coverage": {{"data": "yes|partial|no|no_evidence", "scores": "...", "task_scores": "...", "trajectories": "...", "process": "...", "infra": "..."}},
  "harbor_fit": {{"container": "yes|no|unclear", "blocker": "short phrase or null"}},
  "checks": {{"data_released": {{"value": "...", "quote": "..."}}, "provenance": {{...}}, "human_review": {{...}}, "domain_expertise": {{...}}, "verifier": {{...}}, "judge_validated": {{...}}, "solvable": {{...}}, "environment": {{...}}, "gaming": {{...}}, "variance": {{...}},
             "best_score": {{"percent": number or null, "system": "...", "run_by": "authors|others|both", "quote": "..."}}, "top_gap": number or null,
             "size": {{"tasks": number or null, "categories": number or null, "sources": number or null}}}},
  "risks": [{{"risk": "at most 20 words", "quote": "exact words from the TEXT, or omit if the TEXT is silent on it"}}]}}
- Answer the checks of section 3.0 FIRST, each from the TEXT with an exact quote; use "not_stated" when the TEXT does not say. Look for every one of them. This is not a review of the paper: you are establishing facts about the benchmark as a source of tasks.
- "best_score.percent" is the best result on the main metric as a percentage of the maximum (higher is better); null if it cannot be put that way.
- "risks": up to three things someone bringing this benchmark into Harbor would have to settle first, drawn from the checks (tasks not released, unvalidated judge, live websites, no evidence that tasks are solvable, top models near the ceiling, reward hacking not addressed). [] only if every check came back clean.
- Apply the bars for "strong" in sections 3.1 to 3.5 exactly. They will be re-applied to your checks by a script.
- TEXT.linked_page, when present, is the benchmark's own page (a dataset card or project page), given because no paper or repository is linked. Judge from it as you would from a README; what it does not say is not_stated.
- TEXT.paper is the whole paper (or says so if it was cut). Read all of it before deciding: task design, construction, verifier and results are usually described after the abstract.
- Weak or missing Attention never blocks a benchmark.
- If FACTS.new is true the benchmark is under 15 days old with no leaderboard: Difficult and Attention are expected to be no_evidence, and that must not hold it back. Judge it on Real, Diverse, Valuable and Solid.
- "quote" must be copied exactly from the benchmark's TEXT (paper, abstract, README, file list or linked page), at most 40 words. Omit it when the verdict is no_evidence. For "difficult" and "attention" you may instead rest on FACTS and omit the quote.
- If the TEXT does not say, the verdict is no_evidence, not weak.
- "mode" in FACTS is agentic, modified or non. Apply T2 or T3 accordingly.

BENCHMARKS
"""


def squash(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text).strip().lower()


def standard_text() -> tuple[str, str]:
    """(version, the sections the judge needs: tiers, dimensions, Harbor fit, rules)."""
    text = STANDARD.read_text()
    version = re.search(r"^Version (\S+)", text, re.M).group(1)
    body = text[text.index("## 2. Tiers"):text.index("## 6. Output")]
    return version, body.strip()


def age_days(item: dict, today: dt.date) -> int | None:
    if not item.get("date"):
        return None
    return (today - dt.date.fromisoformat(item["date"][:10])).days


def current(row: dict, version: str) -> bool:
    """Is this stored judgement valid under `version` of the standard?"""
    if row["standard"] == version:
        return True
    if version == "0.6" and row["standard"] == "0.5":
        return row["tier"] != "recommend"       # the new bars can only lower a verdict
    return row["standard"] in CARRIES.get(version, ()) and row.get("model") is not None and row["tier"] in TIERS


def is_new(item: dict, today: dt.date) -> bool:
    """The `new` flag, from the pool's own fields."""
    age = age_days(item, today)
    if age is None or age >= NEW_DAYS:
        return False
    if item["lb"] not in ("none", "unchecked"):          # someone keeps a leaderboard for it
        return False
    metrics = item.get("metrics") or {}
    return not any((metrics.get(k) or 0) >= bar for k, bar in ATTENTION_BAR.items())


def facts(item: dict, today: dt.date) -> dict:
    """What the pool knows, without the Adapter List or Harbor Index labels (those are the check)."""
    age = age_days(item, today)
    months = max(age / 30.4, 1.0) if age is not None else None
    metrics = {k: v for k, v in (item.get("metrics") or {}).items()
               if k in ("stars", "forks", "citations", "upvotes", "likes", "downloads") and v is not None}
    score = None
    if item.get("best") is not None:
        src = {"own": item.get("own"), "aggregator": item.get("agg"), "paper": item.get("paper")}[item["basis"]] or {}
        score = {"best_percent": item["best"], "source": item["basis"] + " leaderboard" if item["basis"] != "paper" else "paper abstract (authors' own figure)",
                 "system": src.get("model"), "as_of": src.get("as_of") or src.get("found"),
                 "systems_listed": src.get("models") or src.get("entries")}
    return {
        "name": item["name"], "mode": item["mode"], "class": item["class_name"],
        "published": item.get("date"), "age_days": age, "new": is_new(item, today), "what_it_tests": item.get("does"),
        "best_score": score, "leaderboard": item["lb"],
        "attention": metrics,
        "stars_per_month": round(metrics["stars"] / months, 1) if months and "stars" in metrics else None,
        "citations_per_month": round(metrics["citations"] / months, 1) if months and "citations" in metrics else None,
        "organisations": item.get("orgs") or None, "authors": item.get("author_count") or None,
        "repo_last_push": (item.get("sig") or {}).get("pushed"),
        "links": [l["kind"] + ": " + l["url"] for l in item["links"][:6]],
    }


def repo_of(item: dict) -> str | None:
    """The benchmark's own repository: the one its signals were fetched from."""
    return (item.get("sig") or {}).get("repo")


def repo_pages(repo: str, token: str | None) -> dict:
    """README text and top-level file names, cached on disk."""
    path = PAGES / (repo.replace("/", "__") + ".json")
    if path.exists():
        return json.loads(path.read_text())
    out = {"repo": repo, "readme": "", "files": [], "fetched": dt.date.today().isoformat()}
    if token:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        try:
            listing = get(f"https://api.github.com/repos/{repo}/contents", headers) or []
            out["files"] = [e["name"] + ("/" if e["type"] == "dir" else "") for e in listing if isinstance(e, dict)][:80]
            readme = next((e for e in listing if isinstance(e, dict) and e["name"].lower().startswith("readme")), None)
            if readme and readme.get("download_url"):
                import urllib.request
                with urllib.request.urlopen(urllib.request.Request(readme["download_url"], headers={"User-Agent": "bench-pool"}), timeout=30) as resp:
                    out["readme"] = resp.read(60000).decode("utf-8", "replace")
        except Exception as err:  # noqa: BLE001 - judge from the abstract alone
            out["error"] = str(err)[:120]
    PAGES.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False))
    return out


_arxiv_lock = threading.Lock()
_arxiv_last = [0.0]


def _arxiv_get(url: str) -> bytes | None:
    """One request to arXiv at a time, three seconds apart."""
    import time
    import urllib.error
    import urllib.request
    with _arxiv_lock:
        wait = 3.0 - (time.time() - _arxiv_last[0])
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bench-pool (tiering; reads each paper once)"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read(30_000_000)
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        finally:
            _arxiv_last[0] = time.time()


def html_to_text(html: str) -> str:
    import html as html_lib
    html = re.sub(r"(?is)<(script|style|nav|header|footer|math|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)</(p|div|h\d|li|tr|section|figcaption|table)>|<br[^>]*>", "\n", html)
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", html))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()


def drop_references(text: str) -> str:
    """Cut the bibliography but keep appendices that follow it."""
    m = None
    for m in re.finditer(r"\n\s*(References|Bibliography|REFERENCES)\s*\n", text):
        pass
    if not m or m.start() < len(text) * 0.3:
        return text
    tail = text[m.end():]
    app = re.search(r"\n\s*(Appendix|Appendices|APPENDIX|Supplementary|[A-Z]\s+[A-Z][a-z]+ (Details|Results|Statement|Prompts?|Examples?))\b", tail)
    return text[:m.start()] + ("\n[reference list removed]\n" + tail[app.start():] if app else "\n[reference list removed]")


def paper_text(arxiv: str) -> dict:
    """The whole paper as text, cached. {"text", "via", "chars"}; text is "" if it could not be read."""
    path = PAGES / f"paper_{arxiv}.json"
    if path.exists():
        return json.loads(path.read_text())
    out = {"arxiv": arxiv, "text": "", "via": None, "fetched": dt.date.today().isoformat()}
    body = _arxiv_get(f"https://arxiv.org/html/{arxiv}")
    if body and b"ltx_" in body:
        out.update(text=drop_references(html_to_text(body.decode("utf-8", "replace"))), via="arxiv html")
    if len(out["text"]) < 4000:                      # no HTML version: read the PDF
        pdf = _arxiv_get(f"https://arxiv.org/pdf/{arxiv}")
        if pdf and pdf[:4] == b"%PDF":
            with tempfile.NamedTemporaryFile(suffix=".pdf") as fh:
                fh.write(pdf)
                fh.flush()
                try:
                    proc = subprocess.run(["pdftotext", "-q", fh.name, "-"], capture_output=True, timeout=120)
                    text = proc.stdout.decode("utf-8", "replace")
                    if len(text) > 4000:
                        out.update(text=drop_references(re.sub(r"[ \t]+", " ", text)), via="arxiv pdf")
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    pass
    out["chars"] = len(out["text"])
    PAGES.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False))
    return out


def arxiv_of(item: dict) -> str | None:
    if item["id"].startswith("arxiv-"):
        return item["id"][6:].replace("-", ".", 1)
    for link in item["links"]:
        m = re.search(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})|10\.48550/arxiv\.(\d{4}\.\d{4,5})", link["url"], re.I)
        if m:
            return m.group(1) or m.group(2)
    return None


AGGREGATORS = ("llm-stats.com", "artificialanalysis.ai", "zeroeval.com", "evaleval/benchmark-saturation")
PAGE_LIMIT = 20_000
PAGE_MIN = 600           # less text than this is a shell page (script-rendered), not something to read


def page_address(url: str) -> str | None:
    """Where to read a linked page as text, or None for links this function is not for."""
    if any(a in url for a in AGGREGATORS) or "arxiv.org" in url or "10.48550/arxiv" in url.lower() or "github.com" in url:
        return None
    m = re.search(r"huggingface\.co/(datasets|spaces)/([\w.-]+/[\w.-]+)", url)
    if m:
        return f"https://huggingface.co/{m.group(1)}/{m.group(2)}/raw/main/README.md"
    return url if url.startswith("http") else None


def other_page(item: dict) -> dict | None:
    """The first linked page besides the paper and the repository that has real text:
    a Hugging Face dataset card, a DOI landing page, a project page. Cached on disk.
    Returns {"url", "text"} or None."""
    import hashlib
    import urllib.error
    import urllib.request
    tried = 0
    for link in item["links"]:
        if link["kind"] == "leaderboard":
            continue
        address = page_address(link["url"])
        if not address or tried >= 3:
            continue
        tried += 1
        path = PAGES / ("page_" + hashlib.sha1(address.encode()).hexdigest()[:16] + ".json")
        if path.exists():
            got = json.loads(path.read_text())
        else:
            got = {"url": link["url"], "text": "", "fetched": dt.date.today().isoformat()}
            headers = {"User-Agent": "Mozilla/5.0 (bench-pool; reads each page once)"}
            if "huggingface.co" in address and os.environ.get("HF_TOKEN"):
                headers["Authorization"] = "Bearer " + os.environ["HF_TOKEN"]
            try:
                with urllib.request.urlopen(urllib.request.Request(address, headers=headers), timeout=40) as resp:
                    body = resp.read(3_000_000).decode("utf-8", "replace")
                got["text"] = clean_readme(body, PAGE_LIMIT) if address.endswith(".md") else html_to_text(body)[:PAGE_LIMIT]
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                pass
            PAGES.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(got, ensure_ascii=False))
        if len(got["text"]) >= PAGE_MIN:
            return got
    return None


def clean_readme(text: str, limit: int = README_LIMIT) -> str:
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)|<img[^>]*>|<a [^>]*>|</a>|</?(p|div|h\d|br|picture|source|table|tr|td|th|details|summary)[^>]*>", " ", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()[:limit]


def packet(item: dict, summary: str, pages: dict | None, paper: dict | None, today: dt.date,
           page: dict | None = None) -> tuple[dict, dict]:
    """(what the judge is given, a record of how much that was)."""
    text = {}
    read = {"paper": None, "paper_chars": 0, "paper_cut": False, "readme_chars": 0, "files": 0, "page": None, "page_chars": 0}
    if page:
        text["linked_page"] = page["text"]
        read.update(page=page["url"], page_chars=len(page["text"]))
    if paper and paper.get("text"):
        body = paper["text"]
        read.update(paper=paper["via"], paper_chars=len(body), paper_cut=len(body) > PAPER_LIMIT)
        text["paper"] = body[:PAPER_LIMIT] + ("\n[paper cut here for length]" if read["paper_cut"] else "")
    else:
        text["abstract"] = summary[:2500]
    if pages:
        if pages.get("readme"):
            text["readme"] = clean_readme(pages["readme"])
            read["readme_chars"] = len(text["readme"])
        if pages.get("files"):
            text["repository_files"] = " ".join(pages["files"])
            read["files"] = len(pages["files"])
    return {"key": item["key"], "FACTS": facts(item, today), "TEXT": text}, read


SYSTEM = "You are a careful reviewer of AI benchmarks. You reply with JSON only."


def ask(prompt: str, effort: str = EFFORT) -> list[dict]:
    reply = llm.complete(prompt, SYSTEM, effort)
    match = re.search(r"\[.*\]", reply, re.S)
    if not match:
        raise RuntimeError(f"no JSON array in reply: {reply[:200]!r}")
    return json.loads(match.group(0))


def read_checks(row: dict, haystack: str) -> tuple[dict, list[dict]]:
    """The model's checks and risks, keeping only answers whose quote is in the text."""
    given = row.get("checks") if isinstance(row.get("checks"), dict) else {}
    checks: dict = {}
    for name, allowed in CHECKS.items():
        got = given.get(name) if isinstance(given.get(name), dict) else {"value": given.get(name)}
        value = got.get("value") if got.get("value") in allowed else "not_stated"
        quote = got.get("quote") if isinstance(got.get("quote"), str) and got["quote"].strip() else None
        if value not in ("not_stated", "not_applicable") and not (quote and squash(quote) in haystack):
            value, quote = "not_stated", None          # an answer needs its quote
        checks[name] = {"value": value, **({"quote": quote[:300]} if quote and value != "not_stated" else {})}
    best = given.get("best_score") if isinstance(given.get("best_score"), dict) else {}
    percent = best.get("percent") if isinstance(best.get("percent"), (int, float)) and 0 <= best["percent"] <= 100 else None
    quote = best.get("quote") if isinstance(best.get("quote"), str) else None
    if percent is not None and not (quote and squash(quote) in haystack):
        percent = None
    checks["best_score"] = {"percent": percent, "system": str(best.get("system") or "")[:80] or None,
                            "run_by": best.get("run_by") if best.get("run_by") in ("authors", "others", "both") else None,
                            **({"quote": quote[:300]} if percent is not None else {})}
    gap = given.get("top_gap")
    checks["top_gap"] = gap if isinstance(gap, (int, float)) else None
    size = given.get("size") if isinstance(given.get("size"), dict) else {}
    checks["size"] = {k: size.get(k) if isinstance(size.get(k), (int, float)) else None for k in ("tasks", "categories", "sources")}
    risks = []
    for entry in (row.get("risks") or [])[:3]:
        if isinstance(entry, dict) and entry.get("risk"):
            quote = entry.get("quote") if isinstance(entry.get("quote"), str) and squash(entry["quote"]) in haystack and entry["quote"].strip() else None
            risks.append({"risk": str(entry["risk"])[:200], **({"quote": quote[:300]} if quote else {})})
    return checks, risks


def apply_bars(dims: dict, checks: dict, notes: list[str], known_best: float | None = None) -> None:
    """Sections 3.1 to 3.5: a strong the checks do not carry becomes ok; Valuable is set from the checks."""
    value = lambda name: checks[name]["value"]

    def cap(name: str, allowed: bool, why: str) -> None:
        if dims[name]["verdict"] == "strong" and not allowed:
            dims[name]["verdict"] = "ok"
            notes.append(f"{name}: strong lowered to ok, {why}")

    cap("real", value("provenance") in ("real_artifacts", "expert_written"), "tasks are not shown to come from real artifacts or experts")
    size = checks["size"]
    cap("diverse", (size["tasks"] or 0) >= 100 and max(size["categories"] or 0, size["sources"] or 0) >= 5,
        "fewer than 100 tasks, or fewer than 5 categories and 5 sources")
    # The pool's own leaderboard score counts when the text quotes none.
    best = checks["best_score"]["percent"] if checks["best_score"]["percent"] is not None else known_best
    cap("difficult", best is not None and best <= HARD_AT_MOST, f"no best score at or below {HARD_AT_MOST:g}% was quoted")
    if best is not None and best >= EASY_FROM and dims["difficult"]["verdict"] in ("strong", "ok"):
        dims["difficult"]["verdict"] = "weak"
        notes.append(f"difficult: best score quoted is {best:g}%, at or above {EASY_FROM:g}%")
    sound_verifier = value("verifier") in ("executable", "exact_match") or \
        (value("verifier") in ("llm_judge", "mixed") and value("judge_validated") == "yes")
    cap("solid", sound_verifier and value("solvable") == "yes",
        "the verifier is not validated, or nothing shows the tasks are solvable")
    # Valuable, as the project owner defined it: models cannot do it and it needs domain expertise.
    if dims["valuable"]["verdict"] != "weak":
        strong = value("domain_expertise") == "yes" and dims["difficult"]["verdict"] == "strong"
        dims["valuable"] = {"verdict": "strong" if strong else "ok",
                            **({"quote": checks["domain_expertise"]["quote"]} if strong and checks["domain_expertise"].get("quote") else {})}


def supports_recommend(dims: dict, item: dict, new: bool) -> tuple[bool, str, str]:
    """Do the checked dimensions carry a recommend? (yes/no, the rule, why not).

    T2 (agentic, modified): Real and Solid strong, plus Difficult or Attention
    strong (waived for a `new` benchmark, which cannot have either yet), and
    none of Real, Diverse, Difficult, Valuable, Solid weak.
    T3 (non-agentic): Difficult and Attention strong.
    Never with a leaderboard score at or above the saturation bar.
    """
    is_ = lambda name, verdict: (dims.get(name) or {}).get("verdict") == verdict
    if item.get("best") is not None and item.get("basis") in ("own", "aggregator") and item["best"] >= SATURATED:
        return False, "T4", "leaderboard score is 90% or more"
    if item["mode"] == "non":
        ok = is_("difficult", "strong") and is_("attention", "strong")
        return ok, "T3", "" if ok else "a non-agentic benchmark needs strong Difficult and strong Attention"
    weak = [d for d in DIMENSIONS[:5] if is_(d, "weak")]
    if weak:
        return False, "T2", "weak: " + ", ".join(weak)
    if not (is_("real", "strong") and is_("solid", "strong")):
        return False, "T2", "recommend needs both Real and Solid to be strong"
    if not new and not (is_("difficult", "strong") or is_("attention", "strong")):
        return False, "T2", "recommend needs strong Difficult or strong Attention as well (waived only for new benchmarks)"
    return True, "T2", ""


def rerule(version: str, today: dt.date) -> int:
    """Re-derive every tier from the dimension verdicts already stored, with no model call.

    Used when a new version of the standard changes only how verdicts combine.
    Each benchmark's latest judgement under the previous version is copied to
    the current one; a recommend its dimensions no longer carry becomes hold.
    """
    items = {i["key"]: i for i in json.loads(POOL.read_text())["items"]}
    rows: dict[str, dict] = {}
    for line in OUT.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            rows.setdefault(row["standard"], {})[row["key"]] = row
    if rows.get(version):
        print(f"standard {version} already has {len(rows[version])} judgements; nothing re-derived")
        return 0
    previous = max((v for v in rows if v < version), default=None)
    if previous is None:
        raise SystemExit("no earlier judgements to re-derive from")
    moved = Counter()
    with OUT.open("a") as fh:
        for key, old in rows[previous].items():
            if key not in items:
                continue
            new = dict(old, standard=version, date=today.isoformat(), rederived_from=previous, notes=list(old.get("notes") or []))
            if old["tier"] == "recommend":
                ok, rule, why = supports_recommend(old["dimensions"], items[key], is_new(items[key], today))
                if not ok:
                    new.update(tier="hold", rule="T4")
                    new["notes"].append(f"standard {version}: {why}")
                else:
                    new["rule"] = rule
            moved[(old["tier"], new["tier"])] += 1
            fh.write(json.dumps(new, ensure_ascii=False) + "\n")
    print(f"re-derived {sum(moved.values())} judgements from standard {previous}:",
          {f"{a}->{b}": n for (a, b), n in sorted(moved.items())})
    return 0


def check(row: dict, pack: dict, item: dict) -> dict:
    """Keep only what the given text supports, then make the tier follow from it."""
    haystack = squash(" ".join(pack["TEXT"].values()) + " " + json.dumps(pack["FACTS"], ensure_ascii=False))
    notes = []
    dims = {}
    for name in DIMENSIONS:
        got = (row.get("dimensions") or {}).get(name) or {}
        verdict = got.get("verdict") if got.get("verdict") in VERDICTS else "no_evidence"
        quote = got.get("quote") if isinstance(got.get("quote"), str) and got.get("quote").strip() else None
        if quote and squash(quote) not in haystack:
            quote = None
            if name not in ("difficult", "attention"):      # those two may rest on FACTS
                notes.append(f"{name}: quote not found in the text, verdict dropped")
                verdict = "no_evidence"
        if verdict in ("strong", "weak") and not quote and name not in ("difficult", "attention"):
            notes.append(f"{name}: no quote given, verdict dropped")
            verdict = "no_evidence"
        dims[name] = {"verdict": verdict, **({"quote": quote[:400]} if quote and verdict != "no_evidence" else {})}

    checks, risks = read_checks(row, haystack)
    apply_bars(dims, checks, notes, item.get("best"))

    tier = row.get("tier") if row.get("tier") in TIERS else "hold"
    rule = str(row.get("rule") or "")[:3]
    on_board = item.get("best") is not None and item["basis"] in ("own", "aggregator")
    if tier not in TIERS:
        tier, rule = "hold", "T4"
    if tier == "no":
        if rule not in BLOCKING:
            tier, rule = "hold", "T4"
            notes.append("no blocking rule named")
        elif rule == "B1" and not (pack["TEXT"].get("readme") or pack["TEXT"].get("repository_files") or pack["TEXT"].get("paper")
                                   or pack["TEXT"].get("linked_page")):
            # With only an abstract there is nothing that could show the data is missing.
            tier, rule = "hold", "T4"
            notes.append("B1 needs the paper or a repository page to have been read; only the abstract was available")
        elif rule == "B3" and not (on_board and item["best"] >= SATURATED):
            tier, rule = "hold", "T4"
            notes.append("B3 needs a leaderboard score of 90% or more")
    if tier == "recommend":
        ok, rule, why = supports_recommend(dims, item, bool(pack["FACTS"].get("new")))
        if not ok:
            tier, rule = "hold", "T4"
            notes.append(why)
    if tier == "hold":
        rule = "T4"
    coverage = {k: (row.get("coverage") or {}).get(k) if (row.get("coverage") or {}).get(k) in ("yes", "partial", "no")
                else "no_evidence" for k in COVERAGE}
    fit = row.get("harbor_fit") or {}
    return {
        "tier": tier, "rule": rule, "reason": str(row.get("reason") or "")[:300],
        "dimensions": dims, "checks": checks, "risks": risks, "coverage": coverage,
        "harbor_fit": {"container": fit.get("container") if fit.get("container") in ("yes", "no") else "unclear",
                       "blocker": (str(fit["blocker"])[:120] if fit.get("blocker") else None)},
        "notes": notes,
    }


def unread_verdict(item: dict) -> tuple[str, str, str]:
    """For a benchmark with no paper and no repository: B3 if a leaderboard shows it saturated, else T0."""
    if item.get("best") is not None and item["basis"] in ("own", "aggregator") and item["best"] >= SATURATED:
        return "no", "B3", f"Best score on a leaderboard is {item['best']:g}% ({item['basis']}), at or above the 90% bar; nothing else could be read."
    looked = item.get("source_search")
    if looked:
        return "hold", "T0", (f"No paper or repository is linked. A search of {looked['searched']} for \"{looked['query']}\" on {looked['date']} "
                              f"found no paper that introduces it" + (f" ({looked['why']})" if looked.get("why") else "") + ". Nothing to judge on yet.")
    return "hold", "T0", "No paper, repository or readable page is linked, and it has not been searched for yet. Nothing to judge on yet."


def latest(version: str) -> dict[str, dict]:
    done: dict[str, dict] = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                if current(row, version):
                    done[row["key"]] = row
    return done


def pilot_set(items: list[dict]) -> list[dict]:
    """Harbor Index v1 sources, Adapter List excludes, and one recent benchmark per class."""
    picked = [i for i in items if i.get("hi1")][:14]
    picked += [i for i in items if i.get("adapter") and i["adapter"]["include"] == "exclude"][:6]
    seen_classes: set[int] = set()
    for item in sorted(items, key=lambda i: i.get("date") or "", reverse=True):
        if item["origin"] == "snapshot" and item["cls"] not in seen_classes and (item.get("sig") or {}).get("repo"):
            seen_classes.add(item["cls"])
            picked.append(item)
    return picked[:30]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--effort", default=EFFORT, choices=("low", "medium", "high"))
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--all", action="store_true", help="also judge covered benchmarks (the check on the standard)")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--only", help="one benchmark, by name")
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--redo", action="store_true", help="judge again even if already judged under this standard")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--rerule", action="store_true",
                        help="copy the previous standard's judgements to the current one, re-deriving tiers; no model call")
    parser.add_argument("--redo-model", help="judge again the benchmarks whose current verdict was made by this model")
    args = parser.parse_args()
    load_env()
    token = os.environ.get("GITHUB_TOKEN")
    args.model = None if args.report or args.rerule else llm.model()
    version, standard = standard_text()
    today = dt.date.today()

    data = json.loads(POOL.read_text())
    class_name = {c["id"]: c["name"] for c in data["meta"]["classes"]}
    items = data["items"]
    for item in items:
        item["class_name"] = class_name[item["cls"]]
    summaries = {c["id"]: c["summary"] for c in json.loads(CANDIDATES.read_text())["candidates"]}
    done = latest(version)

    if args.rerule:
        return rerule(version, today)
    if args.report:
        print(f"standard {version}: {len(done)} of {len(items)} judged", dict(Counter(r["tier"] for r in done.values())))
        print("rules:", dict(Counter(r["rule"] for r in done.values())))
        return 0

    todo = pilot_set(items) if args.pilot else items
    if args.only:
        todo = [i for i in items if i["name"].lower() == args.only.lower()]
    def due(item: dict) -> bool:
        old = done.get(item["key"])
        if old is None:
            return True
        if old["rule"] != "T0":
            return False
        # Held for want of anything to read: judge it once a search has found its paper,
        # and restate the reason once a search has been made.
        return bool(arxiv_of(item) or repo_of(item) or other_page(item)) or \
            (bool(item.get("source_search")) and "A search of" not in old["reason"])

    if args.redo_model:
        todo = [i for i in items if done.get(i["key"], {}).get("model") == args.redo_model]
    elif not args.redo:
        todo = [i for i in todo if due(i)]
    if args.limit:
        todo = todo[: args.limit]

    stamp = {"date": today.isoformat(), "standard": version}
    if not (args.all or args.only or args.pilot or args.redo_model):
        todo = [i for i in todo if not i.get("covered")]
    unreadable = [i for i in todo if not arxiv_of(i) and not repo_of(i) and not other_page(i)]
    with OUT.open("a") as fh:
        for item in unreadable:
            tier, rule, reason = unread_verdict(item)
            fh.write(json.dumps({"key": item["key"], **stamp, "model": None, "tier": tier, "rule": rule,
                                 "reason": reason,
                                 "dimensions": {}, "coverage": {}, "harbor_fit": {}, "notes": [], "pages": [],
                                 "read": {"paper": None, "paper_chars": 0, "paper_cut": False, "readme_chars": 0, "files": 0}},
                                ensure_ascii=False) + "\n")
    skip = {i["key"] for i in unreadable}
    for_model = [i for i in todo if i["key"] not in skip]
    print(f"standard {version}: {len(todo)} to judge; {len(unreadable)} have nothing to read (T0), "
          f"{len(for_model)} for {args.model} ({sum(is_new(i, today) for i in for_model)} flagged new)", flush=True)
    if not for_model:
        return 0

    batches = [for_model[i:i + args.batch] for i in range(0, len(for_model), args.batch)]
    lock = threading.Lock()
    stats = Counter()
    workdir = tempfile.mkdtemp(prefix="bench-pool-tier-")
    prompt_head = INSTRUCTIONS.format(standard=standard)

    def run(batch: list[dict]) -> None:
        packs, pages_read, reads = {}, {}, {}
        for item in batch:
            repo, axv = repo_of(item), arxiv_of(item)
            pages = repo_pages(repo, token) if repo else None
            paper = paper_text(axv) if axv else None
            # A dataset card or project page is read when there is neither a paper nor a repository.
            page = other_page(item) if not (paper and paper.get("text")) and not (pages and pages.get("readme")) else None
            packs[item["key"]], reads[item["key"]] = packet(item, summaries.get(item["id"], ""), pages, paper, today, page)
            pages_read[item["key"]] = ([f"https://arxiv.org/abs/{axv}"] if paper and paper.get("text") else []) + \
                ([f"https://github.com/{repo}"] if pages and (pages.get("readme") or pages.get("files")) else []) + \
                ([page["url"]] if page else [])
        rows: list[dict] = []
        for attempt in (1, 2):
            try:
                rows = ask(prompt_head + json.dumps(list(packs.values()), ensure_ascii=False, indent=0), args.effort)
                break
            except Exception as err:  # noqa: BLE001 - report and retry once
                print(f"  batch failed (try {attempt}): {err}", file=sys.stderr, flush=True)
        by_key = {i["key"]: i for i in batch}
        good = []
        for row in rows:
            key = row.get("key") if isinstance(row, dict) else None
            if key in by_key:
                verdict = check(row, packs[key], by_key[key])
                read = reads[key]
                if verdict["tier"] == "recommend" and not read["paper_chars"] and not read["readme_chars"] and not read["page_chars"]:
                    verdict.update(tier="hold", rule="T4")
                    verdict["notes"].append("recommend needs the paper, the README or the benchmark's own page to have been read")
                good.append({"key": key, **stamp, "model": args.model, **verdict, "pages": pages_read[key], "read": read})
        with lock:
            with OUT.open("a") as fh:
                for row in good:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stats[row["tier"]] += 1
            stats["unanswered"] += len(batch) - len(good)
            print(f"  judged {sum(v for k, v in stats.items() if k != 'unanswered')}/{len(for_model)} "
                  f"(unanswered {stats['unanswered']})", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        list(executor.map(run, batches))
    print("done:", dict(stats))
    return 0 if not stats["unanswered"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
