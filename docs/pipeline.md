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
python3 scripts/leaderboards.py   # top score per benchmark                    -> data/leaderboards.json
python3 scripts/adapter_list.py   # the team's Adapter List (.xlsx export)     -> data/adapter_list.json
python3 scripts/candidates.py     # rules, leaderboards, Adapter List, merge   -> data/candidates.json
python3 scripts/classify.py       # benchmark gate, mode, class, short facts   -> data/labels.jsonl
python3 scripts/find_leaderboards.py  # each benchmark's own leaderboard      -> data/leaderboard_search.jsonl
python3 scripts/signals.py        # stars, citations, likes, with history      -> data/signals.jsonl
python3 scripts/build.py          # join everything                            -> web/data/benchmarks.json
python3 scripts/tier.py           # recommend / hold / too new / no            -> data/tiers.jsonl
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
| Gate, mode, class, sub-class, multimodal tag, realism line, value line | Model-read from title and abstract. Not checked by a person |
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
web/       index.html, style.css, app.js, data/benchmarks.json
NOTICE.md  credits and licences (Radar CC BY-NC-SA 4.0; design reference)
```
