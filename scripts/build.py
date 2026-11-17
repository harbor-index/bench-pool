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
import re
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
SOURCE_SEARCH = DATA / "source_search.json"
SIGNALS = DATA / "signals.jsonl"
TIERS = DATA / "tiers.jsonl"
EPOCH = DATA / "epoch.json"
HEADROOM = DATA / "headroom.jsonl"
READINESS = DATA / "readiness.jsonl"
POPULAR_MODELS = 10       # LLM Stats: at least this many models report a score (mostly from model cards)
HEADROOM_SATURATED = 10   # within this many points of the ceiling counts as saturated
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


FAMILY_DROP = re.compile(r"\([^)]*\)|\b(?:v?\d+(?:[.\-]\d+)*[a-z]?|verified|lite|mini|hard|easy|full|val|subset|split|"
                         r"diamond|private|public|sample|cpu only|leaderboard|benchmark|bench)\b", re.I)


def family_key(name: str) -> str:
    """Name with versions, years, splits and subset words removed: Terminal-Bench 2.1 -> terminal,
    SWE-bench Verified -> swe, AIME 2025 -> aime. Different benchmarks keep different keys
    (SWE-bench Pro -> swe pro, LiveCodeBench Pro -> livecode pro)."""
    s = re.sub(r"(?i)bench", " bench ", name.replace("’", "'"))
    s = FAMILY_DROP.sub(" ", s)
    return pool.canon_key(re.sub(r"\s+", " ", s).strip() or name)


def harbor_match(items: list[dict]) -> None:
    """Mark what Harbor already has (scripts/harbor_status.py): exact name, or the same family."""
    path = DATA / "harbor_status.json"
    hs = json.loads(path.read_text()) if path.exists() else {"registry": [], "hub": []}
    exact: dict[str, list[str]] = {}
    fam: dict[str, list[str]] = {}
    for r in hs["registry"]:
        label = f"registry: {r['name']}" + (f" {r['version']}" if r.get("version") else "")
        exact.setdefault(pool.canon_key(r["name"].replace("-", " ").replace("_", " ")), []).append(label)
        fam.setdefault(family_key(r["name"].replace("-", " ").replace("_", " ")), []).append(label)
    for slug in hs["hub"]:
        name = re.sub(r"(\d)-(\d)", r"\1.\2", slug.split("/", 1)[1]).replace("-", " ").replace("_", " ")
        label = f"hub: {slug}"
        exact.setdefault(pool.canon_key(name), []).append(label)
        fam.setdefault(family_key(name), []).append(label)
    families: dict[str, list[dict]] = {}
    for it in items:
        it["fkey"] = family_key(it["name"])
        families.setdefault(it["fkey"], []).append(it)
    for it in items:
        members = [m for m in families[it["fkey"]] if m is not it]
        here = exact.get(it["key"], [])
        in_harbor = sorted({f"pool: {m['name']} ({'Harbor Index v1' if m['covered'] == 'v1' else 'adapter'})" for m in members if m["covered"]}
                           | set(fam.get(it["fkey"], [])) - set(here))
        it["harbor"] = {
            "status": it["covered"] or ("hub" if any(h.startswith("hub:") for h in here) else "registry" if here else None),
            "here": here[:6], "family": in_harbor[:8],
        }
        it["family"] = [{"id": m["id"], "name": m["name"], "covered": m["covered"]} for m in members][:12]
        del it["fkey"]


def best_comparable(own: dict | None, rows: list[dict], paper: dict | None, published: str | None):
    """The one best score the Board, the tiers and the Ranking all use.

    The highest percentage from the benchmark's own leaderboard or any aggregator (LLM Stats, Artificial
    Analysis, Benchmark Saturation, Epoch AI). A table that lists a single system is not a leaderboard and
    only counts when nothing else exists. The paper's own figure counts only while the benchmark is under a
    year old: later systems have usually beaten it.
    """
    cands = []
    if own and own.get("pct") is not None:
        cands.append({"pct": own["pct"], "kind": "own", "source": "own leaderboard", "model": own.get("model"),
                      "as_of": own.get("found"), "url": own.get("url"), "systems": own.get("entries")})
    for r in rows:
        if r.get("pct") is not None:
            cands.append({"pct": r["pct"], "kind": "aggregator", "source": r["source"], "model": r.get("model"),
                          "org": r.get("org"), "as_of": r.get("as_of"), "url": r.get("url"), "systems": r.get("models"),
                          "self_reported": r.get("self_reported"), "raw": r.get("raw"), "scale": r.get("scale"),
                          "models": r.get("models")})
    multi = [c for c in cands if c["kind"] == "own" or (c.get("systems") or 0) != 1]
    young = published and published >= (dt.date.today() - dt.timedelta(days=365)).isoformat()
    if multi:
        top = max(multi, key=lambda c: (c["pct"], c.get("as_of") or ""))
        return top["pct"], top["kind"], top
    # A table with one system is one report, like a paper's figure: it only counts while recent.
    singles = [c for c in cands if c.get("as_of") and c["as_of"] >= (dt.date.today() - dt.timedelta(days=365)).isoformat()]
    if singles and young:
        top = dict(max(singles, key=lambda c: c["pct"]), single=True)
        return top["pct"], top["kind"], top
    if paper and paper.get("pct") is not None and young:
        return paper["pct"], "paper", {"pct": paper["pct"], "kind": "paper", "source": "paper", "model": paper.get("model"),
                                       "as_of": published, "systems": None}
    return None, None, None


def ranking(key: str, why: list[str], score: dict | None, ep: dict | None, judged: dict | None) -> dict | None:
    """Where a popular benchmark stands: best score, the reachable ceiling, and whether the gap is real.

    band  saturated  within HEADROOM_SATURATED points of the ceiling
          real       a gap, and the evidence says models fail valid tasks
          suspect    a gap, but much of it looks like broken tasks, environment or grading
          unverified a gap, but no evidence either way yet (or not judged yet by scripts/headroom.py)
          noscore    no percentage score anywhere
    """
    if not why:
        return None
    sota = score
    # Ceiling: the best score a perfect agent could reach. Only two things lower it: Epoch AI's estimate, and
    # a stated share of tasks that cannot earn credit (wrong reference answers, unsolvable tasks). A human
    # baseline is not a ceiling, and an estimate that some system has already beaten is dropped.
    ceiling, basis, quote, note = 100.0, "nominal maximum: no evidence that any task cannot earn credit", None, None
    options = []
    if ep and ep.get("ceiling") not in (None, 1.0):
        options.append((round(ep["ceiling"] * 100, 1), "Epoch AI's estimate of the reachable score", None))
    if judged and judged.get("ceiling") is not None and judged.get("ceiling_quote"):
        options.append((judged["ceiling"], judged.get("ceiling_basis") or "a stated share of broken tasks", judged["ceiling_quote"]))
    seen_max = max([sota["pct"] if sota else 0] + [h["score"] * 100 for h in ((ep or {}).get("history") or [])])
    for value, why_, q in sorted(options):
        if value + 0.05 < seen_max:
            note = f"An estimate of {value:g}% ({why_}) has already been beaten ({seen_max:.1f}%), so it is not used."
            continue
        ceiling, basis, quote = value, why_, q
        break
    out = {
        "why": why, "sota": sota, "ceiling": ceiling, "ceiling_basis": basis, "ceiling_quote": quote, "ceiling_note": note,
        "human": (judged or {}).get("human_baseline"),
        "headroom": round(ceiling - sota["pct"], 1) if sota else None,
        "velocity": ep.get("velocity") if ep else None,
        "history": (ep.get("history") or [])[-24:] if ep else [],
        "epoch_models": ep.get("models") if ep else None,
        "superseded_by": ep.get("superseded_by") if ep else None,
        "judged": bool(judged),
    }
    if judged:
        out.update({k: judged.get(k) for k in ("verdict", "cause", "summary", "evidence", "audits", "date", "model")})
    if sota is None:
        band = "noscore"
    elif out["headroom"] <= HEADROOM_SATURATED:
        band = "saturated"
    elif judged and judged.get("verdict") in ("real", "suspect"):
        band = judged["verdict"]
    else:
        band = "unverified"
    out["band"] = band
    if out["velocity"] and out["velocity"] > 0 and out["headroom"] and out["headroom"] > HEADROOM_SATURATED:
        out["months_left"] = round((out["headroom"] - HEADROOM_SATURATED) / out["velocity"], 1)
    return out


def main() -> None:
    bundle, candidates, labels, benchmarks = pool.load()

    boards: dict[str, list[dict]] = {}
    for entry in json.loads((DATA / "leaderboards.json").read_text()):
        if entry.get("raw") is not None:
            boards.setdefault(pool.canon_key(entry["name"]), []).append(entry)

    # Popular: tracked by Epoch AI, Artificial Analysis or Benchmark Saturation, or reported by
    # many models on LLM Stats. Rows without a score count too (Epoch lists some it has not run).
    popular: dict[str, list[str]] = {}
    for entry in json.loads((DATA / "leaderboards.json").read_text()):
        src, n = entry["source"], entry.get("models") or 0
        if src in ("Epoch AI", "Artificial Analysis", "Benchmark Saturation") or (src == "LLM Stats" and n >= POPULAR_MODELS):
            why = f"{src}" + (f", {n} models" if n else "")
            popular.setdefault(pool.canon_key(entry["name"]), []).append(why)
    epoch = {}
    if EPOCH.exists():
        ep = json.loads(EPOCH.read_text())
        epoch = {pool.canon_key(b["name"]): b for b in ep["benchmarks"]}
        epoch_as_of = ep["as_of"]
    headroom = {}
    if HEADROOM.exists():
        for line in HEADROOM.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                headroom[row["key"]] = row      # a later line wins

    readiness = {}
    if READINESS.exists():
        for line in READINESS.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                readiness[row["key"]] = row

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
    source_search = json.loads(SOURCE_SEARCH.read_text()) if SOURCE_SEARCH.exists() else {}
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

        # Aggregator leaderboard: the highest percentage any aggregator shows (some stop at older
        # models, so the newest crawl is not always the best score), then the newest.
        agg = None
        rows = sorted(boards.get(key, []), key=lambda e: (e.get("pct") is not None, e.get("pct") or 0, e["as_of"]), reverse=True)
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
        best, basis, score = best_comparable(own, boards.get(key, []), paper, dates[0] if dates else None)
        if score and score["kind"] == "aggregator":
            agg = {k: score.get(k) for k in ("pct", "raw", "scale", "model", "org", "source", "url", "as_of",
                                              "self_reported", "models")}

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

        # A paper found by searching for the benchmark's name (scripts/find_sources.py).
        looked = source_search.get(key)
        if looked and looked.get("arxiv"):
            links.setdefault(f"https://arxiv.org/abs/{looked['arxiv']}", "paper")
        if looked and looked.get("repo"):
            links.setdefault(f"https://github.com/{looked['repo']}", "code")
        adapter = next((m["adapter"] for m in members if m["origin"] == "adapter_list"), None)
        if key in hi1:
            hi1_seen.add(key)
        origins = {m["origin"] for m in members}

        tier, tier_trail = tier_view(tiers.get(key, []), version)
        covered = covered_by(hi1.get(key), adapter)
        why_popular = popular.get(key, []) + (["Harbor Index v1"] if hi1.get(key) else [])
        if not why_popular and tier and tier.get("tier") == "recommend" and not covered:
            why_popular = ["Recommended new candidate"]      # so the Ranking also covers the recommendations
        rank = ranking(key, why_popular, score, epoch.get(key), headroom.get(key))

        items.append({
            "id": lead["id"], "key": key, "name": bench["name"], "_records": [m["id"] for m in members],
            "tier": tier, "tier_trail": tier_trail, "covered": covered,
            "source_search": looked and {k: looked.get(k) for k in ("date", "searched", "query", "arxiv", "title", "why")},
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
            "agg": agg, "own": own, "paper": paper, "search": search, "best": best, "basis": basis, "score": score,
            "sat": (best > SATURATED_ABOVE) if best is not None else None,
            "rank": rank,
            "readiness": {k: v for k, v in readiness[key].items() if k not in ("key", "name")} if key in readiness else None,
        })

    harbor_match(items)
    import tier as tiering
    today = dt.date.today()
    for item in items:
        item["new"] = tiering.is_new(item, today)
    open_items = [i for i in items if not i["covered"]]
    items.sort(key=lambda i: (i["date"] or "0000", i["name"].lower()), reverse=True)
    first_day, last_day, n_days = bundle["snapshots"]
    counts = bundle["counts"]
    ranked = [i for i in items if i["rank"]]
    ranking_meta = {
        "popular": len(ranked), "epoch_as_of": epoch_as_of if epoch else None,
        "bands": {b: sum(1 for i in ranked if i["rank"]["band"] == b) for b in ("real", "suspect", "unverified", "saturated", "noscore")},
        "judged": sum(1 for i in ranked if i["rank"].get("judged")),
    }
    meta = {
        "ranking": ranking_meta,
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
            "searched_for_source": sum(i["source_search"] is not None for i in open_items),
            "source_found": sum(bool(i["source_search"] and i["source_search"]["arxiv"]) for i in open_items),
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
    import feed
    redirects = feed.assign_ids(items)
    for it in items:
        del it["_records"]
        for f in it.get("family") or []:
            f["pid"] = next((x["pid"] for x in items if x["id"] == f["id"]), None)
    build = feed.write_feed(items, meta)
    meta["build_id"] = build["build_id"]
    meta["redirects"] = {k: v for k, v in redirects.items() if k != v}
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
