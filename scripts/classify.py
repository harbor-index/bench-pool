#!/usr/bin/env python3
"""Stage 2 of the gate: an LLM reads each candidate's title and abstract.

For every candidate in data/candidates.json it decides whether the record is a
benchmark (the only inclusion rule). For benchmarks it also gives the agent
interaction mode (agentic / modified-agentic / non-agentic, Harbor Index v1
paper, Appendix D.2), one of the 10 classes and the short facts shown on the
site. The mode is a signal for the later tiering step, not a reason to drop.

Answers are appended to data/labels.jsonl and never recomputed unless
PROMPT_VERSION changes, so a daily run only pays for new candidates.

    python3 scripts/classify.py --limit 20        # try a few
    python3 scripts/classify.py                   # everything not yet labelled
    python3 scripts/classify.py --redo adapter    # ask again: Adapter List rows not labelled by the current model
    python3 scripts/classify.py --redo benchmarks # ask again: every benchmark not labelled by the current model

Backend: scripts/llm.py (the endpoint in .env, else the local `claude`
command), at medium effort. A new answer for the same record is appended and
wins.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import llm

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = ROOT / "data" / "candidates.json"
LABELS = ROOT / "data" / "labels.jsonl"
PROMPT_VERSION = 2
MODEL = "claude-sonnet-5-5"
EFFORT = "medium"
MODES = ("agentic", "modified", "non")

CLASSES = {
    1: ("Software Engineering", ["Competitive/function", "Repo issue/test", "Other"]),
    2: ("Mathematics & Reasoning", []),
    3: ("Knowledge & Long Context", []),
    4: ("Scientific Research", ["AI R&D & Self-Improvement"]),
    5: ("Agents, Tools & Systems", ["Computer Use & GUI"]),
    6: ("Data & Analytics", []),
    7: ("Professional Domains", []),
    8: ("Safety & Security", []),
    9: ("Multimodal", []),
    10: ("Games & Embodied", []),
}

PROMPT = """You label records for a catalogue of BENCHMARKS for AI agents and models. Each record is a title plus an abstract or repository description. Judge only from the text given. Do not use tools. Reply with one JSON array and nothing else.

GATE (one yes/no question)
- bench: the record itself releases or introduces a benchmark, evaluation suite or evaluation environment with tasks that others can run to compare systems. NOT a benchmark: a model, a method, an agent framework, a tool, a survey, a position paper, a training-only dataset, a results dump, a single sub-score or index of another benchmark, or a paper that only uses existing benchmarks. If the text is too thin to tell, answer false.

MODE (for benchmarks; a property of the benchmark itself)
- "agentic": explicitly designed for agent-based evaluation. Tasks assume iterative interaction with an environment (filesystem, shell, browser, GUI, external tools/APIs/MCP, simulator, game, robot, simulated user with tool calls), multi-step reasoning and/or test-driven feedback; evaluating without agent capabilities is infeasible or against the original design. A title that says "agent" is not enough.
- "non": designed for direct model evaluation. Tasks are single-pass: the model produces an answer from the prompt alone, with no tools or environment, and giving it agent capabilities would not meaningfully change what is measured (question answering, multiple choice, classification, captioning, one-shot generation). A benchmark that scores judges, retrievers or memory stores rather than an acting system is "non".
- "modified": originally single-pass, but exposing an environment (filesystem access, iterative execution, test-driven refinement) changes the outcome measurably. Typically coding or scientific-computing tasks with executable tests that were specified as one-shot generation (e.g. BigCodeBench, SciCode).

Records whose source is "LLM Stats", "Artificial Analysis", "Benchmark Saturation" or "Harbor Adapter List" are established benchmarks taken from a curated table, with only a short description. For these only, you may also use what you reliably know about the named benchmark. For "Harbor Adapter List" records bench is always true. For the other three, if you do not know the benchmark and the description is too thin, answer bench false.

For records where bench is false, return only: {"id", "bench", "why"}.

For benchmarks, return all of:
- id
- bench: true
- mode: "agentic", "modified" or "non"
- why: at most 12 words, what the system under test does
- name: the benchmark's short name as its authors write it (e.g. "SWE-bench Pro"). If unnamed, a 2-4 word descriptive name.
- cls: one number
  1 Software Engineering
  2 Mathematics & Reasoning (math, logic, puzzles, planning as pure reasoning)
  3 Knowledge & Long Context (information seeking, deep research, retrieval, memory, long documents)
  4 Scientific Research (doing science: experiments, analysis, paper reproduction, lab work, ML research)
  5 Agents, Tools & Systems (general tool use, MCP, function calling, multi-agent, web/desktop/mobile operation, agent infrastructure)
  6 Data & Analytics (SQL, spreadsheets, data science, BI)
  7 Professional Domains (finance, law, medicine, customer service, business operations, education)
  8 Safety & Security (cyber offence/defence, prompt injection, harmful actions, privacy, robustness under attack)
  9 Multimodal (perception or generation over images, audio, video, charts or documents-as-images, where that is the capability tested)
  10 Games & Embodied (games, robots, simulators, navigation)
  Pick the class of the capability being tested. A domain-specific benchmark goes to its domain, not to class 5. Use class 9 only when no other class fits better; a GUI benchmark with screenshots is class 5, a robot benchmark with cameras is class 10 (the mm field records the modality).
- sub: only these values are allowed, otherwise null
  cls 1: "Competitive/function" (algorithmic or function-level coding), "Repo issue/test" (repository-level issue fixing, tests, PRs), "Other" (everything else in software engineering); cls 1 must have one of the three
  cls 4: "AI R&D & Self-Improvement" (agents doing ML/AI research or improving themselves) or null
  cls 5: "Computer Use & GUI" (browser, desktop or mobile operation) or null
- mm: true if tasks need non-text input such as images, screenshots, audio or video
- real: at most 14 words on realism. Where the tasks come from and how close they are to real work (e.g. "Real GitHub issues from 12 repos, run in Docker"). Facts only.
- val: at most 14 words on value. What it shows that was not measurable before, or who would use it. Facts only, no praise.
- data: "public", "partial", "private" or "unknown". Is the task data released? Say "public" only if the text says so or the record is a dataset/code repository.
- scores: "yes" if the text reports model or agent results on it, "no" if it says none, else "unknown"
- traj: "yes" if agent trajectories or logs are said to be released, else "unknown"
- infra: "yes" if a runnable harness, environment, Docker images or evaluation code is said to be released, else "unknown"
- lb: "yes" if the text mentions a public leaderboard or live results site, else "unknown"
- best: the top score any system reaches on the benchmark's main success metric, as a number from 0 to 100, ONLY when the text states it explicitly as a percentage where higher is better (success rate, accuracy, pass rate, resolved rate). Otherwise null. Never compute or guess it.
- best_model: the system that got it, or null
- best_metric: 1-3 words, or null
- best_quote: the exact words from the text that state it (at most 25 words), or null

RECORDS
"""


def upgrade(row: dict) -> dict | None:
    """A stored label as a current-version label, or None if it must be asked again.

    Version 1 asked "agentic: yes/no" and had Games & Embodied as class 9. Its
    answers stay valid for non-benchmarks and for agentic benchmarks; benchmarks
    it called not agentic were stored without a class and are asked again.
    """
    version = row.get("prompt_version")
    if version == PROMPT_VERSION:
        return row
    if version != 1:
        return None
    if not row.get("bench"):
        return {k: row[k] for k in ("id", "model", "bench", "why") if k in row} | {"prompt_version": PROMPT_VERSION, "from_v1": True}
    if not row.get("agentic"):
        return None
    out = {k: v for k, v in row.items() if k != "agentic"}
    out.update({"prompt_version": PROMPT_VERSION, "mode": "agentic", "from_v1": True,
                "cls": 10 if row["cls"] == 9 else row["cls"]})
    return out


def load_labels(path: Path = LABELS) -> dict[str, dict]:
    """Current labels by candidate id. A later line wins over an earlier one."""
    done: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip():
                row = upgrade(json.loads(line))
                if row is not None:
                    done[row["id"]] = row
    return done


def load_done() -> dict[str, dict]:
    return load_labels()


def ask(model: str, batch: list[dict], workdir: str, effort: str = EFFORT) -> list[dict]:
    records = [
        {"id": c["id"], "title": c["title"], "source": ", ".join(c["sources"][:3]), "text": c["summary"][:1100]}
        for c in batch
    ]
    text = llm.complete(PROMPT + json.dumps(records, ensure_ascii=False, indent=0),
                        "You are a careful data labeller. You reply with JSON only.", effort)
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        raise RuntimeError(f"no JSON array in reply: {text[:200]!r}")
    return json.loads(match.group(0))


def clean(row: dict, candidate: dict, model: str) -> dict:
    forced = candidate.get("origin") == "adapter_list"  # a hand-kept list of benchmarks
    out = {
        "id": candidate["id"], "prompt_version": PROMPT_VERSION, "model": model,
        "bench": bool(row.get("bench")) or forced,
        "why": str(row.get("why") or "")[:160],
    }
    if not out["bench"]:
        return out
    if row.get("mode") not in MODES:
        raise ValueError(f"bad mode {row.get('mode')!r}")
    out["mode"] = row["mode"]
    cls = row.get("cls")
    if cls not in CLASSES:
        raise ValueError(f"bad class {cls!r}")
    sub = row.get("sub") if row.get("sub") in CLASSES[cls][1] else None
    if cls == 1 and sub is None:
        sub = "Other"
    best, quote = row.get("best"), row.get("best_quote")
    # Keep a score only if the quoted words are really in the abstract and contain the number.
    ok = isinstance(best, (int, float)) and 0 <= best <= 100 and isinstance(quote, str)
    if ok:
        squash = lambda s: re.sub(r"\s+", " ", s).strip().lower()
        number = re.sub(r"\.0+$", "", f"{best:g}")
        ok = squash(quote) in squash(candidate["summary"]) and number in quote
    out.update({
        "name": str(row.get("name") or candidate["title"])[:80],
        "cls": cls, "sub": sub, "mm": bool(row.get("mm")),
        "real": str(row.get("real") or "")[:200], "val": str(row.get("val") or "")[:200],
        "data": row.get("data") if row.get("data") in ("public", "partial", "private") else "unknown",
        "scores": row.get("scores") if row.get("scores") in ("yes", "no") else "unknown",
        "traj": "yes" if row.get("traj") == "yes" else "unknown",
        "infra": "yes" if row.get("infra") == "yes" else "unknown",
        "lb": "yes" if row.get("lb") == "yes" else "unknown",
        "best": float(best) if ok else None,
        "best_model": (str(row.get("best_model"))[:80] if ok and row.get("best_model") else None),
        "best_metric": (str(row.get("best_metric"))[:40] if ok and row.get("best_metric") else None),
        "best_quote": quote[:300] if ok else None,
    })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--effort", default=EFFORT, choices=("low", "medium", "high"))
    parser.add_argument("--redo", choices=("adapter", "benchmarks"),
                        help="ask again for records whose label was not made by --model")
    parser.add_argument("--batch", type=int, default=20)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, help="label at most N candidates")
    args = parser.parse_args()

    args.model = llm.model()
    candidates = json.loads(CANDIDATES.read_text())["candidates"]
    done = load_done()
    todo = [c for c in candidates if c["id"] not in done]
    if args.redo:
        stale = lambda c: c["id"] in done and done[c["id"]].get("model") != args.model
        if args.redo == "adapter":
            todo += [c for c in candidates if c["origin"] == "adapter_list" and stale(c)]
        else:
            todo += [c for c in candidates if stale(c) and done[c["id"]]["bench"]]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(candidates)} candidates, {len(done)} labelled, {len(todo)} to do", flush=True)
    if not todo:
        return 0

    batches = [todo[i : i + args.batch] for i in range(0, len(todo), args.batch)]
    lock = threading.Lock()
    stats = {"ok": 0, "failed": 0}
    workdir = tempfile.mkdtemp(prefix="bench-pool-classify-")

    def run(batch: list[dict]) -> None:
        by_id = {c["id"]: c for c in batch}
        rows: list[dict] = []
        for attempt in (1, 2):
            try:
                rows = ask(args.model, batch, workdir, args.effort)
                break
            except Exception as err:  # noqa: BLE001 - report and retry once
                print(f"  batch failed (try {attempt}): {err}", file=sys.stderr, flush=True)
        good = []
        for row in rows:
            cand = by_id.get(row.get("id")) if isinstance(row, dict) else None
            if cand is None:
                continue
            try:
                good.append(clean(row, cand, args.model))
            except ValueError as err:
                print(f"  {cand['id']}: {err}", file=sys.stderr, flush=True)
        with lock:
            with LABELS.open("a") as fh:
                for row in good:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            stats["ok"] += len(good)
            stats["failed"] += len(batch) - len(good)
            print(f"  labelled {stats['ok']}/{len(todo)} (unanswered {stats['failed']})", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run, batches))
    print(f"done: {stats['ok']} labelled, {stats['failed']} unanswered (re-run to retry)")
    return 0 if stats["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
