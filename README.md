# bench-pool

A pool of benchmarks for AI agents and models, screened as new candidates for
[Harbor Index](https://github.com/harbor-index/harbor-index-1.0).

**Site: <https://harbor-index.github.io/bench-pool/>**

It is updated automatically once a day.

## What it does

Every day it reads the new records from
[Benchmark Radar](https://benchmark-radar.org/), keeps the ones that are
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

Verdicts are made by a language model and have not been checked by a person.

## What is on the site

| Page | Shows |
|---|---|
| Board | Every benchmark, with its tier, type, best known score, stars and citations |
| New | What arrived this week and in the weeks before |
| Filter | How many records each step kept, and what was turned away and why |
| A benchmark's page | The verdict, the evidence for it, and links |

## Daily reports

Each day's run also writes a short report to [reports/](reports/): what is new
that day, which tier each new benchmark got and why, and anything that changed
tier.

## More

- [docs/tiering-standard.md](docs/tiering-standard.md): the rules behind Recommend / Hold / No
- [docs/pipeline.md](docs/pipeline.md): how it is built and run
- [NOTICE.md](NOTICE.md): credits and licences. Data comes from Benchmark Radar (CC BY-NC-SA 4.0)
