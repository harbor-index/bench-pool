# Tiering standard

Version 0.6 (2026-11-13). Scope and rules confirmed by the project owner; not yet reviewed by Lin.

The pool exists to find new candidates for the next Harbor Index. Benchmarks
that Harbor Index v1 already drew tasks from, or that already have a merged
Harbor adapter, are marked **covered**: they stay in the pool as reference and
as a check on this standard, but they are not candidates and are left out of
the tier counts.

This file is the whole instruction for the agent that decides, for one
benchmark at a time, whether it is worth proposing for Harbor Index. It is a
first filter: cheap, explainable, and wrong in the direction of keeping a
benchmark for a person to look at. The deep audit of individual tasks
(repeated model runs, broken-task detection, human review) is a later stage
and is not done here.

Change this file, bump the version, and every benchmark is judged again.

## 1. What the agent is given

For each benchmark:

- its row in the pool: name, mode, class, dates, links, scores with their
  source, stars, citations, Hugging Face counts, and the date each was fetched;
- the full text of its paper (arXiv's HTML version, or the PDF turned into
  text), not only the abstract, without the reference list;
- its repository README in full and its top-level file list, when it has a
  repository.

The agent does not browse. `scripts/tier.py` fetches these and hands them over
as text, and records for every verdict how much was read. A verdict needs the
whole paper or the README:

- If neither a paper nor a repository could be read, no model is asked and the
  benchmark is `hold` under rule T0. A one-line description is not enough to
  judge on.
- If the paper had to be cut for length, the verdict says so.

The agent may not use what it remembers about a benchmark as evidence: every
claim needs a quote from the text it was given in this run. The Adapter List
row and Harbor Index v1 membership are not shown to it; they are the check.

## 2. Tiers

| Tier | Meaning |
|---|---|
| `recommend` | Propose for Harbor Index now. No blocking rule fires; Real and Solid are both strong; and Difficult or Attention is strong too. |
| `hold` | Plausible, but something a person must settle: mixed evidence, or one dimension is weak. |
| `no` | A blocking rule fires. The rule is named. |

`new` is a flag, not a tier: published less than 15 days ago, no leaderboard
of its own or on an aggregator, and attention under the bar (100 stars, 20
Hugging Face upvotes or 5 citations). A new benchmark is judged like any other
on what its pages show (real, diverse, valuable, solid, coverage, Harbor fit).
Difficult and Attention will usually be `no_evidence` for it, and that never
holds it back.

There is no total score. Benchmarks publish very different amounts of
information, and a weighted sum would mostly measure how much they publish.

## 3. Dimensions

Five come from the team's 4-5-6 framework (real, diverse, difficult, valuable,
solid). Two more are specific to this filter (coverage, attention).

Each dimension gets one of `strong`, `ok`, `weak`, `no_evidence`, plus the
evidence: a quote of at most 40 words and the address it came from.
`no_evidence` is not `weak`. It means the pages do not say.

### 3.0 Checks, answered before any verdict

This is not a review of the paper. The question is whether the benchmark is a
sound source of tasks for Harbor Index, so the judge first looks up a fixed set
of facts about the benchmark itself. Each answer is one of the listed values
with a quote from the text; an answer whose quote is not in the text is reset
to `not_stated` by the script.

| Check | Values | What it is |
|---|---|---|
| `data_released` | yes, partial, no, not_stated | The tasks themselves are public. |
| `provenance` | real_artifacts, expert_written, generated, mixed, not_stated | Where tasks come from. Generated = LLM-synthesised, templated or procedural. |
| `human_review` | yes, no, not_stated | People checked the tasks. |
| `domain_expertise` | yes, no, not_stated | Solving a task needs professional or specialist knowledge (finance, law, medicine, a science, security, systems engineering), not only general skill. |
| `verifier` | executable, exact_match, llm_judge, human, mixed, not_stated | How an answer is scored. |
| `judge_validated` | yes, no, not_applicable, not_stated | For a model judge: agreement with people is reported with a number. |
| `solvable` | yes, no, not_stated | There is evidence that the tasks and their environments are not broken, so that a failure is the agent's. See below. |
| `environment` | container, live_web, simulator, hardware, not_stated | Where a task runs. |
| `gaming` | yes, no, not_stated | Reward hacking, shortcuts or contamination are discussed or defended against. |
| `variance` | yes, no, not_stated | Repeated runs, error bars or confidence intervals. |
| `best_score` | percent of the maximum, the system, run by authors / others / both | Best result on the main metric. |
| `top_gap` | points | Between the best and third-best frontier system. |
| `size` | tasks, categories, sources | Tasks; categories in the benchmark's own taxonomy; distinct repositories, sites or datasets the tasks are drawn from. |

`solvable` is the purpose that Harbor's oracle solution serves, and any
evidence with that purpose counts: a reference solution shown to pass; tasks
built from artifacts that carry their own solution (a merged fix, a published
result); people solving the tasks or a human baseline; each task validated by
its authors as solvable; or an analysis of failed runs showing the failures
are real and not caused by the environment or the verifier. A paper that says
none of this is `not_stated`.

The judge also lists up to three **adoption risks**: things someone bringing
this benchmark into Harbor would have to settle first (tasks not released, a
judge nobody validated, live websites that cannot be frozen, top models
already near the ceiling). They come from the checks above, not from an
opinion of the paper, and are shown next to the verdict.

The script applies the bars below to the checks. A `strong` the checks do not
carry is lowered to `ok`, whatever the model wrote.

### 3.1 Real

Would someone do this task in the real world, and care about the result?

`strong`: `provenance` is real_artifacts or expert_written.
`weak`: generated or invented tasks with no stated human review.
Generated or mixed tasks that people reviewed are `ok`.

### 3.2 Diverse

Diversity inside the benchmark: how many kinds of task it has.

`strong`: at least 100 tasks, and at least 5 categories in the benchmark's own
taxonomy or at least 5 distinct sources.
`weak`: fewer than 30 tasks, or one template repeated.

### 3.3 Difficult (saturation and differentiability)

`strong`: `best_score` is given as a number and is at most 60% of the maximum.
`weak`: 80% or more, or three or more recent frontier systems within 5 points
at the top.
No number: `no_evidence`.

A score reported only in the benchmark's own paper counts, but it was measured
by the authors on the models of that date. Rule B3 (saturated) still needs a
leaderboard.

### 3.4 Valuable

Kept simple: a benchmark is valuable when current models cannot do it and the
tasks need domain expertise.

`strong`: `domain_expertise` is yes and Difficult is `strong`. Set by the
script from the checks.
`weak`: a toy setting, or a variant of an existing benchmark with nothing new.

### 3.5 Solid

Can a failure on this benchmark be trusted to be the agent's failure?

`strong`: the verifier is executable or exact-match, or a model judge whose
agreement with people is reported; and `solvable` is yes.

Reward hacking is recorded (`gaming`) and shown, and counts as an adoption
risk when the paper is silent on it. This filter cannot detect reward hacking
itself: that takes running agents and reading trajectories, which is the later
audit stage.

### 3.6 Coverage (what is public)

One line each, `yes` / `partial` / `no` / `no_evidence`:

| Item | Where to look |
|---|---|
| Task data public, full or partial | repository, dataset card |
| Benchmark-level scores | leaderboard, paper |
| Task-level scores | results files, leaderboard detail |
| Trajectories | repository, dataset card |
| Analysis process: judge prompts, filtering code | repository |
| Infrastructure: harness, Docker images, run instructions | repository |

For a benchmark already in Harbor format these are read from the task
directory (`instruction.md`, `environment/`, `tests/`, `solution/`,
`task.toml`) by a script, not by the agent.

### 3.7 Attention

Stars, citations, Hugging Face likes and downloads, organisations, number of
authors, and whether a lab has reported results on it. Read per unit of time
since publication, not as raw counts: 200 stars in three weeks is more than
2,000 in three years.

Strong attention can stand in for strong Difficult in rule T2. Weak or missing attention never blocks a benchmark and never moves one
to `no`.

## 4. Harbor fit

Recorded, and used by rule B2.

- Mode: `agentic`, `modified` or `non` (Harbor Index v1, Appendix D.2).
- Can a task run in a container with a programmatic verifier? Blockers:
  physical robots, a simulator that needs a licence, live websites that cannot
  be frozen, human graders.
- Games, robots and embodied benchmarks are not out by rule. What counts is
  whether the benchmark evaluates what a language model or an agent built on
  one can do. A simulator benchmark where an LLM or VLM agent plans and acts is
  judged like any other. A benchmark for trained control policies (robot
  manipulation policies, reinforcement-learning agents, driving stacks) does
  not evaluate model or agent capability in this sense: rule B6.

## 5. Rules

Blocking rules, checked in order. The first that fires gives `no`.

| Rule | Fires when |
|---|---|
| B1 not runnable | A repository or dataset page was read and shows that no task data is public, and none is announced. With only an abstract to go on this rule cannot fire: not knowing is `hold`. |
| B2 cannot be hosted | Tasks cannot run in a container with a programmatic verifier (see section 4). |
| B3 saturated | Best score is at or above 90% of the ceiling on a leaderboard (own or aggregator), and no harder split exists. A paper-only score never fires this rule. |
| B4 superseded | The authors have released a successor that replaces it. The successor is named. |
| B5 not a benchmark | On reading the pages, it is a method, model or dataset without an evaluation protocol. |
| B6 not about model or agent capability | It evaluates trained control policies or task-specific networks, not a language model or an agent built on one. |

Then:

| Rule | Tier |
|---|---|
| T0 | Neither a paper nor a repository could be read: `hold`, decided by the script with no model call. |
| T2 | Mode is `agentic` or `modified`; none of Real, Diverse, Difficult, Valuable, Solid is `weak`; Real and Solid are both `strong`; and Difficult or Attention is `strong`. For a benchmark with the `new` flag the last condition is waived, since it can have neither yet. Never with a leaderboard score of 90% or more. The script applies this rule to the checked dimension verdicts: the model's own "recommend" stands only if they carry it. |
| T3 | Mode is `non`: `recommend` only if it is unsaturated, Difficult is `strong`, and Attention is `strong` (the Humanity's Last Exam case). Otherwise `hold`. |
| T4 | Everything else: `hold`, with the dimension that held it back named. |

## 6. Output

One JSON object per benchmark, appended with the date, the standard's version
and the model. Earlier lines are kept, so the tier history can be drawn.

```json
{
  "key": "swelancer",
  "date": "2026-11-12",
  "standard": "0.1",
  "model": "…",
  "tier": "recommend",
  "rule": "T2",
  "reason": "one sentence a person can check",
  "dimensions": {
    "real": {"verdict": "strong", "quote": "…", "url": "…"},
    "diverse": {"verdict": "ok", "quote": "…", "url": "…"},
    "difficult": {"verdict": "ok", "quote": "…", "url": "…"},
    "valuable": {"verdict": "strong", "quote": "…", "url": "…"},
    "solid": {"verdict": "no_evidence"},
    "attention": {"verdict": "strong", "quote": "…", "url": "…"}
  },
  "coverage": {"data": "yes", "scores": "yes", "task_scores": "no_evidence",
               "trajectories": "no", "process": "partial", "infra": "yes"},
  "harbor_fit": {"container": "yes", "blocker": null},
  "pages_read": ["…"]
}
```

A quote that is not on the page it cites is dropped by a script, and its
dimension becomes `no_evidence`.

## 7. Checks before a full run

1. Calibration set: the 27 benchmarks Harbor Index v1 drew tasks from should
   come out `recommend` or `hold`. Adapter List rows marked `exclude` should
   mostly come out `no` or `hold`. Every miss is read by a person and either
   the standard or the list is corrected.
2. Noise: judge 30 benchmarks twice. The share that changes tier is reported
   on the Filter page.
3. A change of tier is shown on the site with its cause: a signal changed, the
   standard changed, or the same inputs gave a different answer.

## 8. Decisions and open points

Settled on 2026-11-13, version 0.6:

- The judge answers a fixed list of checks before any verdict, and "strong"
  has an explicit bar per dimension that the script enforces. On the same 30
  benchmarks this brought the GPT judge's count of strong verdicts for Real,
  Diverse and Difficult from 13, 18, 12 down to 6, 8, 6 (Sonnet: 8, 8, 1), and
  every answer named concrete risks where before most named none.
- Valuable is defined by the project owner as: models cannot do it, and the
  tasks need domain expertise. Diverse means variety of task kinds inside the
  benchmark. Solid asks for evidence with the purpose of Harbor's oracle, not
  for an oracle by that name.
- Only benchmarks that 0.5 recommended are judged again under 0.6: the new
  bars can only lower a verdict. The others keep their 0.5 verdict until they
  are next judged.

Settled on 2026-11-13, version 0.5:

- `recommend` now needs Real and Solid strong, plus Difficult or Attention.
  Version 0.4 asked for any two strong of five and recommended 37% of what was
  judged. The same 30 benchmarks were given to two models (Sonnet 5.5 and
  gpt-6.1-terra): they agreed on "strong" for Solid 23 times and Real 21, but
  for Valuable only 16, and the GPT model called Valuable strong for 81% of the
  pool. Under the 0.4 rule the two models gave the same tier 23 times of 30;
  under this rule 28. Valuable and Diverse are still judged and shown, and a
  weak one still blocks, but they no longer earn a recommend.
- Only the way verdicts combine changed, so nothing was read again:
  `tier.py --rerule` re-derived every tier from the stored dimension verdicts.

Settled on 2026-11-12:

- Version 0.4: Attention counts toward the two strong dimensions. The `new`
  window is 15 days, because the field moves fast. The judge reads the whole
  paper, not the abstract, at medium reasoning effort. The first 133 verdicts
  were made by Sonnet 5.5 and the rest by a GPT model through the team's
  proxy; each verdict records its model. Everything is
  judged again; no earlier verdict carries over.
- Version 0.3: `too_new` is no longer a tier. The newest benchmarks are what
  this pool is for, so they are judged in full and carry a `new` flag. Every
  other rule is unchanged, so judgements a model made under 0.2 stand under
  0.3; only the benchmarks 0.2 had set aside as `too_new` are judged again.
- "New for Harbor Index" means not covered by v1 and without a merged adapter,
  whatever the publication date.

- T3: a non-agentic benchmark can be `recommend`, under the conditions in T3.
- B3: the saturation bar is 90%.
- B2/B6: embodied and game benchmarks are judged on whether they evaluate
  model or agent capability, not excluded as a class.

Still open:

- The attention bar of the `new` flag.
- Whether a benchmark with a saturated main split but a hard subset stays in.
- Moving the judge to a stronger model that can open pages itself.
