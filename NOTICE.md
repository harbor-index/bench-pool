# Credits and licences

## Data: Benchmark Radar

All records come from [Benchmark Radar](https://benchmark-radar.org/) by
Koutian Wu, <https://github.com/ktwu01/benchmark-radar>: the daily snapshots in
`data/snapshots/`, the leaderboard crawls in `data/leaderboard_snapshots/` and
`data/catalog/benchmark_dates.yml`.

Radar's content is licensed
[CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/); its data
files and pipeline code are MIT. bench-pool filters, classifies and summarises
that content. The derived data in `web/data/benchmarks.json` and
`data/labels.jsonl` is shared under the same CC BY-NC-SA 4.0 terms:
attribution, non-commercial, share-alike. Commercial use needs Koutian Wu's
written permission. The site footer carries the credit.

Radar's leaderboard crawls restate third-party tables: LLM Stats, Artificial
Analysis, and [Benchmark Saturation](https://github.com/evaleval/benchmark-saturation)
(MIT, Copyright (c) 2026 Benchmark Saturation contributors). Paper titles and
abstract quotes remain under their authors' terms.

## Design: Terminal-Bench-Science

The look follows <https://www.terminal-bench-science.ai/> (monospace type, large
uppercase title, icon filter row, view toggle, inline score bars, teal accent).

The repository `harbor-framework/terminal-bench-science` is Apache-2.0 (checked
2026-11-11 through the GitHub API). Apache-2.0 would allow reuse with
attribution, but it does not grant use of the project's name or logo. Nothing
was copied: no code, styles, icons or images. All files under `web/` were
written for bench-pool, which has its own name and mark.

## Font

Google Sans Code, loaded from Google Fonts (SIL Open Font License 1.1). The
page falls back to the system monospace font when offline.
