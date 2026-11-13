#!/usr/bin/env python3
"""Turn the team's Adapter List spreadsheet into a seed list of mature benchmarks.

Reads  data/raw/adapter_list/adapter_list.xlsx   (an .xlsx export of the Google
       Sheet "Adapter List"; download it by hand or through the Drive connector)
Writes data/adapter_list.json               every kept field; git-ignored
       data/established_benchmarks.json     a plain list: name, link, and whether
                                            Harbor has a merged adapter. Committed;
                                            a run without the sheet uses it

Only the sheet "Adapter list v2.0" is read. Kept per row: name, link, domain,
description, priority notes, and the team's own labels (Agentic, Saturated,
Include for paper, Priority, Harbor Status, Harbor PR). Reviewer and
contributor names are not copied.

The labels are shown on the site next to what this pipeline finds, so that
out-of-date rows are visible. They are never used as this pipeline's answer.

Standard library only: an .xlsx file is a zip of XML files.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "adapter_list" / "adapter_list.xlsx"
OUT = ROOT / "data" / "adapter_list.json"
# The part that lives in the repository: a plain list of established benchmarks, with a
# link each, and whether Harbor already has a merged adapter. Nothing else from the sheet.
PUBLIC = ROOT / "data" / "established_benchmarks.json"
SHEET = "Adapter list v2.0"
M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MODE = {"agentic": "agentic", "modified-agentic": "modified", "non-agentic": "non"}
KEEP = {
    "Name": "name", "Benchmark Link": "link_text", "Benchmark Domain": "domain",
    "Priority Notes (and citations / github stars)": "notes", "Benchmark Description": "description",
    "Priority": "priority", "Saturated": "saturated", "Agentic": "agentic",
    "Include for paper": "include", "Harbor Status": "status", "Harbor PR": "pr",
}


def column(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_sheet(path: Path, sheet: str) -> list[dict]:
    """Rows of one sheet as {header: text}; a cell's hyperlink is under "<header> URL"."""
    with zipfile.ZipFile(path) as z:
        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{{{M}}}si"):
                strings.append("".join(t.text or "" for t in si.iter(f"{{{M}}}t")))
        targets = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
        part = None
        for s in ET.fromstring(z.read("xl/workbook.xml")).find(f"{{{M}}}sheets"):
            if s.get("name") == sheet:
                part = "xl/" + targets[s.get(f"{{{R}}}id")].removeprefix("/xl/").removeprefix("xl/")
        if part is None:
            raise SystemExit(f"sheet {sheet!r} not in {path.name}")
        root = ET.fromstring(z.read(part))
        links: dict[str, str] = {}
        rels = part.replace("worksheets/", "worksheets/_rels/") + ".rels"
        if rels in z.namelist():
            by_id = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read(rels))}
            for h in root.iter(f"{{{M}}}hyperlink"):
                if by_id.get(h.get(f"{{{R}}}id")):
                    links[h.get("ref")] = by_id[h.get(f"{{{R}}}id")]

    grid: list[dict[int, str]] = []
    urls: list[dict[int, str]] = []
    for row in root.iter(f"{{{M}}}row"):
        cells, cell_urls = {}, {}
        for c in row.findall(f"{{{M}}}c"):
            v = c.find(f"{{{M}}}v")
            if c.get("t") == "s" and v is not None:
                text = strings[int(v.text)]
            elif c.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in c.iter(f"{{{M}}}t"))
            else:
                text = v.text if v is not None else ""
            if text and text.strip():
                cells[column(c.get("r"))] = text.strip()
            if c.get("r") in links:
                cell_urls[column(c.get("r"))] = links[c.get("r")]
        grid.append(cells)
        urls.append(cell_urls)
    header = grid[0]
    out = []
    for cells, cell_urls in zip(grid[1:], urls[1:]):
        row = {header[i].strip(): text for i, text in cells.items() if i in header}
        row.update({header[i].strip() + " URL": u for i, u in cell_urls.items() if i in header})
        out.append(row)
    return out


def tidy(row: dict) -> dict | None:
    name = row.get("Name", "").strip()
    # "TRAIL" is a real benchmark whose row was filled with its own name in every column.
    if not name:
        return None
    out = {short: row.get(long, "").strip() for long, short in KEEP.items()}
    link = row.get("Benchmark Link URL") or (out["link_text"] if out["link_text"].startswith("http") else "")
    out["link"] = link.strip()
    del out["link_text"]
    out["pr"] = (row.get("Harbor PR URL") or out["pr"]).strip()
    if not out["pr"].startswith("http"):
        out["pr"] = ""
    out["mode"] = MODE.get(out.pop("agentic").lower())
    for field in ("domain", "notes", "description", "priority", "saturated", "include", "status"):
        if out[field] == name:      # the filled-with-its-own-name row
            out[field] = ""
    return out


def main() -> None:
    if not SRC.exists():
        raise SystemExit(f"missing {SRC.relative_to(ROOT)}: export the Adapter List sheet as .xlsx first")
    rows, seen, twice = [], set(), []
    for row in (tidy(r) for r in read_sheet(SRC, SHEET)):
        if not row:
            continue
        key = re.sub(r"[^a-z0-9]+", "", row["name"].lower())
        if key in seen:             # the sheet lists a few benchmarks twice; the first row wins
            twice.append(row["name"])
            continue
        seen.add(key)
        rows.append(row)
    if twice:
        print("listed twice, first row kept:", ", ".join(twice))
    OUT.write_text(json.dumps({"sheet": SHEET, "rows": rows}, ensure_ascii=False, indent=1))
    PUBLIC.write_text(json.dumps({
        "_about": "Established benchmarks added to the pool by hand, so that work older than the first Radar "
                  "snapshot is present. harbor_adapter is true when Harbor already has a merged adapter for it.",
        "benchmarks": [{"name": r["name"], "link": r["link"], "harbor_adapter": r["status"] == "Merged"} for r in rows]},
        ensure_ascii=False, indent=1))
    print(f"{len(rows)} benchmarks; mode labelled {sum(r['mode'] is not None for r in rows)}; "
          f"with link {sum(bool(r['link']) for r in rows)}; merged {sum(r['status'] == 'Merged' for r in rows)}")


if __name__ == "__main__":
    main()
