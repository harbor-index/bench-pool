#!/usr/bin/env python3
"""Epoch AI Benchmarking Hub: dated scores of many models on popular benchmarks.

Downloads https://epoch.ai/data/benchmark_data.zip (CC BY 4.0, credit Epoch AI)
to data/raw/epoch/ and writes data/epoch.json: per benchmark its ceiling (the
best score Epoch thinks is reachable, e.g. 0.97 on GPQA diamond because some
answers are disputed), its random baseline, its release date, what superseded
it, and every model's score with that model's release date. From those:

  top        the best score and the model that set it
  history    the running best over time (one point each time the record moved)
  velocity   how many points the record rose per month over the last 12 months
  models     how many models have a score (a sign of how widely it is used)

Scores are fractions 0-1 here. The download is refreshed once a day.

    python3 scripts/epoch.py
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "epoch" / "benchmark_data.zip"
OUT = ROOT / "data" / "epoch.json"
URL = "https://epoch.ai/data/benchmark_data.zip"
UA = "bench-pool/0.1 (benchmark discovery; https://github.com/harbor-index/bench-pool)"


def download() -> None:
    fresh = RAW.exists() and dt.datetime.fromtimestamp(RAW.stat().st_mtime).date() == dt.date.today()
    if fresh:
        return
    RAW.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": UA}), timeout=120) as r:
            body = r.read()
        zipfile.ZipFile(io.BytesIO(body))          # check it is a zip before replacing the old one
        RAW.write_bytes(body)
    except Exception as exc:  # noqa: BLE001  keep yesterday's copy when the site is down
        if not RAW.exists():
            raise
        print(f"epoch: download failed ({str(exc)[:80]}), using the copy from "
              f"{dt.datetime.fromtimestamp(RAW.stat().st_mtime).date()}", file=sys.stderr)


def page_info(name: str, cache: dict) -> dict:
    """Description, paper and repository from the benchmark's page on epoch.ai (cached; refreshed monthly)."""
    import re as _re, html as _html, time as _time
    slug = _re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    old = cache.get(name)
    if old and old.get("checked", "") >= (dt.date.today() - dt.timedelta(days=30)).isoformat():
        return old
    info = {"slug": slug, "checked": dt.date.today().isoformat(), "description": None, "links": []}
    try:
        req = urllib.request.Request(f"https://epoch.ai/benchmarks/{slug}", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=30) as r:
            page = r.read().decode("utf-8", "replace")
        m = _re.search(r'<meta name="description" content="([^"]+)"', page)
        info["description"] = _html.unescape(m.group(1)) if m else None
        info["links"] = sorted(set(_re.findall(r"https?://(?:arxiv\.org/abs/[0-9.]+|github\.com/[\w.-]+/[\w.-]+|huggingface\.co/datasets/[\w.-]+/[\w.-]+)", page)))[:6]
        info["url"] = f"https://epoch.ai/benchmarks/{slug}"
    except Exception:  # noqa: BLE001  no page under that name; the row keeps working without it
        pass
    _time.sleep(0.5)
    return info


def num(text: str | None) -> float | None:
    try:
        return float(text) if text not in (None, "") else None
    except ValueError:
        return None


def velocity(history: list[dict], today: dt.date) -> float | None:
    """Points per month the record rose over the last 12 months (fractions * 100)."""
    if not history:
        return None
    start = today - dt.timedelta(days=365)
    before = [h for h in history if h["date"] < start.isoformat()]
    base = before[-1]["score"] if before else None
    inside = [h for h in history if h["date"] >= start.isoformat()]
    if base is None:
        if len(inside) < 2:
            return None
        base, start = inside[0]["score"], dt.date.fromisoformat(inside[0]["date"])
    months = max(1.0, (today - start).days / 30.44)
    return round((history[-1]["score"] - base) * 100 / months, 2)


def main() -> int:
    download()
    z = zipfile.ZipFile(RAW)
    names = {Path(n).name: n for n in z.namelist()}
    meta = list(csv.DictReader(io.TextIOWrapper(z.open(names["benchmark_metadata.csv"]), "utf-8")))
    today = dt.date.today()
    cache = {}
    if OUT.exists():
        cache = {b["name"]: b["page"] for b in json.loads(OUT.read_text())["benchmarks"] if b.get("page")}
    out = []
    for m in meta:
        entry = {
            "name": m["benchmark"], "ceiling": num(m.get("score_ceiling")), "baseline": num(m.get("random_baseline")),
            "released": m.get("release_date") or None, "superseded_by": m.get("superseded_by") or None,
            "in_index": m.get("in_eci") == "True", "file": m.get("source_file") or None,
            "top": None, "history": [], "velocity": None, "models": 0,
            "page": page_info(m["benchmark"], cache),
        }
        f = m.get("source_file")
        if f and f in names:
            rows = list(csv.DictReader(io.TextIOWrapper(z.open(names[f]), "utf-8")))
            col = m.get("score_column")
            results = []
            for r in rows:
                s = num(r.get(col))
                if s is None:
                    continue
                results.append({"model": r.get("Name") or r.get("Model version") or "", "org": r.get("Organization") or None,
                                "date": (r.get("Release date") or r.get("Date") or "")[:10], "score": s})
            if results and max(x["score"] for x in results) > 1.5:      # stated in percent
                for x in results:
                    x["score"] /= 100
            entry["models"] = len({x["model"] for x in results})
            if results:
                top = max(results, key=lambda x: x["score"])
                entry["top"] = {"score": round(top["score"], 4), "model": top["model"], "org": top["org"], "date": top["date"]}
                best = -1.0
                for x in sorted((x for x in results if x["date"]), key=lambda x: (x["date"], -x["score"])):
                    if x["score"] > best + 1e-9:
                        best = x["score"]
                        entry["history"].append({"date": x["date"], "score": round(x["score"], 4), "model": x["model"]})
                entry["velocity"] = velocity(entry["history"], today)
        out.append(entry)
    OUT.write_text(json.dumps({"as_of": today.isoformat(), "source": URL, "licence": "CC BY 4.0, Epoch AI",
                               "benchmarks": out}, ensure_ascii=False, indent=1))
    scored = [e for e in out if e["top"]]
    print(f"epoch: {len(out)} benchmarks, {len(scored)} with scores, "
          f"{sum(1 for e in out if e['ceiling'] not in (None, 1.0))} with a ceiling below 100%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
