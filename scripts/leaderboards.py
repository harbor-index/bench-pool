#!/usr/bin/env python3
"""Read Radar's leaderboard crawls into one table of top scores.

Radar keeps point-in-time copies of three public score tables: LLM Stats,
Artificial Analysis and the Benchmark Saturation annotations. For each
benchmark this script records the rank-1 row: score, model, source, crawl date.

Writes data/leaderboards.json. A top score is expressed as a percentage only
when the source's scale allows it (0-1 or 0-100); Elo-style scores stay raw
and never count towards saturation.

Caveat carried over from Radar: these rows state no protocol (shots, harness,
attempts) and many are vendor self-reported.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "leaderboards"
OUT = ROOT / "data" / "leaderboards.json"
csv.field_size_limit(10**9)

# LLM Stats / Artificial Analysis categories that suggest an agentic benchmark.
# Rows with these become gate candidates; every row can still supply a score.
AGENT_CATEGORIES = {"agents", "agentic", "tool_calling", "tool-use"}


def norm_name(name: str) -> str:
    """Lower-case letters and digits only. Greek and other non-Latin letters are
    spelled out (τ -> tau, Δ -> delta) so that "Δτ-Bench" and "τ-bench" differ."""
    out = []
    for ch in name.replace("²", "2").replace("³", "3"):
        plain = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
        if not plain and ch.isalpha():
            plain = (unicodedata.name(ch, "").split() or [""])[-1]
        out.append(plain)
    return re.sub(r"[^a-z0-9]+", "", "".join(out).lower())


def rows(name: str) -> list[dict]:
    path = RAW / name
    if not path.exists():
        raise SystemExit(f"missing {path}; run scripts/fetch.py first")
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def number(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def release_dates() -> dict[str, str]:
    """Parse benchmark_dates.yml (key line, then a `released:` line) without PyYAML."""
    path = RAW / "benchmark_dates.yml"
    dates: dict[str, str] = {}
    if not path.exists():
        return dates
    key = None
    for line in path.read_text(encoding="utf-8").splitlines():
        head = re.match(r"^  ([a-z0-9-]+:[^\s]+):\s*$", line)
        if head:
            key = head.group(1)
        found = re.match(r"^    released:\s*'?(\d{4}-\d{2}-\d{2})", line)
        if found and key:
            dates[key] = found.group(1)
    return dates


def top_rows(score_rows: list[dict]) -> dict[str, dict]:
    best: dict[str, dict] = {}
    count: dict[str, int] = {}
    for row in score_rows:
        bid = row["benchmark_id"]
        count[bid] = count.get(bid, 0) + 1
        score = number(row.get("benchmark_score"))
        if score is None:
            continue
        if bid not in best or score > number(best[bid]["benchmark_score"]):
            best[bid] = row
    for bid, row in best.items():
        row["_models"] = count[bid]
    return best


def main() -> None:
    dates = release_dates()
    entries: list[dict] = []

    # LLM Stats, crawled 2026-08-17
    tops = top_rows(rows("llm_stats_benchmark_scores_2026-08-17.csv"))
    for bench in rows("llm_stats_benchmarks_2026-08-17.csv"):
        bid = bench["benchmark_id"]
        cats = json.loads(bench.get("categories") or "[]")
        top = tops.get(bid)
        entry = {
            "key": norm_name(bench["name"]), "name": bench["name"], "source": "LLM Stats",
            "source_id": bid, "url": f"https://llm-stats.com/benchmarks/{bid}", "as_of": "2026-08-17",
            "description": bench.get("description") or "", "categories": cats,
            "multimodal": bench.get("modality") not in ("", "text"),
            "released": dates.get(f"llm-stats:{bid}"),
            "candidate": bool(AGENT_CATEGORIES & set(cats)),
        }
        if top:
            score, scale = number(top["benchmark_score"]), number(top.get("benchmark_max_score"))
            entry.update({
                # A percentage only on a 0-1 or 0-100 scale, and only if the score fits it.
                "pct": round(score * 100 / scale, 1) if scale in (1.0, 100.0) and 0 <= score <= scale else None,
                "raw": score, "scale": scale if scale and score <= scale else None, "model": top["model_name"],
                "org": top.get("organization_name") or None,
                "self_reported": top.get("self_reported") == "True", "models": top["_models"],
            })
        entries.append(entry)

    # Artificial Analysis, crawled 2026-08-25 (runs the evaluations itself)
    tops = top_rows(rows("artificial_analysis_benchmark_scores_2026-08-25.csv"))
    for bench in rows("artificial_analysis_benchmarks_2026-08-25.csv"):
        bid = bench["benchmark_id"]
        cats = json.loads(bench.get("categories") or "[]")
        top = tops.get(bid)
        entry = {
            "key": norm_name(bench["name"]), "name": bench["name"], "source": "Artificial Analysis",
            "source_id": bid, "url": bench.get("detail_source_url") or "https://artificialanalysis.ai/",
            "as_of": "2026-08-25", "description": bench.get("description") or "", "categories": cats,
            "multimodal": "multimodal" in cats, "released": dates.get(f"artificial-analysis:{bid}"),
            "candidate": bool(AGENT_CATEGORIES & set(cats)),
        }
        if top:
            score = number(top["benchmark_score"])
            entry.update({
                "pct": round(score * 100, 1) if 0 <= score <= 1 else None, "raw": score,
                "scale": 1.0 if 0 <= score <= 1 else None,
                "model": top["model_name"], "org": top.get("organization_name") or None,
                "self_reported": False, "models": top["_models"],
            })
        entries.append(entry)

    # Benchmark Saturation annotations (evaleval, MIT), copied 2026-11-04
    tops = top_rows(rows("benchmark_saturation_benchmark_scores_2026-11-04.csv"))
    for bench in rows("benchmark_saturation_benchmarks_2026-11-04.csv"):
        bid = bench["benchmark_id"]
        top = tops.get(bid)
        name = re.split(r":\s", bench["name"], maxsplit=1)[0].strip()
        entry = {
            "key": norm_name(name), "name": name, "source": "Benchmark Saturation",
            "source_id": bid, "url": bench.get("detail_source_url") or "https://github.com/evaleval/benchmark-saturation",
            "as_of": "2026-11-04", "description": bench["name"], "categories": [],
            "multimodal": False, "released": bench.get("released") or None,
            # Too few rows to guess from; let the classifier see all 60.
            "candidate": True,
        }
        if top:
            score = number(top["benchmark_score"])
            pct = score * 100 if score <= 1 else score
            is_pct = "elo" not in (bench.get("metric") or "").lower() and 0 <= pct <= 100
            entry.update({
                "pct": round(pct, 1) if is_pct else None, "raw": score, "scale": 100.0 if is_pct else None,
                "model": top["model_name"], "org": top.get("organization_name") or None,
                "self_reported": None, "models": top["_models"],
            })
        entries.append(entry)

    OUT.write_text(json.dumps(entries, ensure_ascii=False, indent=1))
    scored = [e for e in entries if e.get("raw") is not None]
    print(f"leaderboard rows: {len(entries)}, with a top score: {len(scored)}, "
          f"as a percentage: {sum(e.get('pct') is not None for e in entries)}, "
          f"gate candidates: {sum(e['candidate'] for e in entries)}")


if __name__ == "__main__":
    main()
