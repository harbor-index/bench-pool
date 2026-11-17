#!/usr/bin/env python3
"""What Harbor already has: its dataset registry and the datasets on Harbor Hub.

  registry  https://github.com/harbor-framework/harbor/blob/main/registry.json
            (dataset name, version, task count)
  hub       https://hub.harborframework.com/datasets, every page of the public
            listing (owner/name slugs, e.g. terminal-bench/terminal-bench-2-1)

Writes data/harbor_status.json. scripts/build.py matches benchmarks to these
by name (and by family, for versions and subsets), so the site can say whether
a benchmark is already registered or published in Harbor format before anyone
starts an adapter for it.

    python3 scripts/harbor_status.py
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "harbor_status.json"
REGISTRY = "https://raw.githubusercontent.com/harbor-framework/harbor/main/registry.json"
HUB = "https://hub.harborframework.com/datasets"
UA = "bench-pool/0.1 (benchmark discovery; https://github.com/harbor-index/bench-pool)"


def get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def main() -> int:
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    out = {"as_of": dt.date.today().isoformat(), "registry": old.get("registry", []), "hub": old.get("hub", [])}
    try:
        reg = json.loads(get(REGISTRY))
        seen = {}
        for d in reg:
            name = d.get("name")
            if name:
                seen[(name, d.get("version"))] = {"name": name, "version": d.get("version"),
                                                  "tasks": len(d.get("tasks") or []), "description": (d.get("description") or "")[:200]}
        out["registry"] = list(seen.values())
    except Exception as exc:  # noqa: BLE001  keep yesterday's list
        print(f"harbor_status: registry failed ({str(exc)[:80]}), kept the previous list", file=sys.stderr)
    try:
        slugs, page, last = set(), 1, 1
        while page <= last and page <= 60:
            listing = get(f"{HUB}?page={page}")
            found = set(re.findall(r'/datasets/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)', listing))
            slugs |= found
            last = max([last] + [int(p) for p in re.findall(r"[?&]page=(\d+)", listing)])
            page += 1
            time.sleep(1)
        if slugs:
            out["hub"] = sorted(slugs)
        # Each dataset's own page: task count, version, description, links (cached for 30 days).
        info = old.get("hub_info", {})
        cutoff = (dt.date.today() - dt.timedelta(days=30)).isoformat()
        for slug in out["hub"]:
            if slug in info and info[slug].get("checked", "") >= cutoff:
                continue
            try:
                page = get(f"{HUB}/{slug}")
                m = re.search(r'<meta name="description" content="([^"]*)"', page)
                desc = html.unescape(m.group(1)) if m else ""
                tasks = re.search(r"Tasks:\s*([\d,]+)", desc)
                version = re.search(r"Version:\s*([\w.\-]+)", desc)
                info[slug] = {"checked": dt.date.today().isoformat(),
                              "tasks": int(tasks.group(1).replace(",", "")) if tasks else None,
                              "version": version.group(1) if version else None,
                              "description": re.sub(r"^(?:Tasks:[^·]*·\s*)?(?:Version:[^·]*·\s*)?", "", desc).strip(),
                              "links": sorted(set(re.findall(r"https?://(?:arxiv\.org/abs/[0-9.]+|github\.com/[\w.-]+/[\w.-]+)", page)))[:5]}
            except Exception:  # noqa: BLE001
                continue
            time.sleep(0.6)
        out["hub_info"] = {k: v for k, v in info.items() if k in set(out["hub"])}
    except Exception as exc:  # noqa: BLE001
        print(f"harbor_status: hub failed ({str(exc)[:80]}), kept the previous list", file=sys.stderr)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"harbor_status: {len(out['registry'])} registry datasets, {len(out['hub'])} Hub datasets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
