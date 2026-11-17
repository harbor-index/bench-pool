# bench-pool

A pool of benchmarks for AI agents and models, screened as new candidates for
[Harbor Index](https://github.com/harbor-index/harbor-index-1.0).

**Site: <https://harbor-index.github.io/bench-pool/>**

It is updated automatically once a day.

## What it does

Every day it reads the new records from
[Benchmark Radar](https://benchmark-radar.org/) and from its own searches of
arXiv, Hugging Face, GitHub, lab blogs and Harbor Hub, keeps the ones that are
benchmarks, reads each benchmark's paper and repository, and sorts it into one
of three tiers:

| Tier | Meaning |
|---|---|
| Recommend | Worth proposing for Harbor Index now |
| Hold | Plausible; a person has to settle one point, which is named |
| No | A blocking reason applies, for example it is saturated or its tasks are not public |

Each verdict comes with the sentences it rests on, quoted from the paper, and a
short list of things to settle before bringing the benchmark into Harbor.
Benchmarks that Harbor Index v1 already uses, or that already have a Harbor
adapter, are marked as covered and kept for reference.

## What is on the site

| Page | Shows |
|---|---|
| Overview | This week's new benchmarks, tier changes, what is ready to adapt, and the field at a glance |
| Board | Every benchmark with filters, a list, and its verdict, evidence and adapter readiness side by side |
| Ranking | Popular and recommended benchmarks ordered by real headroom: how far the best score is from what is reachable, and whether that gap is the models' or the benchmark's |
| New | What was first seen (or published) this week and in the weeks before |
| Screening | How many records each step kept, what was turned away and why |
| About | Where each field comes from |

Panels can be dragged, resized and hidden. Benchmarks can be starred, noted,
compared side by side and exported as CSV or JSON; a filtered view has a link
of its own.

For scripts: `data/benchmarks.json` has everything; `data/v1/latest.json`,
`data/v1/changes/` and `data/v1/benchmarks/<id>.json` give the build id, what
changed since the last build, and an adapter brief per recommended benchmark.
Ids such as `bp-000123` are permanent. See [docs/pipeline.md](docs/pipeline.md).

## Daily reports

Each day's run also writes a short report to [reports/](reports/): what is new
that day, which tier each new benchmark got and why, and anything that changed
tier.

## More

- [docs/tiering-standard.md](docs/tiering-standard.md): the rules behind Recommend / Hold / No
- [docs/pipeline.md](docs/pipeline.md): how it is built and run
- [NOTICE.md](NOTICE.md): credits and licences. Data comes from Benchmark Radar (CC BY-NC-SA 4.0)
