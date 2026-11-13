"""Checks for the rules that decide names, scores and gate output.

    python3 -m unittest discover -s tests -v      (run from the repository root)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from candidates import arxiv_id, has_traction, link_kind  # noqa: E402
from build import differences  # noqa: E402
from classify import clean, upgrade  # noqa: E402
from leaderboards import norm_name  # noqa: E402
import datetime as dt  # noqa: E402
import tier  # noqa: E402
from signals import own_repo  # noqa: E402

CANDIDATE = {
    "id": "arxiv-0000-00001",
    "title": "DemoBench: agents in a sandbox",
    "summary": "We test agents in a sandbox. The best agent\nreaches only 41.5% success rate.",
}
PASS = {"id": CANDIDATE["id"], "bench": True, "mode": "agentic", "why": "acts in a sandbox", "name": "DemoBench",
        "cls": 5, "sub": None, "mm": False, "real": "r", "val": "v", "data": "public", "scores": "yes"}


class NormName(unittest.TestCase):
    def test_spelling_variants_match(self):
        self.assertEqual(norm_name("Terminal-Bench 2.0"), norm_name("Terminal Bench 2.0"))
        self.assertEqual(norm_name("SWE-bench Pro"), norm_name("SWE-Bench Pro"))
        self.assertEqual(norm_name("τ²-Bench Telecom"), "tau2benchtelecom")

    def test_greek_letters_are_not_dropped(self):
        # "Δτ-Bench" once matched the leaderboard row for "Tau-bench".
        self.assertNotEqual(norm_name("Δτ-Bench"), norm_name("Tau-bench"))


class Clean(unittest.TestCase):
    def test_dropped_record_keeps_only_the_verdict(self):
        out = clean({"id": "x", "bench": False, "why": "a method paper"}, CANDIDATE, "m")
        self.assertFalse(out["bench"])
        self.assertNotIn("cls", out)

    def test_non_agentic_benchmark_is_kept_with_its_mode(self):
        out = clean(dict(PASS, mode="non", cls=2), CANDIDATE, "m")
        self.assertTrue(out["bench"])
        self.assertEqual((out["mode"], out["cls"]), ("non", 2))

    def test_benchmark_without_a_valid_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            clean(dict(PASS, mode="sort of"), CANDIDATE, "m")

    def test_adapter_list_row_is_always_a_benchmark(self):
        seed = dict(CANDIDATE, origin="adapter_list")
        self.assertTrue(clean(dict(PASS, bench=False), seed, "m")["bench"])

    def test_score_kept_when_quote_is_in_the_abstract(self):
        row = dict(PASS, best=41.5, best_quote="The best agent reaches only 41.5% success rate", best_model="agent")
        self.assertEqual(clean(row, CANDIDATE, "m")["best"], 41.5)

    def test_score_dropped_when_quote_is_invented(self):
        row = dict(PASS, best=97, best_quote="agents reach 97% success")
        out = clean(row, CANDIDATE, "m")
        self.assertIsNone(out["best"])
        self.assertIsNone(out["best_quote"])

    def test_score_dropped_when_number_not_in_quote(self):
        row = dict(PASS, best=80, best_quote="The best agent reaches only 41.5% success rate")
        self.assertIsNone(clean(row, CANDIDATE, "m")["best"])

    def test_bad_class_is_rejected(self):
        with self.assertRaises(ValueError):
            clean(dict(PASS, cls=12), CANDIDATE, "m")

    def test_sub_class_must_belong_to_the_class(self):
        self.assertIsNone(clean(dict(PASS, sub="Repo issue/test"), CANDIDATE, "m")["sub"])
        self.assertEqual(clean(dict(PASS, cls=1, sub=None), CANDIDATE, "m")["sub"], "Other")


class Candidates(unittest.TestCase):
    def test_arxiv_id_from_each_source(self):
        self.assertEqual(arxiv_id({"url": "https://arxiv.org/abs/2611.12118"}), "2611.12118")
        self.assertEqual(arxiv_id({"url": "https://doi.org/10.48550/arxiv.2611.10026"}), "2611.10026")
        self.assertEqual(arxiv_id({"url": "https://huggingface.co/papers/2611.12118"}), "2611.12118")
        self.assertIsNone(arxiv_id({"url": "https://github.com/a/b"}))

    def test_link_kind(self):
        self.assertEqual(link_kind("https://github.com/a/b"), "code")
        self.assertEqual(link_kind("https://huggingface.co/datasets/a/b"), "data")
        self.assertEqual(link_kind("https://arxiv.org/abs/2611.12118"), "paper")


if __name__ == "__main__":
    unittest.main()


class UpgradeV1Labels(unittest.TestCase):
    V1 = {"id": "a", "prompt_version": 1, "model": "haiku", "bench": True, "agentic": True, "why": "w",
          "name": "X", "cls": 9, "sub": None, "mm": False}

    def test_agentic_benchmark_keeps_its_answer_and_moves_to_class_10(self):
        out = upgrade(dict(self.V1))
        self.assertEqual((out["mode"], out["cls"]), ("agentic", 10))
        self.assertNotIn("agentic", out)

    def test_other_classes_are_unchanged(self):
        self.assertEqual(upgrade(dict(self.V1, cls=5))["cls"], 5)

    def test_non_agentic_benchmark_is_asked_again(self):
        # version 1 stored no class for these, and "not agentic" may now be "modified"
        self.assertIsNone(upgrade({"id": "a", "prompt_version": 1, "bench": True, "agentic": False, "why": "w"}))

    def test_non_benchmark_stays_dropped(self):
        self.assertFalse(upgrade({"id": "a", "prompt_version": 1, "bench": False, "agentic": True, "why": "w"})["bench"])


class AdapterListDifferences(unittest.TestCase):
    ROW = {"mode": "non", "saturated": "Somewhat (20-50)"}

    def test_no_row_no_difference(self):
        self.assertEqual(differences(None, "agentic", 99.0, "own"), [])

    def test_same_mode_and_score_inside_the_bucket(self):
        self.assertEqual(differences(self.ROW, "non", 35.0, "aggregator"), [])

    def test_mode_and_saturation_are_reported_separately(self):
        fields = [d["field"] for d in differences(self.ROW, "modified", 71.2, "aggregator")]
        self.assertEqual(fields, ["mode", "saturation"])

    def test_missing_score_or_unlabelled_row_is_not_a_difference(self):
        self.assertEqual(differences({"mode": None, "saturated": "Hard to Define"}, "agentic", None, None), [])


class Traction(unittest.TestCase):
    def test_one_count_over_its_bar_is_enough(self):
        self.assertTrue(has_traction({"metrics": {"upvotes": 10}}))
        self.assertTrue(has_traction({"metrics": {"stars": 3479, "downloads": 17}}))

    def test_zero_missing_or_small_counts_are_not_traction(self):
        self.assertFalse(has_traction({}))
        self.assertFalse(has_traction({"metrics": {"citations": 0, "upvotes": 9, "stars": None}}))


class OwnRepo(unittest.TestCase):
    def test_aggregator_repository_is_not_a_benchmarks_own(self):
        self.assertIsNone(own_repo("https://github.com/evaleval/benchmark-saturation/blob/abc/data/x.csv"))
        self.assertEqual(own_repo("https://github.com/SWE-bench/SWE-bench"), "SWE-bench/SWE-bench")


class TierRules(unittest.TestCase):
    TODAY = dt.date(2026, 11, 12)
    ITEM = {"date": "2026-11-05", "lb": "none", "metrics": {"stars": 3}, "mode": "agentic", "best": None, "basis": None}
    PACK = {"TEXT": {"abstract": "Tasks are real GitHub issues from 12 repositories. Tests are executable. "
                                 "Every task has a merged fix that passes."}, "FACTS": {}}
    CHECKS = {"provenance": {"value": "real_artifacts", "quote": "real GitHub issues from 12 repositories"},
              "verifier": {"value": "executable", "quote": "Tests are executable"},
              "solvable": {"value": "yes", "quote": "Every task has a merged fix that passes"}}

    def answer(self, **dims):
        full = {d: {"verdict": "ok"} for d in tier.DIMENSIONS}
        full.update(dims)
        return {"tier": "recommend", "rule": "T2", "reason": "r", "dimensions": full, "checks": self.CHECKS}

    def test_new_quiet_benchmark_gets_the_new_flag(self):
        self.assertTrue(tier.is_new(self.ITEM, self.TODAY))

    def test_attention_leaderboard_or_age_remove_the_new_flag(self):
        self.assertFalse(tier.is_new(dict(self.ITEM, metrics={"stars": 250}), self.TODAY))
        self.assertFalse(tier.is_new(dict(self.ITEM, lb="own"), self.TODAY))
        self.assertFalse(tier.is_new(dict(self.ITEM, date="2026-10-20"), self.TODAY))     # 23 days: past the 15-day window
        self.assertFalse(tier.is_new(dict(self.ITEM, date=None), self.TODAY))

    def test_recommend_stands_when_real_and_solid_are_strong_with_real_quotes(self):
        pack = dict(self.PACK, FACTS={"new": True})      # a new benchmark: Real and Solid are enough
        out = tier.check(self.answer(real={"verdict": "strong", "quote": "real GitHub issues from 12 repositories"},
                                     solid={"verdict": "strong", "quote": "Tests are executable"}), pack, self.ITEM)
        self.assertEqual((out["tier"], out["rule"], out["notes"]), ("recommend", "T2", []))

    def test_invented_quote_drops_the_verdict_and_the_tier(self):
        out = tier.check(self.answer(real={"verdict": "strong", "quote": "curated by 40 senior engineers"},
                                     solid={"verdict": "strong", "quote": "Tests are executable"}), self.PACK, self.ITEM)
        self.assertEqual(out["dimensions"]["real"]["verdict"], "no_evidence")
        self.assertEqual((out["tier"], out["rule"]), ("hold", "T4"))

    def test_saturated_on_a_leaderboard_cannot_be_recommended(self):
        item = dict(self.ITEM, best=95.0, basis="aggregator")
        out = tier.check(self.answer(real={"verdict": "strong", "quote": "real GitHub issues from 12 repositories"},
                                     solid={"verdict": "strong", "quote": "Tests are executable"}), self.PACK, item)
        self.assertEqual(out["tier"], "hold")

    def test_b3_needs_a_leaderboard_score_not_a_paper_figure(self):
        row = dict(self.answer(), tier="no", rule="B3")
        self.assertEqual(tier.check(row, self.PACK, dict(self.ITEM, best=96.0, basis="paper"))["tier"], "hold")
        self.assertEqual(tier.check(row, self.PACK, dict(self.ITEM, best=96.0, basis="own"))["tier"], "no")

    def test_non_agentic_needs_strong_difficulty_and_attention(self):
        item = dict(self.ITEM, mode="non", best=37.7, basis="aggregator")
        weak = tier.check(self.answer(difficult={"verdict": "strong"}), self.PACK, item)
        strong = tier.check(self.answer(difficult={"verdict": "strong"}, attention={"verdict": "strong"}), self.PACK, item)
        self.assertEqual((weak["tier"], strong["tier"], strong["rule"]), ("hold", "recommend", "T3"))

    def test_no_public_data_cannot_be_concluded_from_an_abstract_alone(self):
        row = dict(self.answer(), tier="no", rule="B1")
        self.assertEqual(tier.check(row, self.PACK, self.ITEM)["tier"], "hold")
        read = {"TEXT": dict(self.PACK["TEXT"], readme="Code only. The task set is not released."), "FACTS": {}}
        self.assertEqual(tier.check(row, read, self.ITEM)["tier"], "no")

    def test_model_verdicts_from_0_2_stand_under_0_3_but_too_new_does_not(self):
        self.assertTrue(tier.current({"standard": "0.2", "model": "haiku", "tier": "hold"}, "0.3"))
        self.assertFalse(tier.current({"standard": "0.2", "model": None, "tier": "too_new"}, "0.3"))
        self.assertFalse(tier.current({"standard": "0.1", "model": "haiku", "tier": "hold"}, "0.3"))


class Covered(unittest.TestCase):
    def test_v1_source_or_merged_adapter_is_covered(self):
        from build import covered_by
        self.assertEqual(covered_by(5, None), "v1")
        self.assertEqual(covered_by(None, {"status": "Merged"}), "adapter")
        self.assertIsNone(covered_by(None, {"status": "Working"}))
        self.assertIsNone(covered_by(None, None))


class RecommendRule(unittest.TestCase):
    """Standard 0.5: Real and Solid strong, plus Difficult or Attention (waived when new)."""
    OLD = {"mode": "agentic", "best": None, "basis": None}

    def dims(self, **strong_or_other):
        d = {name: {"verdict": "ok"} for name in tier.DIMENSIONS}
        d.update({k: {"verdict": v} for k, v in strong_or_other.items()})
        return d

    def test_real_and_solid_alone_are_not_enough_for_an_older_benchmark(self):
        self.assertFalse(tier.supports_recommend(self.dims(real="strong", solid="strong"), self.OLD, new=False)[0])

    def test_difficult_or_attention_completes_it(self):
        self.assertTrue(tier.supports_recommend(self.dims(real="strong", solid="strong", difficult="strong"), self.OLD, False)[0])
        self.assertTrue(tier.supports_recommend(self.dims(real="strong", solid="strong", attention="strong"), self.OLD, False)[0])

    def test_new_benchmark_needs_only_real_and_solid(self):
        self.assertTrue(tier.supports_recommend(self.dims(real="strong", solid="strong"), self.OLD, new=True)[0])

    def test_valuable_and_diverse_do_not_earn_a_recommend(self):
        self.assertFalse(tier.supports_recommend(self.dims(valuable="strong", diverse="strong", difficult="strong"), self.OLD, False)[0])

    def test_a_weak_dimension_blocks_but_weak_attention_does_not(self):
        base = dict(real="strong", solid="strong", difficult="strong")
        self.assertFalse(tier.supports_recommend(self.dims(**base, diverse="weak"), self.OLD, False)[0])
        self.assertTrue(tier.supports_recommend(self.dims(**base, attention="weak"), self.OLD, False)[0])


class Reading(unittest.TestCase):
    def test_reference_list_is_cut_but_the_appendix_after_it_is_kept(self):
        body = "Intro. " * 400 + "\nReferences\n[1] A paper. [2] Another.\nAppendix A Task Details\nJudge prompt here."
        out = tier.drop_references(body)
        self.assertNotIn("[1] A paper", out)
        self.assertIn("Judge prompt here", out)

    def test_packet_records_a_cut_paper(self):
        item = {"key": "k", "name": "n", "mode": "agentic", "class_name": "c", "date": None, "lb": "none", "links": [], "best": None}
        pack, read = tier.packet(item, "abstract", None, {"text": "x" * (tier.PAPER_LIMIT + 5), "via": "arxiv html"}, dt.date(2026, 11, 12))
        self.assertTrue(read["paper_cut"])
        self.assertNotIn("abstract", pack["TEXT"])


class Bars(unittest.TestCase):
    """Standard 0.6, section 3: a strong the checks do not carry becomes ok."""
    T = TierRules()
    STRONG = dict(real={"verdict": "strong", "quote": "real GitHub issues from 12 repositories"},
                  solid={"verdict": "strong", "quote": "Tests are executable"})

    def judged(self, checks, **dims):
        row = dict(self.T.answer(**dims), checks=checks)
        return tier.check(row, self.T.PACK, self.T.ITEM)

    def test_real_needs_real_or_expert_provenance(self):
        checks = dict(self.T.CHECKS, provenance={"value": "generated", "quote": "Tasks are real GitHub issues"})
        self.assertEqual(self.judged(checks, **self.STRONG)["dimensions"]["real"]["verdict"], "ok")

    def test_solid_needs_evidence_that_tasks_are_solvable(self):
        checks = {k: v for k, v in self.T.CHECKS.items() if k != "solvable"}
        out = self.judged(checks, **self.STRONG)
        self.assertEqual(out["dimensions"]["solid"]["verdict"], "ok")
        self.assertEqual(out["checks"]["solvable"]["value"], "not_stated")

    def test_a_check_without_its_quote_in_the_text_is_not_stated(self):
        checks = dict(self.T.CHECKS, solvable={"value": "yes", "quote": "an oracle solution passes every task"})
        self.assertEqual(self.judged(checks, **self.STRONG)["checks"]["solvable"]["value"], "not_stated")

    def test_valuable_is_domain_expertise_plus_unsolved(self):
        pack = {"TEXT": {"abstract": self.T.PACK["TEXT"]["abstract"] + " Tasks need a licensed accountant. The best agent solves 31% of tasks."}, "FACTS": {}}
        checks = dict(self.T.CHECKS, domain_expertise={"value": "yes", "quote": "Tasks need a licensed accountant"},
                      best_score={"percent": 31, "system": "agent", "run_by": "authors", "quote": "The best agent solves 31% of tasks"})
        row = dict(self.T.answer(difficult={"verdict": "strong"}, valuable={"verdict": "ok"}), checks=checks)
        self.assertEqual(tier.check(row, pack, self.T.ITEM)["dimensions"]["valuable"]["verdict"], "strong")
        easy = dict(checks, best_score={"percent": 88, "system": "agent", "run_by": "authors", "quote": "The best agent solves 31% of tasks"})
        out = tier.check(dict(row, checks=easy), pack, self.T.ITEM)["dimensions"]
        self.assertEqual((out["difficult"]["verdict"], out["valuable"]["verdict"]), ("weak", "ok"))

    def test_only_a_0_5_recommend_is_judged_again_under_0_6(self):
        self.assertTrue(tier.current({"standard": "0.5", "model": "m", "tier": "hold"}, "0.6"))
        self.assertFalse(tier.current({"standard": "0.5", "model": "m", "tier": "recommend"}, "0.6"))
