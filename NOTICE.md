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

## Data: Epoch AI

The ranking uses the Epoch AI Benchmarking Hub (<https://epoch.ai/benchmarks>):
dated scores, score ceilings and successors, downloaded from
`https://epoch.ai/data/benchmark_data.zip`. Epoch AI's data is licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); credit Epoch AI.

## Design

The site's design draws on Apple's Human Interface Guidelines, stripe.com and the AutoReview
explorer (harbor-index/autoreview). Only ideas and colour values were taken from them; no code,
styles, icons or images were copied.
All files under `web/` except `web/vendor/` were written for bench-pool.

## Code: GridStack

`web/vendor/gridstack-all.js` and `gridstack.min.css` are GridStack 10.3.1
(<https://gridstackjs.com>), MIT licence, Copyright (c) 2019-2023 Alain Dumesny; the licence is in
`web/vendor/GRIDSTACK-LICENSE`. It makes the panels draggable and resizable.

## Font

Inter, loaded from Google Fonts (SIL Open Font License 1.1). The page falls back to the system font
when offline.
