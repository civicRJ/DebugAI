"""Instruction-adherence judge + Socratic fix agent (heuristic path, no API key)."""

from debugai import analyze
from debugai.agents import (
    DEFAULT_REGISTRY, PENDING_RERUN, SocraticTutorAgent, propose_fix,
)
from debugai.judge import INSTRUCTION_VIOLATION, judge_instructions
from debugai.schema import CaptureRecord

SYS = ("You are Vin, a Socratic tutor. Do not give away the solution in the first "
       "one or two responses. A response must contain only one question. Ask one "
       "leading question. Never start by paraphrasing the student.")
USER = "Explain why convex lenses converge light while concave lenses diverge it."
BAD = ("Convex and concave lenses are made of tiny prisms. In a convex lens the prism "
       "bases face the axis so rays converge; in a concave lens the bases face away so "
       "rays diverge. Light always bends towards the prism base, which is the whole "
       "reason a convex lens focuses light and a concave lens spreads it out across the "
       "principal axis. Thinking about that prism idea, how do the prism bases explain "
       "why one converges and the other diverges?")
GOOD = ("Good question to explore. What do you notice about how a convex lens's "
        "thickness changes from its centre to its edge?")


def test_judge_flags_reveal_too_much():
    d = judge_instructions(SYS, USER, BAD)
    assert d.healthy is False and d.model == "heuristic"
    assert any("reveal" in v.rule.lower() for v in d.violations)
    assert d.confidence > 0.5


def test_judge_passes_compliant_socratic_reply():
    d = judge_instructions(SYS, USER, GOOD)
    assert d.healthy is True and not d.violations


def test_judge_too_many_questions():
    d = judge_instructions(SYS, USER, "What is a lens? And how does it bend light?")
    assert d.healthy is False
    assert any("more than one question" in v.rule.lower() for v in d.violations)


def test_no_system_prompt_is_healthy():
    assert judge_instructions("", USER, BAD).healthy is True


def test_analyze_judge_merges_instruction_violation():
    r = analyze(prompt=USER, output=BAD, system_prompt=SYS,
                chunks=["convex converges; concave diverges; prism bases"],
                similarity_scores=[0.85], temperature=0.3,
                explain_with_llm=False, judge=True)
    assert r["healthy"] is False
    assert r["primary"]["failure"] == INSTRUCTION_VIOLATION
    assert r["primary"]["evidence"]["violations"]


def test_judge_off_by_default():
    # Without judge=True the behavioural check never runs (grounding only).
    r = analyze(prompt=USER, output=BAD, system_prompt=SYS,
                chunks=["convex converges; concave diverges"],
                similarity_scores=[0.85], explain_with_llm=False)
    assert r["primary"] is None or r["primary"]["failure"] != INSTRUCTION_VIOLATION


def test_socratic_agent_selected_and_rewrites_prompt():
    diag = {"healthy": False, "primary": {"failure": INSTRUCTION_VIOLATION,
            "confidence": 0.85, "severity": "critical", "evidence": {"violations": []}}}
    agent = DEFAULT_REGISTRY.find_agent(diag)
    assert isinstance(agent, SocraticTutorAgent)
    rec = CaptureRecord(user_prompt=USER, llm_output=BAD, system_prompt=SYS)
    report = propose_fix(diag, rec, rerun=None)
    assert report.verdict == PENDING_RERUN
    assert "Socratic" in report.candidate.system_prompt_additions
    assert "one" in report.candidate.system_prompt_additions.lower()


def test_socratic_agent_verifies_via_rejudge():
    # A rerun that returns a compliant Socratic reply → re-judge clears it.
    diag = {"healthy": False, "primary": {"failure": INSTRUCTION_VIOLATION,
            "confidence": 0.85, "severity": "critical", "evidence": {"violations": []}}}
    rec = CaptureRecord(user_prompt=USER, llm_output=BAD, system_prompt=SYS)
    report = propose_fix(diag, rec, rerun=lambda s, u, c, t: GOOD)
    assert report.reverified is True
    assert report.reverified_cleared is True
    assert report.verdict == "verified"
    assert report.after_output == GOOD
