#!/usr/bin/env python3
"""Is the gap to 100% real? For each popular benchmark, the ranking's judging step.

A low best score only means a benchmark is hard if the tasks it fails on are
valid. Broken or ambiguous tasks, wrong reference answers, flaky or live
environments and unvalidated model graders also hold scores down. This step
asks a model, from evidence only:

  ceiling  the best score a perfect agent could reach: 100 minus the share of
           tasks the text shows cannot earn credit (wrong answers, unsolvable).
           A human baseline is recorded separately and never used as a ceiling.
  cause    what the remaining gap is mostly made of: model | tasks |
           environment | grader | mixed | unknown
  verdict  real     the gap is mostly models failing valid tasks
           suspect  a material part of it is the benchmark's fault
           unknown  the text does not say

Evidence given to the model, and nothing else:
  ABOUT    the benchmark's own description and the facts the tiering step looked up
  SCORES   the best scores we have (own leaderboard, aggregators, Epoch AI, paper)
  EPOCH    Epoch AI's ceiling, baseline, successor and record history
  AUDITS   up to 8 arXiv papers that discuss the benchmark's errors, audits,
           verified versions or contamination (arXiv API search, kept 30 days)

Quotes that are not in that text are dropped, and a claim without a kept quote
does not count. Answers go to data/headroom.jsonl (one line per benchmark, a
later line wins); a benchmark is asked again after 30 days.

    python3 scripts/headroom.py --limit 5      # try a few
    python3 scripts/headroom.py                # every popular benchmark that is due
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import llm

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "web" / "data" / "benchmarks.json"
EPOCH = ROOT / "data" / "epoch.json"
OUT = ROOT / "data" / "headroom.jsonl"
AUDIT_CACHE = ROOT / "data" / "raw" / "audits"
PROMPT_VERSION = 3
RECHECK_DAYS = 30
EFFORT = "medium"
ATOM = "{http://www.w3.org/2005/Atom}"
UA = "bench-pool/0.1 (benchmark discovery; https://github.com/harbor-index/bench-pool)"
# Title words of papers that examine a benchmark's problems (searched together with the name in the abstract).
AUDIT_WORDS = ["error", "errors", "mislabeled", "mislabelled", "audit", "auditing", "flawed", "flaws", "contamination",
               "invalid", "noisy", "ambiguous", "unsolvable", "saturated", "saturation", "revisiting", "pitfalls",
               "broken", "validity", "reliable", "cheating", "shortcuts", "verified"]


def squash(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text or "").strip().lower()


# ---------------------------------------------------------------- evidence
def audits(name: str) -> list[dict]:
    """arXiv papers that talk about this benchmark's problems. Cached for 30 days."""
    plain = re.sub(r"\s*\(.*?\)", "", name).replace("’", "'")
    plain = re.sub(r"[^A-Za-z0-9 .'\-]", " ", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    path = AUDIT_CACHE / (re.sub(r"\W+", "_", plain.lower())[:80] + ".json")
    if path.exists() and (time.time() - path.stat().st_mtime) < RECHECK_DAYS * 86400:
        return json.loads(path.read_text())
    if len(plain) < 3:
        return []
    # 1. papers named after it (its own paper, a "Verified" version, an audit of it)
    # 2. papers that mention it and whose title is about errors, audits, contamination and the like
    queries = [(f'ti:"{plain}"', 4),
               (f'abs:"{plain}" AND (' + " OR ".join(f"ti:{w}" for w in AUDIT_WORDS) + ")", 6)]
    out, seen = [], set()
    try:
        for query, n in queries:
          url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
              {"search_query": query, "max_results": n, "sortBy": "relevance"})
          with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
              root = ET.fromstring(r.read())
          time.sleep(3.1)
          for e in root.findall(ATOM + "entry"):
              title = re.sub(r"\s+", " ", e.findtext(ATOM + "title") or "").strip()
              abstract = re.sub(r"\s+", " ", e.findtext(ATOM + "summary") or "").strip()
              if squash(plain) not in squash(title + " " + abstract) or title in seen:
                  continue
              seen.add(title)
              out.append({"title": title, "url": (e.findtext(ATOM + "id") or "").replace("http://", "https://"),
                          "date": (e.findtext(ATOM + "published") or "")[:10], "abstract": abstract[:1400]})
    except Exception as exc:  # noqa: BLE001  no audits is a valid answer; try again next time
        print(f"  audits: {name}: {str(exc)[:80]}", file=sys.stderr)
        return []
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False))
    return out


def evidence(item: dict, ep: dict | None, papers: list[dict]) -> dict[str, str]:
    t = item.get("tier") or {}
    checks = t.get("checks") or {}
    about = [f"Name: {item['name']}", f"Title: {item.get('title') or ''}", f"What it tests: {item.get('does') or ''}",
             f"Realism: {item.get('real') or ''}"]
    for k in ("solvable", "verifier", "judge_validated", "environment", "data_released", "human_review", "gaming"):
        if k in checks:
            c = checks[k]
            about.append(f"Check {k}: {c.get('value')}" + (f' — "{c["quote"]}"' if c.get("quote") else ""))
    for r in t.get("risks") or []:
        about.append(f"Risk: {r.get('risk')}" + (f' — "{r["quote"]}"' if r.get("quote") else ""))
    scores = []
    for kind in ("own", "agg", "paper"):
        s = item.get(kind)
        if s and s.get("pct") is not None:
            scores.append(f"{kind}: {s['pct']}% by {s.get('model') or '?'}"
                          + (f" ({s.get('source')}, {s.get('as_of')})" if kind == "agg" else "")
                          + (" [self-reported by the vendor]" if s.get("self_reported") else ""))
            if s.get("quote"):
                scores.append(f'  quote: "{s["quote"]}"')
    epoch = []
    if ep:
        c = ep.get("ceiling")
        epoch.append(f"Epoch AI ceiling (best reachable score): {c*100:.0f}%" if c not in (None, 1.0)
                     else "Epoch AI ceiling: not estimated (Epoch's default; says nothing about task validity)")
        if ep.get("baseline") is not None:
            epoch.append(f"Random baseline: {ep['baseline']*100:.0f}%")
        if ep.get("superseded_by"):
            epoch.append(f"Superseded by: {ep['superseded_by']}")
        for h in (ep.get("history") or [])[-6:]:
            epoch.append(f"Record {h['date']}: {h['score']*100:.1f}% by {h['model']}")
    aud = [f"[{p['title']}] ({p['date']}) {p['abstract']}" for p in papers]
    return {"ABOUT": "\n".join(about), "SCORES": "\n".join(scores) or "none",
            "EPOCH": "\n".join(epoch) or "not tracked by Epoch AI", "AUDITS": "\n\n".join(aud) or "none found"}


PROMPT = """Decide whether the gap between this benchmark's best score and 100% is real.

A low score means models are weak only if the tasks are valid. Broken or ambiguous tasks, wrong reference
answers, unsolvable tasks, flaky or live environments and unvalidated model graders also lower scores.

Use ONLY the text below. Do not use outside knowledge. Every quote must be copied word for word from the text.

{text}

Answer with one JSON object:
{{
 "broken_share": number or null,  // % of tasks that can NOT earn credit even for a perfect agent: wrong or missing
                                  // reference answers, unsolvable tasks, tasks whose environment cannot work.
                                  // Only if the text states such a share. NOT a human or expert score; NOT tasks
                                  // marked "uncertain" or "ambiguous" (they can still earn credit); NOT weak tests
                                  // (those let wrong answers pass); NOT grader disagreement. Else null.
 "broken_quote": "...",           // the words that state that share, or ""
 "broken_basis": "...",           // a few plain words, e.g. "an audit found 6.5% wrong answers"
 "human_baseline": {{"percent": number or null, "quote": "..."}},   // a stated human or expert score, for reference only
 "cause": "model|tasks|environment|grader|mixed|unknown",   // what the remaining gap is mostly made of
 "verdict": "real|suspect|unknown",
     // real: evidence the tasks are valid and checkable (solvability or oracle shown, human-validated answers,
     //       executable or exact-match grading, or an audit that found few problems), so the gap is models failing.
     //       "Nothing reported against it" is NOT evidence: answer unknown.
     // suspect: evidence that a material share (about 10% of tasks or more, or a large part of the gap) is the
     //       benchmark's fault: errors, ambiguity, unsolvable tasks, live or flaky environment, unvalidated grader.
     // unknown: the text does not show either.
 "evidence": [ {{"claim": "...", "quote": "...", "from": "ABOUT|SCORES|EPOCH|AUDITS: <paper title>"}} ],   // at most 3
 "summary": "..."                 // one plain sentence for a reader, no jargon
}}"""


def judge(item: dict, ep: dict | None) -> dict:
    papers = audits(item["name"])
    parts = evidence(item, ep, papers)
    text = "\n\n".join(f"=== {k} ===\n{v}" for k, v in parts.items())
    reply = llm.complete(PROMPT.format(text=text), "You review AI benchmarks. You reply with JSON only.", EFFORT)
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        raise RuntimeError(f"no JSON in reply: {reply[:160]!r}")
    a = json.loads(m.group(0))
    hay = squash(text)
    ok = lambda q: isinstance(q, str) and len(q.strip()) > 8 and squash(q) in hay  # noqa: E731
    ev = [e for e in (a.get("evidence") or [])[:3] if isinstance(e, dict) and ok(e.get("quote"))]
    share = a.get("broken_share")
    cq = a.get("broken_quote") if ok(a.get("broken_quote")) else None
    ceiling = None
    if isinstance(share, (int, float)) and cq and 0 < share < 60:
        ceiling = round(100 - share, 1)
    else:
        cq = None
    hb = a.get("human_baseline") if isinstance(a.get("human_baseline"), dict) else {}
    human = {"percent": hb.get("percent"), "quote": hb.get("quote")} if isinstance(hb.get("percent"), (int, float)) and ok(hb.get("quote")) else None
    verdict = a.get("verdict") if a.get("verdict") in ("real", "suspect", "unknown") else "unknown"
    if verdict != "unknown" and not ev:
        verdict = "unknown"        # a verdict needs at least one quote that is really in the text
    if verdict == "real" and not any(not (e.get("from") or "").startswith(("EPOCH", "SCORES")) for e in ev):
        verdict = "unknown"        # "real" needs evidence about the tasks themselves, not just scores
    return {
        "key": item["key"], "name": item["name"], "date": dt.date.today().isoformat(), "model": llm.model(),
        "prompt_version": PROMPT_VERSION, "ceiling": ceiling, "ceiling_quote": cq,
        "ceiling_basis": (a.get("broken_basis") or "")[:120] if ceiling is not None else None, "human_baseline": human,
        "cause": a.get("cause") if a.get("cause") in ("model", "tasks", "environment", "grader", "mixed", "unknown") else "unknown",
        "verdict": verdict, "evidence": ev, "summary": (a.get("summary") or "")[:300],
        "audits": [{"title": p["title"], "url": p["url"], "date": p["date"]} for p in papers],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--redo", action="store_true", help="ask again even if the answer is recent")
    args = ap.parse_args()
    llm.load_env()
    items = [i for i in json.loads(POOL.read_text())["items"] if i.get("rank")]
    epoch = {}
    if EPOCH.exists():
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import pool
        epoch = {pool.canon_key(b["name"]): b for b in json.loads(EPOCH.read_text())["benchmarks"]}
    done = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["key"]] = r
    cutoff = (dt.date.today() - dt.timedelta(days=RECHECK_DAYS)).isoformat()
    due = [i for i in items if args.redo or i["key"] not in done or done[i["key"]].get("prompt_version") != PROMPT_VERSION
           or done[i["key"]]["date"] < cutoff]
    # Benchmarks with a score first: those are the ones the ranking orders.
    due.sort(key=lambda i: (i["rank"]["sota"] is None, -(len(i["rank"]["why"]))))
    if args.limit:
        due = due[: args.limit]
    print(f"headroom: {len(items)} popular benchmarks, {len(due)} to judge")
    # Audit searches are rate-limited, so fetch them first, one at a time.
    for n, it in enumerate(due, 1):
        audits(it["name"])
        if n % 25 == 0:
            print(f"  audit searches {n}/{len(due)}")
    failed = 0

    def one(it):
        try:
            return judge(it, epoch.get(it["key"]))
        except Exception as exc:  # noqa: BLE001
            print(f"  {it['name']}: {str(exc)[:100]}", file=sys.stderr)
            return None

    with ThreadPoolExecutor(args.workers) as pool_, OUT.open("a") as fh:
        for n, row in enumerate(pool_.map(one, due), 1):
            if row is None:
                failed += 1
                continue
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            if n % 20 == 0:
                print(f"  judged {n}/{len(due)}")
    print(f"done: {len(due) - failed} judged, {failed} failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
