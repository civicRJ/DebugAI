"""Fix Agent Framework tests (§8) — the full diagnose-fix-verify loop.

A fake `rerun` model stands in for the LLM: it answers strictly from the
provided context, so a working fix makes fabrications disappear and lets the
deterministic re-diagnosis confirm (or refute) the fix.
"""

import pytest

from debugai import analyze
from debugai.agents import (
    DEFAULT_REGISTRY, ESCALATED, FAILED, MITIGATED, PENDING_RERUN, VERIFIED,
    AmbiguityGateAgent, CitationVerifierAgent, ConstraintAgent, ContextOptimizerAgent,
    DocumentPatchAgent, FixAgent, FixAgentRegistry, KnowledgeBaseAgent, PromptRuleAgent,
    SchemaRepairAgent, ToolContractAgent, propose_fix,
)
from debugai.schema import CaptureRecord


def fake_rerun(system_prompt, user_prompt, chunks, temperature):
    """A grounded model: answers only from the supplied context."""
    ctx = " ".join(chunks)
    return "Per the provided context: " + ctx if ctx else "I don't have that information."


def diagnose_record(**kw):
    rec = CaptureRecord(
        user_prompt=kw["prompt"], llm_output=kw["output"],
        system_prompt=kw.get("system_prompt", ""),
        retrieved_chunks=kw.get("chunks", []),
        similarity_scores=kw.get("similarity_scores", []),
        temperature=kw.get("temperature"), context_window=kw.get("context_window"),
        max_tokens=kw.get("max_tokens"), latency_ms=kw.get("latency_ms"),
        tool_calls=kw.get("tool_calls", []),
        tools_expected=kw.get("tools_expected", []),
        response_schema=kw.get("response_schema"),
    )
    diag = analyze(
        prompt=rec.user_prompt, output=rec.llm_output, system_prompt=rec.system_prompt,
        chunks=rec.retrieved_chunks, similarity_scores=rec.similarity_scores,
        temperature=rec.temperature, context_window=rec.context_window,
        max_tokens=rec.max_tokens, latency_ms=rec.latency_ms, explain_with_llm=False,
        tool_calls=rec.tool_calls, tools_expected=rec.tools_expected,
        response_schema=rec.response_schema,
    )
    return diag, rec


# --- scenarios (mirror the labeled dataset) --------------------------------
HALLUCINATION = dict(
    prompt="What does Section 4 of the contract require?",
    output="Section 4 requires arbitration in Delaware under the Marbury Clause and a $50,000 penalty.",
    chunks=["Section 4 covers confidentiality obligations between the parties.",
            "The contract is governed by the laws of California."],
    similarity_scores=[0.66, 0.59], temperature=0.75,
)
RETRIEVAL = dict(
    prompt="What is the refund policy for electronics?",
    output="Electronics can be returned within 90 days for a full cash refund.",
    chunks=["Our store hours are 9am to 5pm.", "Parking is behind the building."],
    similarity_scores=[0.42, 0.40], temperature=0.2,
)
BRITTLE = dict(
    prompt="Summarize the meeting notes.",
    output="The team agreed on the Q4 timeline and assigned the design review to the platform group.",
    chunks=["Meeting notes: the team agreed on the Q4 timeline.",
            "Action item: design review assigned to the platform group."],
    similarity_scores=[0.83, 0.80], temperature=0.9,
)
OVERFLOW = dict(
    prompt="Based on the full report, what is the conclusion?",
    output="The report concludes the pilot was a partial success but recommends further study.",
    chunks=["The quarterly report covers financial performance across all twelve regional "
            "divisions, including detailed revenue breakdowns, operating costs, headcount "
            "changes, capital expenditures, supply-chain risks, regulatory exposure, and a "
            "long regional outlook narrative for each division. It then repeats the same "
            "structure for the prior fiscal year and the year before that, with appendices "
            "of dense tabular data, footnotes, methodology notes, and a glossary spanning "
            "many additional pages of prose that fills the entire context window completely."],
    similarity_scores=[0.74], temperature=0.2, context_window=160, max_tokens=4096, latency_ms=3500,
)
ENTITY = dict(
    prompt="What is the maximum torque of the Model X engine?",
    output="The Model X engine produces a maximum torque of 420 Nm at 3500 rpm.",
    chunks=["The Model X engine is a 2.0 liter turbocharged four cylinder unit.",
            "The Model X engine uses direct injection and a variable geometry turbo."],
    similarity_scores=[0.72, 0.70], temperature=0.15,
)


# --- registry / selection --------------------------------------------------
def test_registry_selects_right_agent_per_failure():
    cases = {
        "hallucination": PromptRuleAgent, "retrieval_failure": KnowledgeBaseAgent,
        "prompt_brittleness": ConstraintAgent, "context_overflow": ContextOptimizerAgent,
        "entity_gap": DocumentPatchAgent,
        "schema_violation": SchemaRepairAgent, "tool_call_failure": ToolContractAgent,
        "citation_failure": CitationVerifierAgent, "ambiguous_prompt": AmbiguityGateAgent,
    }
    for failure, cls in cases.items():
        diag = {"healthy": False, "primary": {"failure": failure}}
        assert isinstance(DEFAULT_REGISTRY.find_agent(diag), cls)


def test_custom_agent_takes_priority():
    class SyllabusAgent(FixAgent):
        name = "Syllabus Agent"
        handles = "hallucination"
        def generate_fix(self, d, r): ...
        def build_test_cases(self, d, r): return []
    reg = FixAgentRegistry()
    reg.register(SyllabusAgent())
    diag = {"healthy": False, "primary": {"failure": "hallucination"}}
    assert reg.find_agent(diag).name == "Syllabus Agent"


def test_healthy_has_no_fix():
    diag = {"healthy": True, "primary": None}
    assert propose_fix(diag, CaptureRecord(user_prompt="q", llm_output="a")) is None


def test_pending_when_no_model():
    diag, rec = diagnose_record(**HALLUCINATION)
    report = propose_fix(diag, rec, rerun=None)
    assert report.verdict == PENDING_RERUN
    assert report.tests_total > 0 and report.candidate.system_prompt_additions


# --- full loop per agent ---------------------------------------------------
def test_prompt_rule_agent_verifies_hallucination_fix():
    diag, rec = diagnose_record(**HALLUCINATION)
    assert diag["primary"]["failure"] == "hallucination"
    report = propose_fix(diag, rec, rerun=fake_rerun)
    assert report.agent == "Prompt Rule Agent"
    assert report.tests_passed == report.tests_total
    assert report.reverified_cleared is True
    assert report.verdict == VERIFIED


def test_constraint_agent_verifies_brittleness_fix():
    diag, rec = diagnose_record(**BRITTLE)
    assert diag["primary"]["failure"] == "prompt_brittleness"
    report = propose_fix(diag, rec, rerun=fake_rerun)
    assert report.candidate.new_temperature == 0.2
    assert report.verdict == VERIFIED


def test_context_optimizer_verifies_overflow_fix():
    diag, rec = diagnose_record(**OVERFLOW)
    assert diag["primary"]["failure"] == "context_overflow"
    report = propose_fix(diag, rec, rerun=fake_rerun)
    assert report.candidate.max_chunks == 8
    assert "retrieved_chunks" in report.diff
    assert report.verdict == VERIFIED


def test_knowledge_base_agent_mitigates_retrieval_failure():
    diag, rec = diagnose_record(**RETRIEVAL)
    assert diag["primary"]["failure"] == "retrieval_failure"
    report = propose_fix(diag, rec, rerun=fake_rerun)
    # Interim guard stops fabrication (tests pass) but similarity is unchanged,
    # so the deterministic re-check still sees retrieval failure → MITIGATED.
    assert report.tests_passed == report.tests_total
    assert report.verdict == MITIGATED
    assert "re-chunk" in report.candidate.notes.lower()


def test_document_patch_agent_escalates_entity_gap():
    diag, rec = diagnose_record(**ENTITY)
    assert diag["primary"]["failure"] == "entity_gap"
    report = propose_fix(diag, rec, rerun=fake_rerun)
    assert report.verdict == ESCALATED
    assert report.candidate.escalate is True
    assert report.candidate.notes  # names the missing entities


def test_schema_repair_agent_verifies_valid_json_rerun():
    schema = {
        "type": "object",
        "required": ["status", "answer"],
        "properties": {
            "status": {"type": "string", "enum": ["ok", "error"]},
            "answer": {"type": "string"},
        },
    }
    diag, rec = diagnose_record(
        prompt="Return JSON.",
        output='{"status": "maybe"}',
        response_schema=schema,
    )
    assert diag["primary"]["failure"] == "schema_violation"
    report = propose_fix(diag, rec, rerun=lambda s, u, c, t: '{"status":"ok","answer":"done"}')
    assert report.agent == "Schema Repair Agent"
    assert report.verdict == VERIFIED


def test_tool_contract_agent_mitigates_tool_failure():
    diag, rec = diagnose_record(
        prompt="Search the policy.",
        output="The policy is unchanged.",
        tools_expected=["search"],
    )
    assert diag["primary"]["failure"] == "tool_call_failure"
    report = propose_fix(diag, rec, rerun=fake_rerun)
    assert report.agent == "Tool Contract Agent"
    assert report.verdict == MITIGATED
    assert "Allowed tools: search" in report.candidate.notes


def test_citation_verifier_agent_verifies_corrected_citation():
    diag, rec = diagnose_record(
        prompt="Answer with citations.",
        system_prompt="Cite every factual claim.",
        output="Refunds are available within 30 days.",
        chunks=["Refunds are available within 30 days."],
        similarity_scores=[0.9],
    )
    assert diag["primary"]["failure"] == "citation_failure"
    report = propose_fix(diag, rec, rerun=lambda s, u, c, t: "Refunds are available within 30 days [1].")
    assert report.agent == "Citation Verifier Agent"
    assert report.verdict == VERIFIED


def test_ambiguity_gate_agent_verifies_clarifying_question():
    diag, rec = diagnose_record(
        prompt="Can you do it?",
        output=" ".join(["I will proceed using reasonable assumptions"] * 5),
    )
    assert diag["primary"]["failure"] == "ambiguous_prompt"
    report = propose_fix(diag, rec, rerun=lambda s, u, c, t: "Which task do you want me to do?")
    assert report.agent == "Ambiguity Gate Agent"
    assert report.verdict == VERIFIED


def test_failed_when_fix_does_not_clear():
    # A rerun model that ignores the fix and keeps fabricating → not cleared.
    diag, rec = diagnose_record(**HALLUCINATION)
    bad_output = HALLUCINATION["output"]
    report = propose_fix(diag, rec, rerun=lambda s, u, c, t: bad_output)
    assert report.verdict == FAILED
