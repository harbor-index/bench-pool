"""Permanent ids and the change feed, used by scripts/build.py.

Permanent ids
  Every benchmark gets an id like bp-000123 the first time it enters the pool, and keeps it. The site's
  older ids (the lead record's id, e.g. r-0d8bc3c4d5 or arxiv-2611-17621) change when a better record
  leads the group, so they are kept only as redirects. data/ids.json (committed) holds:
    next        the next number to hand out
    by_key      benchmark key -> permanent id
    by_record   every record id ever seen in a benchmark -> permanent id
    merged      permanent id that disappeared into another -> the one that stayed
  A benchmark keeps its id when its key changes, as long as one of its records was seen before. When two
  benchmarks merge, the older id stays and the other becomes a redirect.

Change feed (static files next to the site, so a script can follow the pool without scraping it)
  web/data/v1/latest.json            build id, time, previous build, counts, file paths
  web/data/v1/changes/<build>.json   events since the previous build
  web/data/v1/changes/index.json     the last 90 builds
  web/data/v1/state.json             what the next build compares against
  Events: discovered, removed, merged, tier_changed, band_changed, score_changed (2+ points),
  harbor_changed, covered_changed, renamed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDS = ROOT / "data" / "ids.json"
V1 = ROOT / "web" / "data" / "v1"
KEEP_BUILDS = 90


def assign_ids(items: list[dict]) -> dict[str, str]:
    """Give each item a permanent "pid". Returns {any old id or pid: current pid} for redirects."""
    db = json.loads(IDS.read_text()) if IDS.exists() else {"next": 1, "by_key": {}, "by_record": {}, "merged": {}}
    # Oldest first, so a fresh start numbers benchmarks in the order they were first seen.
    order = sorted(items, key=lambda i: (i.get("seen") or i.get("date") or "9999", i["name"].lower()))
    taken: dict[str, str] = {}
    for it in order:
        known = []
        if it["key"] in db["by_key"]:
            known.append(db["by_key"][it["key"]])
        known += [db["by_record"][r] for r in it["_records"] if r in db["by_record"]]
        known = [db["merged"].get(p, p) for p in known]
        free = sorted({p for p in known if p not in taken}, key=lambda p: int(p.split("-")[1]))
        if free:
            pid = free[0]
            for other in free[1:]:            # two old benchmarks are now one: the older id stays
                db["merged"][other] = pid
        else:
            pid = f"bp-{db['next']:06d}"
            db["next"] += 1
        taken[pid] = it["key"]
        it["pid"] = pid
        db["by_key"][it["key"]] = pid
        for r in it["_records"]:
            db["by_record"][r] = pid
    IDS.write_text(json.dumps(db, ensure_ascii=False, indent=0, sort_keys=True) + "\n")
    redirects = {**{r: p for r, p in db["by_record"].items()}, **{o: db["merged"].get(n, n) for o, n in db["merged"].items()}}
    for it in items:
        redirects[it["id"]] = it["pid"]
    return redirects


def write_benchmarks(items: list[dict], build: str) -> int:
    """One JSON per benchmark that has an adapter-readiness record: what a script needs to start an adapter."""
    out = V1 / "benchmarks"
    out.mkdir(exist_ok=True)
    keep = set()
    for it in items:
        r = it.get("readiness")
        if not r:
            continue
        sc = it.get("score") or {}
        doc = {
            "schema_version": 1, "build_id": build, "pid": it["pid"], "name": it["name"], "aliases": [f["name"] for f in it.get("family") or []],
            "site": f"https://harbor-index.github.io/bench-pool/#/b/{it['pid']}",
            "recommendation": {"tier": (it.get("tier") or {}).get("tier"), "reason": (it.get("tier") or {}).get("reason"),
                               "risks": [x.get("risk") for x in (it.get("tier") or {}).get("risks") or []]},
            "harbor": it.get("harbor"),
            "best_score": {k: sc.get(k) for k in ("pct", "source", "model", "as_of", "systems", "url")} if sc else None,
            "readiness": r,
        }
        (out / f"{it['pid']}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1))
        keep.add(f"{it['pid']}.json")
    for p in out.glob("*.json"):
        if p.name not in keep:
            p.unlink()
    return len(keep)


def _state(it: dict) -> dict:
    r = it.get("rank") or {}
    return {"name": it["name"], "tier": (it.get("tier") or {}).get("tier"), "covered": it.get("covered"),
            "best": it.get("best"), "band": r.get("band"), "harbor": (it.get("harbor") or {}).get("status"),
            "harbor_here": (it.get("harbor") or {}).get("here") or [],
            "oracle": ((it.get("readiness") or {}).get("oracle") or {}).get("level")}


def write_feed(items: list[dict], meta: dict) -> dict:
    """Compare with the previous build's state, write the change files, return the build record."""
    V1.mkdir(parents=True, exist_ok=True)
    (V1 / "changes").mkdir(exist_ok=True)
    state = {it["pid"]: _state(it) for it in items}
    digest = hashlib.sha1(json.dumps(state, sort_keys=True).encode()).hexdigest()[:8]
    now = dt.datetime.now(dt.timezone.utc)
    build = now.strftime("%Y%m%dT%H%MZ") + "-" + digest
    prev_path = V1 / "state.json"
    prev = json.loads(prev_path.read_text()) if prev_path.exists() else None
    merged = json.loads(IDS.read_text())["merged"] if IDS.exists() else {}
    events = []
    if prev:
        before = prev["items"]
        for pid, s in state.items():
            b = before.get(pid)
            if b is None:
                events.append({"kind": "discovered", "pid": pid, "name": s["name"], "after": s})
                continue
            for field, kind in (("tier", "tier_changed"), ("band", "band_changed"), ("harbor", "harbor_changed"), ("oracle", "readiness_changed"),
                                ("covered", "covered_changed"), ("name", "renamed")):
                if b.get(field) != s.get(field):
                    events.append({"kind": kind, "pid": pid, "name": s["name"], "before": b.get(field), "after": s.get(field)})
            if (b.get("best") is None) != (s.get("best") is None) or \
                    (b.get("best") is not None and s.get("best") is not None and abs(b["best"] - s["best"]) >= 2):
                events.append({"kind": "score_changed", "pid": pid, "name": s["name"], "before": b.get("best"), "after": s.get("best")})
        for pid, b in before.items():
            if pid not in state:
                into = merged.get(pid)
                events.append({"kind": "merged" if into else "removed", "pid": pid, "name": b["name"],
                               **({"into": into} if into else {})})
    record = {
        "schema_version": 1, "build_id": build, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "previous_build_id": prev["build_id"] if prev else None, "data_generated": meta.get("generated"),
        "counts": {"benchmarks": len(items), "events": len(events)},
        "files": {"benchmarks": "data/benchmarks.json", "changes": f"data/v1/changes/{build}.json",
                  "index": "data/v1/changes/index.json"},
    }
    write_benchmarks(items, build if not (prev and prev.get("digest") == digest) else prev["build_id"])
    if prev and prev.get("digest") == digest:
        # Nothing changed for a consumer: keep the previous build id, do not add an empty build.
        return json.loads((V1 / "latest.json").read_text())
    (V1 / "changes" / f"{build}.json").write_text(json.dumps({**record, "events": events}, ensure_ascii=False, indent=1))
    idx_path = V1 / "changes" / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else []
    idx = ([{"build_id": build, "generated_at": record["generated_at"], "events": len(events)}] + idx)[:KEEP_BUILDS]
    for old in [p for p in (V1 / "changes").glob("*.json") if p.name != "index.json"]:
        if old.stem not in {b["build_id"] for b in idx}:
            old.unlink()
    idx_path.write_text(json.dumps(idx, indent=1))
    prev_path.write_text(json.dumps({"build_id": build, "digest": digest, "items": state}, ensure_ascii=False, separators=(",", ":")))
    (V1 / "latest.json").write_text(json.dumps(record, indent=1))
    return record
