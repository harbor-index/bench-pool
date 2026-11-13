#!/usr/bin/env python3
"""Join candidates, gate labels and leaderboard scores into the site's data file.

Reads  data/candidates.json, data/labels.jsonl, data/leaderboards.json,
       data/leaderboard_search.jsonl
Writes web/data/benchmarks.json

Rules applied here (no model calls):
- Keep a candidate only if the gate said it is a benchmark. The agent
  interaction mode (agentic / modified / non) is a column, not a filter.
- Adapter List labels are copied next to this pipeline's own answers; where the
  two disagree the item gets a line in `diff`. The list is never the answer.
- Records with the same benchmark name are one benchmark (scripts/pool.py).
- Three kinds of score are kept apart and never mixed:
    agg    aggregator leaderboard: Radar's crawls of LLM Stats, Artificial
           Analysis and Benchmark Saturation, matched by benchmark name
    own    the benchmark's own leaderboard, found by scripts/find_leaderboards.py
    paper  the best score the paper states in its abstract
- Best known score = own, else aggregator, else paper (percentages only).
- Saturated = best known score above 90%.
- "none" (no public leaderboard) is written only when the search ran and found
  nothing and no aggregator lists the benchmark; a benchmark the search has not
  reached, or could not open, is "unchecked".
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path

import pool
from classify import CLASSES
from signals import SHARED_REPOS

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "web" / "data" / "benchmarks.json"
DROPPED = ROOT / "web" / "data" / "dropped.json"
SATURATED_ABOVE = 90.0
SEARCH = DATA / "leaderboard_search.jsonl"
HI1 = DATA / "harbor_index_v1.json"
SIGNALS = DATA / "signals.jsonl"
TIERS = DATA / "tiers.jsonl"
# Tier changes are shown from this day on. Earlier verdicts were drafts of the standard; they
# stay in data/tiers.jsonl but are not changes a reader should see.
HISTORY_FROM = "2026-11-14"
STANDARD = ROOT / "docs" / "tiering-standard.md"

MODE_NAME = {"agentic": "agentic", "modified": "modified-agentic", "non": "non-agentic"}
# The Adapter List's "Saturated" buckets as score ranges, in percent.
SAT_BUCKET = {"No (<20)": (0, 20), "Somewhat (20-50)": (20, 50), "Almost (50-80)": (50, 80), "Yes (>80)": (80, 100)}


def load_tiers() -> dict[str, list[dict]]:
    """Every judgement per benchmark key, oldest first (scripts/tier.py)."""
    rows: dict[str, list[dict]] = {}
    if TIERS.exists():
        for line in TIERS.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                rows.setdefault(row["key"], []).append(row)
    return rows


def tier_view(history: list[dict], version: str) -> tuple[dict | None, list]:
    """(the current judgement, [[date, tier, standard], ...] for the history line).

    Current means made under this standard, or under one it carries over
    (tier.current). Steps that only repeat the same tier are left out.
    """
    from tier import current
    # The history starts with the current standard: verdicts from the drafts before it
    # are kept in data/tiers.jsonl but are not a change anyone needs to see.
    trail = []
    for row in history:
        if not current(row, version):
            continue
        step = [row["date"], row["tier"], row["standard"]]
        if trail and row["date"] < HISTORY_FROM:
            trail[-1] = step                # while the standard was being worked out: keep only where it ended
        elif not trail or trail[-1][1] != step[1]:
            trail.append(step)
    valid = [row for row in history if current(row, version)]
    now = valid[-1] if valid else None
    if now:
        now = {k: now.get(k) for k in ("tier", "rule", "reason", "dimensions", "coverage", "harbor_fit", "notes",
                                        "pages", "date", "model", "standard", "read", "checks", "risks")}
    return now, trail


def covered_by(hi1_tasks: int | None, adapter: dict | None) -> str | None:
    """Why a benchmark is not a new candidate for Harbor Index, or None if it is one."""
    if hi1_tasks:
        return "v1"
    if adapter and adapter["status"] == "Merged":
        return "adapter"
    return None


def load_signals() -> dict[str, list[dict]]:
    """Every fetched signal line per benchmark key, oldest first (scripts/signals.py)."""
    rows: dict[str, list[dict]] = {}
    if SIGNALS.exists():
        for line in SIGNALS.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                rows.setdefault(row["key"], []).append(row)
    for history in rows.values():
        history.sort(key=lambda r: r["date"])
    return rows


def apply_signals(history: list[dict], metrics: dict) -> dict | None:
    """Overwrite Radar's counts with the newest fetched ones; return what the site shows."""
    if not history:
        return None
    latest: dict[str, dict] = {}
    for row in history:                     # the newest line that has each source
        for source in ("github", "s2", "hf"):
            if source in row:
                if source == "github" and row[source]["repo"].lower() in SHARED_REPOS:
                    continue                # an aggregator's repository, fetched by an earlier version
                latest[source] = dict(row[source], date=row["date"])
    if not latest:
        return None
    gh, s2, hf = latest.get("github"), latest.get("s2"), latest.get("hf")
    if gh:
        metrics.update(stars=gh["stars"], forks=gh["forks"])
    if s2 and s2.get("citations") is not None:
        metrics.update(citations=s2["citations"], influential_citations=s2.get("influential") or 0)
    if hf:
        metrics.update(likes=hf["likes"], downloads=hf.get("downloads") or 0)
    trend = [[r["date"], r.get("github", {}).get("stars"), r.get("s2", {}).get("citations")] for r in history]
    return {
        "checked": history[-1]["date"],
        "repo": gh and gh["repo"], "pushed": gh and gh["pushed"], "created": gh and gh["created"],
        "archived": bool(gh and gh["archived"]),
        "published": s2 and s2.get("published"), "venue": s2 and s2.get("venue"),
        "dataset": hf and hf["dataset"], "gated": bool(hf and (hf["gated"] or hf["private"])),
        "trend": trend if len(trend) > 1 else None,
    }


def differences(adapter: dict | None, mode: str, best: float | None, basis: str | None) -> list[dict]:
    """Where the Adapter List row and this pipeline's findings disagree."""
    if not adapter:
        return []
    out = []
    if adapter["mode"] and adapter["mode"] != mode:
        out.append({"field": "mode", "list": MODE_NAME[adapter["mode"]], "ours": MODE_NAME[mode]})
    bucket = SAT_BUCKET.get(adapter["saturated"])
    if bucket and best is not None and not (bucket[0] <= best <= bucket[1]):
        out.append({"field": "saturation", "list": adapter["saturated"], "ours": f"{best:g}% ({basis})"})
    return out


def main() -> None:
    bundle, candidates, labels, benchmarks = pool.load()

    boards: dict[str, list[dict]] = {}
    for entry in json.loads((DATA / "leaderboards.json").read_text()):
        if entry.get("raw") is not None:
            boards.setdefault(pool.canon_key(entry["name"]), []).append(entry)

    searched: dict[str, dict] = {}
    if SEARCH.exists():
        for line in SEARCH.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                searched[row["key"]] = row

    hi1 = {}
    if HI1.exists():
        hi1 = {pool.canon_key(name): n for name, n in json.loads(HI1.read_text())["tasks"].items()}
    hi1_seen = set()

    signals = load_signals()
    tiers = load_tiers()
    import re
    version = re.search(r"^Version (\S+)", STANDARD.read_text(), re.M).group(1) if STANDARD.exists() else "none"

    kept = sum(len(b["members"]) for b in benchmarks)
    items = []
    for bench in benchmarks:
        key, members, member_labels = bench["key"], bench["members"], bench["labels"]
        lead = members[0]
        lab = member_labels[0]

        links: dict[str, str] = {}
        for member in members:
            for link in member["links"]:
                links.setdefault(link["url"], link["kind"])
        metrics: dict[str, float] = {}
        for member in members:
            for name, value in member["metrics"].items():
                metrics[name] = max(metrics.get(name, 0), value)
        sig = apply_signals(signals.get(key, []), metrics)
        dates = sorted(m["published"] for m in members if m["published"])
        date_basis = "radar" if dates else None
        # Radar's date is often a revision; Semantic Scholar's is the first publication.
        # Adapter List and leaderboard rows carry no date of their own.
        if sig and sig["published"] and (not dates or sig["published"] < dates[0]):
            dates, date_basis = [sig["published"]], "paper"
        elif sig and sig["created"] and not dates:
            dates, date_basis = [sig["created"]], "repository created"
        seen = sorted(m["first_seen"] for m in members if m["first_seen"])

        # Aggregator leaderboard: the crawl row with a percentage, newest crawl first.
        agg = None
        rows = sorted(boards.get(key, []), key=lambda e: (e.get("pct") is not None, e["as_of"]), reverse=True)
        if rows:
            top = rows[0]
            agg = {k: top.get(k) for k in ("pct", "raw", "scale", "model", "org", "source", "url", "as_of",
                                            "self_reported", "models")}
            links.setdefault(top["url"], "leaderboard")

        # The benchmark's own leaderboard, as found by the search.
        found = searched.get(key)
        own = None
        search = {"status": "unchecked", "note": "not searched yet"}
        if found:
            status = found["status"] if found["status"] in ("found", "listed", "none") else "unchecked"
            search = {"status": status, "checked": found["checked"], "pages": found.get("pages_read", 0),
                      "note": found.get("note") or "", "url": found.get("url")}
            if status == "found":
                own = {k: found.get(k) for k in ("pct", "raw", "unit", "metric", "model", "url", "entries", "quote",
                                                 "higher_better")}
                own["found"] = found.get("first_found") or found["checked"]
                own["checked"] = found["checked"]
            if status in ("found", "listed") and found.get("url"):
                links.setdefault(found["url"], "leaderboard")

        paper = next(({"pct": l["best"], "model": l["best_model"], "metric": l["best_metric"], "quote": l["best_quote"]}
                      for l in member_labels if l.get("best") is not None), None)
        best, basis = None, None
        for kind, score in (("own", own), ("aggregator", agg), ("paper", paper)):
            if score and score["pct"] is not None:
                best, basis = score["pct"], kind
                break

        # One word for the leaderboard column.
        if own and agg:
            lb = "both"
        elif own:
            lb = "own"
        elif agg:
            lb = "aggregator"
        elif search["status"] == "listed":
            lb = "listed"       # an own leaderboard exists; its top score could not be read
        elif search["status"] == "none":
            lb = "none"         # searched, nothing found
        else:
            lb = "unchecked"

        def first(field: str, good: tuple) -> str:
            return next((l[field] for l in member_labels if l.get(field) in good), "unknown")

        kinds = set(links.values())
        data = first("data", ("public", "partial", "private"))
        if data == "unknown" and "data" in kinds:
            data = "public"  # a dataset page is linked
        infra = first("infra", ("yes",))
        if infra == "unknown" and "code" in kinds:
            infra = "repo"  # a code repository is linked; contents not checked

        adapter = next((m["adapter"] for m in members if m["origin"] == "adapter_list"), None)
        if key in hi1:
            hi1_seen.add(key)
        origins = {m["origin"] for m in members}

        tier, tier_trail = tier_view(tiers.get(key, []), version)
        covered = covered_by(hi1.get(key), adapter)

        items.append({
            "id": lead["id"], "key": key, "name": bench["name"],
            "tier": tier, "tier_trail": tier_trail, "covered": covered,
            "title": lead["title"],
            "mode": lab["mode"], "adapter": adapter, "hi1": hi1.get(key),
            "diff": differences(adapter, lab["mode"], best, basis),
            "cls": lab["cls"], "sub": lab["sub"], "mm": any(l["mm"] for l in member_labels),
            "date": dates[0] if dates else None, "date_basis": date_basis, "seen": seen[0] if seen else None,
            "sig": sig,
            "origin": next(o for o in pool.ORIGIN_ORDER if o in origins),
            "crawl": any(m["origin"] == "leaderboard" for m in members),
            "does": lab["why"], "real": lab["real"], "val": lab["val"],
            "tags": sorted({t for m in members for t in m["radar_categories"] + m["radar_tags"]}),
            "sources": sorted({s for m in members for s in m["sources"]}),
            "links": [{"url": u, "kind": k} for u, k in links.items()][:10],
            "authors": lead["authors"][:3], "author_count": lead["author_count"],
            "orgs": lead["organizations"][:4], "metrics": metrics,
            "cov": {
                "data": data,
                "scores": "yes" if agg or own else first("scores", ("yes", "no")),
                "traj": first("traj", ("yes",)),
                "infra": infra,
            },
            "lb": lb, "lb_hint": any(l.get("lb") == "yes" for l in member_labels),
            "agg": agg, "own": own, "paper": paper, "search": search, "best": best, "basis": basis,
            "sat": (best > SATURATED_ABOVE) if best is not None else None,
        })

    import tier as tiering
    today = dt.date.today()
    for item in items:
        item["new"] = tiering.is_new(item, today)
    open_items = [i for i in items if not i["covered"]]
    items.sort(key=lambda i: (i["date"] or "0000", i["name"].lower()), reverse=True)
    first_day, last_day, n_days = bundle["snapshots"]
    counts = bundle["counts"]
    meta = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "snapshots": {"first": first_day, "last": last_day, "days": n_days},
        "funnel": {
            "records": counts["records"],
            "candidates": counts["candidates"] + counts.get("leaderboard_candidates", 0)
                          + counts.get("adapter_list_candidates", 0),
            "labelled": len(labels),
            "unlabelled": len(candidates) - len(labels),
            "kept_records": kept,
            "benchmarks": len(items),
            "by_mode": dict(Counter(i["mode"] for i in items)),
            "not_benchmark": sum(not l["bench"] for l in labels.values()),
        },
        "signals": {
            "fetched": sum(i["sig"] is not None for i in items),
            "stars": sum("stars" in i["metrics"] and i["sig"] is not None and bool(i["sig"]["repo"]) for i in items),
            "citations": sum(i["sig"] is not None and i["sig"]["published"] is not None or
                             (i["sig"] is not None and i["metrics"].get("citations", 0) > 0) for i in items),
            "last": max((i["sig"]["checked"] for i in items if i["sig"]), default=None),
        },
        "adapter_list": {
            "rows": counts.get("adapter_list_candidates", 0),
            "in_pool": sum(i["adapter"] is not None for i in items),
            "also_in_radar": sum(i["adapter"] is not None and i["origin"] == "snapshot" for i in items),
            "mode_differs": sum(any(d["field"] == "mode" for d in i["diff"]) for i in items),
            "saturation_differs": sum(any(d["field"] == "saturation" for d in i["diff"]) for i in items),
        },
        "gate": {
            "no_agent_word_records": counts.get("no_agent_word_records", 0),
            "traction_records": counts.get("traction_records", 0),
            "traction_bar": counts.get("traction_bar", {}),
            "adapter_mode_labelled": sum(bool(i["adapter"] and i["adapter"]["mode"]) for i in items),
            "adapter_mode_agree": sum(bool(i["adapter"] and i["adapter"]["mode"] == i["mode"]) for i in items),
        },
        "tiering": {
            "standard": version,
            "run": max((i["tier"]["date"] for i in items if i["tier"]), default=None),
            "judged": sum(i["tier"] is not None for i in open_items),
            "by_agent": sum(bool(i["tier"] and i["tier"]["model"]) for i in open_items),
            "by_rule": sum(bool(i["tier"] and not i["tier"]["model"]) for i in open_items),
            "candidates": len(open_items),
            "covered": dict(Counter(i["covered"] for i in items if i["covered"])),
            "new": sum(i["new"] for i in open_items),
            "tiers": dict(Counter(i["tier"]["tier"] for i in open_items if i["tier"])),
            "tiers_new": dict(Counter(i["tier"]["tier"] for i in open_items if i["tier"] and i["new"])),
            "rules": dict(Counter(i["tier"]["rule"] for i in open_items if i["tier"])),
            "models": sorted({i["tier"]["model"] for i in items if i["tier"] and i["tier"]["model"]}),
            "downgraded": sum(bool(i["tier"] and i["tier"]["notes"]) for i in open_items),
            "read": {
                "paper": sum(bool(i["tier"] and (i["tier"].get("read") or {}).get("paper_chars")) for i in open_items),
                "paper_cut": sum(bool(i["tier"] and (i["tier"].get("read") or {}).get("paper_cut")) for i in open_items),
                "readme_only": sum(bool(i["tier"] and i["tier"].get("read") and not i["tier"]["read"]["paper_chars"]
                                        and i["tier"]["read"]["readme_chars"]) for i in open_items),
                "nothing": sum(bool(i["tier"] and i["tier"]["rule"] == "T0") for i in open_items),
            },
            "hi1": dict(Counter(i["tier"]["tier"] for i in items if i["tier"] and i["hi1"])),
            "excluded_by_list": dict(Counter(i["tier"]["tier"] for i in items
                                             if i["tier"] and i["adapter"] and i["adapter"]["include"] == "exclude")),
        },
        "harbor_index_v1": {"benchmarks": len(hi1), "in_pool": len(hi1_seen),
                            "missing": sorted(k for k in hi1 if k not in hi1_seen)},
        "saturated_above": SATURATED_ABOVE,
        "leaderboards": {
            "aggregator": sum(i["agg"] is not None for i in items),
            "own": sum(i["own"] is not None for i in items),
            "own_listed": sum(i["search"]["status"] == "listed" for i in items),
            "paper": sum(i["paper"] is not None for i in items),
            "searched_none": sum(i["search"]["status"] == "none" for i in items),
            "unchecked": sum(i["search"]["status"] == "unchecked" for i in items),
            "from_crawls": sum(i["crawl"] for i in items),
            "last_search": max((i["search"].get("checked") or "" for i in items), default="") or None,
        },
        "label_models": sorted({l["model"] for l in labels.values()}),
        "classes": [{"id": cid, "name": name, "subs": subs} for cid, (name, subs) in CLASSES.items()],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"meta": meta, "items": items}, ensure_ascii=False, separators=(",", ":")))

    # What the gate turned away, with its one-line reason, for the Filter page.
    dropped = [{"id": cid, "title": candidates[cid]["title"], "why": lab["why"], "origin": candidates[cid]["origin"],
                "src": candidates[cid]["sources"][:2], "date": candidates[cid]["published"],
                "url": next((l["url"] for l in candidates[cid]["links"]), None)}
               for cid, lab in labels.items() if not lab["bench"]]
    dropped.sort(key=lambda d: (d["date"] or "", d["title"]), reverse=True)
    DROPPED.write_text(json.dumps(dropped, ensure_ascii=False, separators=(",", ":")))

    print(json.dumps(meta["funnel"]))
    by_class = Counter(i["cls"] for i in items)
    for cid, (name, _) in CLASSES.items():
        mine = [i for i in items if i["cls"] == cid]
        scored = [i for i in mine if i["best"] is not None]
        print(f"  {name:28} {by_class[cid]:4}  aggregator {sum(i['agg'] is not None for i in mine):3}  "
              f"own {sum(i['own'] is not None for i in mine):3}  "
              f"scored {len(scored):3}  saturated {sum(bool(i['sat']) for i in mine):3}")
    print("leaderboards:", json.dumps(meta["leaderboards"]))
    print("mode:", meta["funnel"]["by_mode"], " adapter list:", json.dumps(meta["adapter_list"]))
    print("tiering:", json.dumps(meta["tiering"]))
    print("harbor index v1:", json.dumps(meta["harbor_index_v1"]))
    print("best score from:", dict(Counter(i["basis"] for i in items)), " leaderboard column:", dict(Counter(i["lb"] for i in items)))
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
