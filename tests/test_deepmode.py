"""Deep-mode multi-run variance + Tier-3 LLM NER guard (§7.5 / §7.1)."""

from debugai import analyze
from debugai.signals import _extract_entities, measure_variance


def test_measure_variance_stable_vs_unstable():
    stable = measure_variance(lambda s, u, c, t: "The capital of France is Paris.",
                              "", "q", [], 0.0, runs=3)
    assert stable < 0.2  # identical outputs → low variance
    flip = {"n": 0}

    def unstable(s, u, c, t):
        flip["n"] += 1
        return ["Yes, absolutely, the answer is clearly affirmative.",
                "No, definitely not, that is completely wrong.",
                "Maybe; it depends entirely on unrelated contextual factors."][flip["n"] % 3]

    assert measure_variance(unstable, "", "q", [], 0.9, runs=3) > 0.3


def test_analyze_deep_mode_overrides_variance_method():
    # No temperature → proxy variance is 0; deep mode measures it from reruns.
    r = analyze(prompt="Summarize the notes.", output="The team agreed on the plan.",
                chunks=["The team agreed on the plan."], similarity_scores=[0.85],
                explain_with_llm=False,
                variance_rerun=lambda s, u, c, t: "wildly " + str(hash((u, t))),
                variance_runs=3)
    assert r["signals"]["variance_method"] == "measured"


def test_tier3_ner_off_by_default():
    # No DEBUGAI_LLM_NER / key → all-lowercase text with no regex entities yields
    # an empty entity set (no LLM call).
    assert _extract_entities("the quick brown fox jumps over the lazy dog") == set()
