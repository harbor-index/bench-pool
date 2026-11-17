# How the pipeline works

The details behind [README](../README.md): every step, where each field comes
from, and the known limits. The rules for Recommend / Hold / No are in
[tiering-standard.md](tiering-standard.md).

## See it

```sh
python3 -m http.server 8137 --bind 127.0.0.1 --directory web
```

Then open <http://localhost:8137>. No install, no build step: `web/` is plain
HTML, CSS and JavaScript that reads `web/data/benchmarks.json`.

## Daily run

```sh
python3 scripts/daily.py            # every day
python3 scripts/daily.py --weekly   # once a week: also search for own leaderboards
python3 scripts/daily.py --dry-run  # show the steps
```

It runs the steps below in order, each doing only what is new, and stops at
the first failure so the site keeps its last good data. Output is appended to
`data/daily.log`.

Every step that needs a language model goes through `scripts/llm.py`, which
reads three lines from `.env`: `OPENAI_BASE_URL`, `OPENAI_API_KEY` and
`OPENAI_MODEL` (any OpenAI-compatible endpoint). `python3 scripts/llm.py`
checks the endpoint and lists its models. Without those lines the local
`claude` command is used. Rate limits and overloads are waited out and retried.

`.github/workflows/daily.yml` runs the same command once a day on GitHub,
commits what the run learned (`data/labels.jsonl`, `data/tiers.jsonl`,
`data/signals.jsonl`, `data/leaderboard_search.jsonl`,
`data/discovered_links.json`, `web/data/`) and publishes `web/` to GitHub
Pages. It needs the names in `.env.example` as repository secrets:
`sh scripts/setup_github.sh` copies them from `.env` (it refuses an endpoint on
this machine, which GitHub could not reach) and switches Pages on.

A trial from nothing: copy `scripts/`, `docs/`, `web/` (without `web/data`),
the four small files `data/aliases.json`, `extra_links.json`,
`harbor_index_v1.json`, `established_benchmarks.json`, and `.env` to an empty
folder and run `python3 scripts/daily.py --days 1 --tier-limit 10` there.

## Refresh the data

Python 3.10+, standard library only. Run from the repository root:

```sh
python3 scripts/fetch.py          # new Radar snapshots + leaderboard crawls  -> data/raw/
python3 scripts/sources.py        # our own searches: arXiv, HF, GitHub, blogs -> data/raw/sources/, data/sources/
python3 scripts/harbor_status.py  # Harbor registry + Harbor Hub datasets      -> data/harbor_status.json
python3 scripts/epoch.py          # Epoch AI dated scores and ceilings          -> data/epoch.json
python3 scripts/leaderboards.py   # top score per benchmark                    -> data/leaderboards.json
python3 scripts/adapter_list.py   # the team's Adapter List (.xlsx export)     -> data/adapter_list.json
python3 scripts/candidates.py     # rules, leaderboards, Adapter List, merge   -> data/candidates.json
python3 scripts/classify.py       # benchmark gate, mode, class, short facts   -> data/labels.jsonl
python3 scripts/find_leaderboards.py  # each benchmark's own leaderboard      -> data/leaderboard_search.jsonl
python3 scripts/signals.py        # stars, citations, likes, with history      -> data/signals.jsonl
python3 scripts/build.py          # join everything                            -> web/data/benchmarks.json
python3 scripts/tier.py           # recommend / hold / too new / no            -> data/tiers.jsonl
python3 scripts/readiness.py      # adapter readiness, from the release itself -> data/readiness.jsonl
python3 scripts/tier.py --rescore # re-apply score bars (no model call)        -> data/tiers.jsonl
python3 scripts/headroom.py       # ranking: is the gap to 100% real?          -> data/headroom.jsonl
python3 scripts/build.py          # again, to put the tiers on the site
python3 scripts/report.py         # the day's report                           -> reports/<date>.md
python3 -m unittest discover -s tests
```

`adapter_list.py` needs `data/raw/adapter_list/adapter_list.xlsx`, an export of
the Google Sheet "Adapter List" (File > Download > .xlsx). The export and
`data/adapter_list.json` are git-ignored: the sheet is the team's own. It also
writes `data/established_benchmarks.json` (names, links, descriptions and
adapter status only), which is committed and is what a run without the sheet
uses, so this step is only needed when the sheet changes.

`sources.py` writes records in Radar's shape, so the rest of the pipeline
treats them like Radar records. arXiv and Hugging Face Daily Papers can be
fetched again for any date and live under `data/raw/sources/` (cached, every
missing day since 2026-10-18 is fetched again); GitHub, blog and Hugging Face
dataset searches only answer for a current window, so only their new items are
written, under `data/sources/`, which is committed. OpenReview is not searched:
its API answers anonymous clients with a verification challenge. Over its first
30 days `sources.py` found 113 benchmarks that Radar did not have (arXiv 90,
GitHub 11, HF Daily Papers 11, HF Datasets 1, blogs 0), next to Radar's 517.

## Ranking

The Ranking page orders benchmarks by real headroom: popular ones (tracked by
Epoch AI, Artificial Analysis or Benchmark Saturation, reported by at least 10
models on LLM Stats, or used in Harbor Index v1) and every recommended new
candidate.

- **Best score** is one record shared by the Board, the tiers and the Ranking
  (`build.best_comparable`): the highest percentage on the benchmark's own
  leaderboard or any aggregator. A table listing a single system is one report,
  not a leaderboard, and a paper's own figure counts only while the benchmark
  is under a year old. When it changes, `tier.py --rescore` re-applies the
  difficulty and saturation bars without a model call.
- **Ceiling** is 100% unless Epoch AI estimates less, or the evidence states a
  share of tasks that cannot earn credit (wrong answers, unsolvable tasks). A
  human baseline is shown for reference and is never a ceiling; neither are
  "uncertain" items, weak tests or grader disagreement. An estimate that some
  system has already beaten is dropped, with a note.
- **Real or not**: `headroom.py` asks a model, from the benchmark's facts, its
  scores, Epoch's record history and up to eight arXiv papers named after it or
  auditing it, whether the gap is models failing valid tasks (real), largely
  the benchmark's fault (suspect), or not shown either way (not verified).
  "Nothing reported against it" is not evidence. Quotes not found in that text
  are dropped, and "real" needs evidence about the tasks themselves.
- Groups: real, not verified, suspect, saturated (within 10 points of the
  ceiling) and no score. Pace is how many points the record rose per month over
  the last year, from Epoch's dated results.

## Harbor status, families and adapter readiness

`harbor_status.py` reads Harbor's `registry.json` and every dataset page on
Harbor Hub. `build.py` marks each benchmark: in Harbor Index v1, has a merged
adapter, on Harbor (registry or Hub, same name), or "family in Harbor" when
another version or subset is (family = the name without versions, years and
subset words such as Verified, Lite, Diamond). Hub datasets also enter the pool
as candidates, so Harbor-native benchmarks no paper feed carries are screened
too.

`readiness.py` reads the release of every recommended benchmark not yet in
Harbor (GitHub repository and file tree, Hugging Face dataset card, Zenodo
record and the software it links to) and records: pinned release, code and data
licences, task count, manifest and a pilot task, the verifier's entry point and
what earns full credit, solvability evidence on a ladder (none, gold answers
only, reference solution shipped, reference reported to pass, reference passes
and no-op fails), runtime needs (services, GPU, live APIs, credentials, per-task
exceptions) and the questions to settle first. Every line quotes the release; a
file path is marked "inspected" when it exists in the repository tree. A
release that shows gold answers only lowers Solid at the next rescore.

## Data for scripts

Next to the site (`web/data/`, published with it):

| File | What |
|---|---|
| `benchmarks.json` | Everything the site shows. `meta.build_id` names the build; `meta.redirects` maps old ids to permanent ones. |
| `v1/latest.json` | The current build id, time, previous build, counts and file paths. |
| `v1/changes/<build>.json` | Events since the previous build: discovered, removed, merged, renamed, tier / band / score / Harbor / readiness changed. |
| `v1/changes/index.json` | The last 90 builds. |
| `v1/benchmarks/<pid>.json` | Adapter readiness record, recommendation, Harbor status and best score, for each recommended benchmark not yet in Harbor. |

Permanent ids look like `bp-000123` (`data/ids.json`, committed): a benchmark
keeps its id when its name or lead record changes, and when two benchmarks
merge the older id stays and the other redirects. The daily report and the site
print the same build id.

`signals.py` reads `GITHUB_TOKEN`, `HF_TOKEN` and `S2_API_KEY` from the
environment or from a `.env` file in the repository root (git-ignored). Without
`GITHUB_TOKEN` it skips GitHub; the other two keys are optional.

Every step keeps what it already has. `fetch.py` skips files on disk,
`classify.py` only labels candidates missing from `data/labels.jsonl`, and
`find_leaderboards.py` only searches benchmarks it has not searched yet, plus
those last searched more than 7 days ago (`--recheck-days`). So a daily run pays
for one new day and about a seventh of the old searches.

`tier.py` judges each benchmark against
[docs/tiering-standard.md](tiering-standard.md), one benchmark per call,
through an OpenAI-compatible endpoint at medium reasoning effort
(`OPENAI_BASE_URL`, `OPENAI_API_KEY` and `OPENAI_MODEL` in `.env`). The verdicts
on the site were made by `gpt-6.1-terra`; new ones use `deepseek-v4.1-flash`,
which agreed with it on the tier of 24 of 28 benchmarks judged by both, with
418 of 420 quotes exact. Each verdict records the model that made it. It fetches the
whole paper (arXiv HTML, else the PDF through `pdftotext` if installed), the
repository README and the file list itself; the model does not browse. A
benchmark with neither a paper nor a repository is held without a model call.
Every answer is checked: a quote that is not in the text given is dropped, and
the model's "recommend" stands only if the checked verdicts carry it (Real and
Solid strong, plus Difficult or Attention). When a new version of the standard
changes only that rule, `tier.py --rerule` re-derives every tier from the
stored verdicts without reading anything again. Each verdict
stores how much was read, and the site shows it. Benchmarks that Harbor Index
v1 already uses, or that have a merged Harbor adapter, are marked covered and
shown as reference; the board lists new candidates by default. A benchmark
under 15 days old with no leaderboard carries a `new` flag. A new version line
in the standard makes every benchmark due again; old judgements stay in
`data/tiers.jsonl` as history. arXiv is read one paper every three seconds, so
a full run takes about an hour.

`classify.py` calls the local `claude` CLI (`claude -p --model
claude-sonnet-5-5 --effort medium` when no endpoint is set in `.env`; otherwise
the same endpoint as the tiering), about 20 records per call. The first runs
used Haiku; `--redo benchmarks` asks again for every benchmark not labelled by
the current model. Labels from prompt version 1 are reused where they still hold
(`upgrade()` in the script); only the benchmarks it had called "not agentic"
were asked again.

`find_leaderboards.py` reads web pages (arXiv, Hugging Face, GitHub, project
sites; fetched pages are cached in `data/raw/pages/`) and calls
`claude -p --model sonnet` once for each benchmark whose pages mention a
leaderboard. The first full run searched about 1,070 benchmarks and made about
300 model calls. Useful flags: `--limit 20`, `--only NAME`, `--report`,
`--redo unchecked`.

A benchmark with no paper and no repository is still read if it links a page
of its own: a Hugging Face dataset card, a DOI landing page or a project page
(`other_page()` in `tier.py`).

`find_sources.py` handles the ones with no such page either (mostly entries
that came from leaderboards). It searches arXiv for the name, a model picks the
paper that introduces the benchmark or says none does, and the match is kept
only if the name is in that paper's title or abstract. A found paper is then
read and judged like any other. When nothing is found the benchmark stays on
Hold, and its page says what was searched and when. The daily run works through
the backlog a batch at a time, and does the same for the search for each
benchmark's own leaderboard.

## How a record gets in

1. **Candidates** (`candidates.py`), from three places:
   - Radar snapshots: Radar tagged the record benchmark or evaluation, and
     either Radar tagged it agentic or its title names something an agent does.
     A benchmark-tagged record with no agent word gets in only on traction
     (`TRACTION` in the script: 10 upvotes, 100 stars, 10 citations, 20 likes
     or 5,000 downloads).
     Records with the same arXiv id, title or artifact link are merged.
   - Every benchmark in Radar's leaderboard crawls.
   - Every row of the team's Adapter List. Radar's snapshots start in July
     2026, so this is how older benchmarks get in.
2. **Gate** (`classify.py`). A model reads the title and abstract and answers
   one question: is this a benchmark that others can run? That is the only
   inclusion rule. Adapter List rows always pass.
3. **Mode** (same call). Each benchmark is `agentic`, `modified` or `non`,
   following Harbor Index v1 (arXiv 2609.04298), Appendix D.2. The mode is a
   column and a signal for recommending a benchmark; it does not remove
   anything. The prompt is the `PROMPT` string in the script; change it and
   bump `PROMPT_VERSION` to relabel.
4. **Class** (same call). The nine classes of the Harbor Index v1 paper, plus
   a tenth, Games & Embodied, which the paper does not have and which is about
   12% of new agentic benchmarks. Multimodal is both class 9 (when perception
   is what is tested) and a tag on any benchmark with non-text input.
5. **Join** (`pool.py`, used by `build.py`). Records with the same benchmark
   name become one row. Names are compared as letters and digits only, after
   three spelling rules: a trailing "benchmark" is dropped, "v2.1" is "2.1", and
   "2.0" is "2". Versions and variants stay separate (OSWorld and OSWorld 2.0
   are two benchmarks). Spellings the rules cannot catch go in
   `data/aliases.json`. `python3 scripts/pool.py` prints what was merged.

Not covered: a non-agentic benchmark that appears only as a new paper in Radar
and has no traction yet. About 12,500 such records exist; a sample showed most
are models, methods and datasets, so they wait until they pass the traction
bar, a leaderboard lists them, or the Adapter List adds them.

## What each field is

| Field | Where it comes from |
|---|---|
| Title, date, authors, links, attention counts, fine tags | Radar, unchanged |
| Aggregator leaderboard score (`agg`) | Radar's crawls of LLM Stats (2026-08-17), Artificial Analysis (2026-08-25), Benchmark Saturation (2026-11-04). Matched by benchmark name. No protocol is stated; many rows are vendor self-reported |
| Own leaderboard score (`own`): top score, system, metric, address, date found | `find_leaderboards.py`. Model-read from the benchmark's own pages; kept only if the quoted row is on the page and contains the number and the system's name |
| Gate, mode, class, sub-class, multimodal tag, realism line, value line | Model-read from title and abstract |
| Stars, forks, citations, likes, downloads (`metrics`, `sig`) | `signals.py`: GitHub, Semantic Scholar and Hugging Face, fetched with a date and kept as history. Where nothing was fetched, Radar's count is shown and marked as not refreshed |
| Adapter List row (`adapter`) and `diff` | The sheet's own Mode, Saturated, Include, Priority and Status, shown next to this pool's answers. Where mode or saturation bucket disagree, the benchmark is marked "≠ list". The sheet is never used as the answer |
| `hi1` | Number of Harbor Index v1 tasks drawn from this benchmark (`data/harbor_index_v1.json`, read from task directory names) |
| Coverage tags (data, scores, trajectories, infra) | Model-read from the abstract, plus two rules: a linked dataset page means data is public; a linked code repository shows as "repo linked" |
| Paper-reported best score (`paper`) | Model-read, kept only if the quoted words are in the abstract and contain the number. Drawn hatched |
| Best known score | The own leaderboard's, else the aggregator's, else the paper's. Percentages only |
| Saturated | Best known score above 90% |
| Leaderboard column (`lb`) | `own`, `aggregator`, `both`, `listed` (an own leaderboard exists but its top score could not be read), `none` (searched, nothing found), `unchecked` |

Known limits:

- The three kinds of score are never mixed: each benchmark carries `agg`,
  `own` and `paper` separately, and the site draws them differently.
- "None" (no public leaderboard) means the search ran and found nothing. The
  search follows links: Radar's links, the arXiv record, the Hugging Face paper
  page, the repository README, the project page, and, if none of those exist,
  links in the paper's full text. It does not use a web search engine, so a
  leaderboard that none of these pages link to is missed.
- "Not checked" means there was nothing to start from, or the pages could not
  be opened. Benchmarks that come only from the aggregator crawls have no
  paper or repository link; add start links for them in
  `data/extra_links.json`.
- Leaderboards drawn by script (SWE-bench, OSWorld and others) show as
  "leaderboard exists, top score not read": the rows are not in the page text.
- Papers with Code is closed (its addresses redirect to Hugging Face), so it is
  not searched.
- "Not stated" means the abstract does not say. The repository was not opened.
- Elo-style scores are shown raw and never count as saturated.
- Radar's snapshots start on 2026-07-23, so the timeline starts there.

## Files

```
scripts/   fetch, leaderboards, adapter_list, candidates, classify, find_leaderboards,
           signals, build; pool (shared)
data/      labels.jsonl, leaderboard_search.jsonl, signals.jsonl, aliases.json,
           extra_links.json, harbor_index_v1.json (kept);
           raw/, adapter_list.json and rebuilt files are git-ignored
tests/     rules for names, scores, gate output and Adapter List differences
web/       index.html, style.css, js/ (core, panels, item, flow, views), vendor/gridstack (MIT), data/benchmarks.json
NOTICE.md  credits and licences (Radar CC BY-NC-SA 4.0; design reference)
```
