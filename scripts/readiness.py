#!/usr/bin/env python3
"""Adapter readiness: what an adapter author needs, for recommended benchmarks not yet in Harbor.

For each such benchmark this reads the release itself, not the paper:
  GitHub      repository metadata (licence, default branch, latest commit), the file tree,
              the README, and a few telling files (Dockerfile, compose files, task manifests)
  Hugging Face dataset card, licence, file list, revision
  Zenodo      the record's files and licence, and the software repository it links to
  Harbor      whether the registry or Harbor Hub already has it (data/harbor_status.json, via the pool)

A model then fills a fixed record, quoting the text for every claim:
  release   repository and commit, dataset and revision, which artifact holds the tasks
  rights    code licence, data licence, and redistribution questions
  tasks     count, unit, manifest path, splits, one suggested pilot task
  verifier  kind, entry point (file or command), what earns full credit
  oracle    the strongest solvability evidence, graded:
              none < offline_answers < reference_solution < reference_passes_reported < controls_reported
            (controls = a reference solution passes AND a no-op or base state fails)
  runtime   docker, services, GPU, network or API dependencies, credentials, per-task exceptions
  questions what an author must settle first
Quotes that are not in the material are dropped with their claim. A file path the record names is
checked against the repository tree: "inspected" when the file exists, "reported" when only the text
says so. Answers go to data/readiness.jsonl and are refreshed when the repository's commit changes,
or after 30 days.

    python3 scripts/readiness.py --limit 3
    python3 scripts/readiness.py
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import llm

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "web" / "data" / "benchmarks.json"
OUT = ROOT / "data" / "readiness.jsonl"
PROMPT_VERSION = 1
RECHECK_DAYS = 30
UA = "bench-pool/0.1 (benchmark discovery; https://github.com/harbor-index/bench-pool)"
ORACLE_LEVELS = ["none", "offline_answers", "reference_solution", "reference_passes_reported", "controls_reported"]
KEY_FILES = re.compile(r"(?:^|/)(?:Dockerfile[^/]*|docker-compose[^/]*\.ya?ml|compose\.ya?ml|LICEN[CS]E[^/]*|"
                       r"(?:task|tasks|manifest|MANIFEST|metadata)\.(?:json|ya?ml|toml)|pyproject\.toml|requirements\.txt|"
                       r"(?:run|eval|evaluate|score|grade|verify)[^/]*\.(?:py|sh))$")


def get(url: str, headers: dict | None = None, raw: bool = False):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
    return body.decode("utf-8", "replace") if raw else json.loads(body)


def gh_headers() -> dict:
    tok = os.environ.get("GITHUB_TOKEN")
    return {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {tok}"} if tok else {})}


# ---------------------------------------------------------------- materials
def github(repo: str) -> dict:
    meta = get(f"https://api.github.com/repos/{repo}", gh_headers())
    branch = meta.get("default_branch") or "main"
    commit = get(f"https://api.github.com/repos/{repo}/commits/{branch}", gh_headers())["sha"]
    tree = get(f"https://api.github.com/repos/{repo}/git/trees/{commit}?recursive=1", gh_headers()).get("tree") or []
    paths = [t["path"] for t in tree if t["type"] == "blob"]
    readme = ""
    try:
        r = get(f"https://api.github.com/repos/{repo}/readme", gh_headers())
        readme = base64.b64decode(r["content"]).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        pass
    files = {}
    budget = 14000
    for p in sorted((p for p in paths if KEY_FILES.search(p)), key=lambda p: (p.count("/"), len(p)))[:12]:
        if budget <= 0:
            break
        try:
            text = get(f"https://raw.githubusercontent.com/{repo}/{commit}/{urllib.parse.quote(p)}", raw=True)
        except Exception:  # noqa: BLE001
            continue
        files[p] = text[: min(2500, budget)]
        budget -= len(files[p])
    # A compact view of the tree: top-level entries and how many files sit under each.
    top: dict[str, int] = {}
    for p in paths:
        top[p.split("/")[0]] = top.get(p.split("/")[0], 0) + 1
    return {"kind": "github", "id": repo, "url": f"https://github.com/{repo}", "commit": commit, "branch": branch,
            "license": (meta.get("license") or {}).get("spdx_id"), "stars": meta.get("stargazers_count"),
            "pushed": (meta.get("pushed_at") or "")[:10], "paths": paths, "tree": top, "readme": readme[:16000], "files": files}


def hf_dataset(ds: str) -> dict:
    meta = get(f"https://huggingface.co/api/datasets/{ds}")
    readme = ""
    try:
        readme = get(f"https://huggingface.co/datasets/{ds}/raw/main/README.md", raw=True)
    except Exception:  # noqa: BLE001
        pass
    files = [s["rfilename"] for s in meta.get("siblings") or []]
    card = meta.get("cardData") or {}
    return {"kind": "hf", "id": ds, "url": f"https://huggingface.co/datasets/{ds}", "commit": meta.get("sha"),
            "license": card.get("license"), "paths": files, "readme": readme[:12000],
            "tree": {f.split("/")[0]: 0 for f in files[:200]}, "files": {}}


def zenodo(rec: str) -> dict:
    meta = get(f"https://zenodo.org/api/records/{rec}")
    md = meta.get("metadata") or {}
    rel = [r.get("identifier") for r in md.get("related_identifiers") or [] if r.get("identifier")]
    return {"kind": "zenodo", "id": rec, "url": f"https://zenodo.org/records/{rec}", "commit": str(meta.get("revision")),
            "license": (md.get("license") or {}).get("id"), "paths": [f.get("key") for f in meta.get("files") or []],
            "readme": re.sub(r"<[^>]+>", " ", md.get("description") or "")[:6000], "related": rel, "tree": {}, "files": {}}


def release_links(item: dict) -> list[str]:
    """When the pool has no repository or dataset link: ask Hugging Face's paper record for its GitHub
    repository, else read the links in the paper's arXiv HTML and keep the ones that look like its release."""
    arx = next((m.group(1) for l in item["links"] for m in [re.search(r"arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5})", l["url"])] if m), None)
    if not arx:
        return []
    found = []
    try:
        rec = get(f"https://huggingface.co/api/papers/{arx}")
        if rec.get("githubRepo"):
            found.append(rec["githubRepo"])
    except Exception:  # noqa: BLE001
        pass
    if found:
        return found
    try:
        page = get(f"https://arxiv.org/html/{arx}", raw=True)
    except Exception:  # noqa: BLE001
        return []
    hrefs = re.findall(r'href="(https?://(?:github\.com/[\w.-]+/[\w.-]+|huggingface\.co/datasets/[\w.-]+/[\w.-]+|zenodo\.org/records?/\d+))', page)
    common = {"github.com/openai", "github.com/anthropics", "github.com/huggingface", "github.com/pytorch", "github.com/google",
              "github.com/microsoft/vscode", "github.com/vllm-project", "github.com/langchain-ai",
              "github.com/brucemiller/LaTeXML", "github.com/arXiv/html_feedback", "github.com/arXiv"}
    name = re.sub(r"[^a-z0-9]", "", item["name"].lower())
    score: dict[str, float] = {}
    for h in hrefs:
        h = h.rstrip(".")
        if any(c in h for c in common):
            continue
        tail = re.sub(r"[^a-z0-9]", "", h.rsplit("/", 1)[-1].lower())
        score[h] = score.get(h, 0) + 1 + (3 if name[:6] and (name[:6] in tail or tail[:6] in name) else 0)
    return [h for h, _ in sorted(score.items(), key=lambda kv: -kv[1])[:2]]


def materials(item: dict) -> list[dict]:
    urls = [l["url"] for l in item["links"]]
    if not any(re.search(r"github\.com/[\w.-]+/|huggingface\.co/datasets/|zenodo\.org", u) for u in urls):
        urls += release_links(item)
    out, seen = [], set()

    def add(fn, ident):
        if ident in seen:
            return
        seen.add(ident)
        try:
            m = fn(ident)
            out.append(m)
            for r in m.get("related") or []:                 # Zenodo -> the software repository
                g = re.search(r"github\.com/([\w.-]+/[\w.-]+?)(?:\.git|/|$)", r)
                if g:
                    add(github, g.group(1))
        except Exception as exc:  # noqa: BLE001
            print(f"  {item['name']}: {ident}: {str(exc)[:70]}", file=sys.stderr)

    for u in urls:
        g = re.search(r"github\.com/([\w.-]+/[\w.-]+?)(?:\.git|/|$|#|\?)", u + "/")
        if g and not g.group(1).startswith(("orgs/", "user-attachments/")):
            add(github, g.group(1))
        h = re.search(r"huggingface\.co/datasets/([\w.-]+/[\w.-]+)", u)
        if h:
            add(hf_dataset, h.group(1))
        z = re.search(r"zenodo\.org/(?:records|record|doi/10\.5281/zenodo\.)/?(\d+)", u)
        if z:
            add(zenodo, z.group(1))
    return out[:3]


# ---------------------------------------------------------------- judging
PROMPT = """You prepare an adapter brief for Harbor, which runs benchmark tasks in containers with a
programmatic verifier. Read ONLY the release material below (repository, dataset card, files) and fill the
record. Copy every quote word for word from the material. Use null or [] when the material does not say.

BENCHMARK: {name}
WHAT IT TESTS: {does}

{text}

Answer with one JSON object:
{{
 "release": {{"tasks_live_in": "github:<owner/repo> | hf:<owner/name> | zenodo:<id> | unknown", "quote": "..."}},
 "rights": {{"code_license": "..." or null, "data_license": "..." or null, "redistribution_questions": ["..."], "quote": "..."}},
 "tasks": {{"count": number or null, "unit": "task|episode|problem|repository|...", "manifest_path": "path or null",
           "splits": ["..."], "pilot": "one task id or path to start with, or null", "quote": "..."}},
 "verifier": {{"kind": "executable_tests|exact_match|programmatic_state|llm_judge|human|mixed|unknown",
              "entry_point": "file path or command, or null", "full_credit": "what earns full credit, one line", "quote": "..."}},
 "oracle": {{"level": "none|offline_answers|reference_solution|reference_passes_reported|controls_reported",
            // offline_answers: gold answers exist but nothing runs a solution through the environment
            // reference_solution: a reference solution or gold patch is shipped
            // reference_passes_reported: the text says the reference solution passes the verifier
            // controls_reported: the text says the reference passes AND a no-op/base state fails
            "path": "where the reference lives, or null", "command": "how to run the check, or null", "quote": "..."}},
 "runtime": {{"docker": "yes|no|unclear", "services": ["..."], "gpu": "yes|no|unclear",
             "network_or_api": ["live services, model endpoints or APIs a task needs"], "credentials": ["..."],
             "exceptions": ["tasks that need something special"], "quote": "..."}},
 "questions": ["what an adapter author must settle first, at most 4, plain words"],
 "next_action": "one line: the smallest first step for an adapter author"
}}"""


def judge(item: dict) -> dict | None:
    mats = materials(item)
    if not mats:
        # Nothing to read is itself the answer an adapter author needs: the tasks may not be out.
        blank = {"quote": None, "evidence": "unknown"}
        return {"key": item["key"], "name": item["name"], "date": dt.date.today().isoformat(), "model": None,
                "prompt_version": PROMPT_VERSION, "sources": [], "no_release": True,
                "release": {**blank, "tasks_live_in": "unknown"}, "rights": dict(blank), "tasks": dict(blank),
                "verifier": dict(blank), "oracle": {**blank, "level": "none"}, "runtime": dict(blank),
                "questions": ["No public repository or dataset was found in the pool's links, Hugging Face's paper "
                              "record or the paper's own links. Are the tasks released?"],
                "next_action": "Ask the authors where the tasks, environment and grader are released."}
    parts = []
    for m in mats:
        head = f"=== {m['kind']}: {m['id']} (commit/revision {m.get('commit')}, licence field: {m.get('license')}) ==="
        tree = ", ".join(f"{k} ({v})" if v else k for k, v in list(m["tree"].items())[:40])
        files = "\n".join(f"--- file {p} ---\n{t}" for p, t in m["files"].items())
        parts.append(f"{head}\nTop-level entries: {tree}\nFile count: {len(m['paths'])}\n--- README ---\n{m['readme']}\n{files}")
    text = "\n\n".join(parts)[:42000]
    reply = llm.complete(PROMPT.format(name=item["name"], does=item.get("does") or "", text=text),
                         "You extract facts from software releases. You reply with JSON only.", "medium")
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        raise RuntimeError(f"no JSON in reply: {reply[:120]!r}")
    a = json.loads(m.group(0))
    squash = lambda t: re.sub(r"[\W_]+", " ", t or "").strip().lower()  # noqa: E731
    hay = squash(text)
    paths = {p for mm in mats for p in mm["paths"]}

    def section(name: str) -> dict:
        sec = a.get(name) if isinstance(a.get(name), dict) else {}
        q = sec.get("quote")
        sec["quote"] = q if isinstance(q, str) and len(q.strip()) > 6 and squash(q) in hay else None
        sec["evidence"] = "reported" if sec["quote"] else "unknown"
        for k in ("manifest_path", "path", "entry_point"):
            v = sec.get(k)
            if isinstance(v, str) and v:
                clean = v.strip().lstrip("./")
                if clean in paths or any(p.startswith(clean.rstrip("/") + "/") for p in paths):
                    sec["evidence"] = "inspected"
                    sec[k + "_found"] = True
                else:
                    sec[k + "_found"] = False
        return sec

    rec = {k: section(k) for k in ("release", "rights", "tasks", "verifier", "oracle", "runtime")}
    if rec["oracle"].get("level") not in ORACLE_LEVELS or (rec["oracle"]["evidence"] == "unknown" and rec["oracle"].get("level") != "none"):
        rec["oracle"]["level"] = "none" if rec["oracle"]["evidence"] == "unknown" else rec["oracle"].get("level", "none")
    return {
        "key": item["key"], "name": item["name"], "date": dt.date.today().isoformat(), "model": llm.model(),
        "prompt_version": PROMPT_VERSION,
        "sources": [{"kind": mm["kind"], "id": mm["id"], "url": mm["url"], "commit": mm.get("commit"),
                     "license": mm.get("license"), "files": len(mm["paths"]), "pushed": mm.get("pushed")} for mm in mats],
        **rec,
        "questions": [q for q in (a.get("questions") or []) if isinstance(q, str)][:4],
        "next_action": (a.get("next_action") or "")[:200],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--redo", action="store_true")
    args = ap.parse_args()
    llm.load_env()
    items = [i for i in json.loads(POOL.read_text())["items"]
             if not i.get("covered") and (i.get("tier") or {}).get("tier") == "recommend"]
    done = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["key"]] = r
    cutoff = (dt.date.today() - dt.timedelta(days=RECHECK_DAYS)).isoformat()
    due = [i for i in items if args.redo or i["key"] not in done or done[i["key"]]["date"] < cutoff
           or done[i["key"]].get("prompt_version") != PROMPT_VERSION]
    if args.limit:
        due = due[: args.limit]
    print(f"readiness: {len(items)} recommended and not in Harbor, {len(due)} to read")

    def one(it):
        try:
            return judge(it)
        except Exception as exc:  # noqa: BLE001
            print(f"  {it['name']}: {str(exc)[:100]}", file=sys.stderr)
            return None

    n_ok = 0
    with ThreadPoolExecutor(args.workers) as ex, OUT.open("a") as fh:
        for row in ex.map(one, due):
            if row:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                n_ok += 1
    print(f"done: {n_ok} written ({len(due) - n_ok} had no release to read or failed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
