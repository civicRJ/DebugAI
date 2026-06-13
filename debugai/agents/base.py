"""Abstract FixAgent + the universal diagnose-fix-verify loop (Architecture §8.1).

    1. Diagnose        (deterministic — already done; passed in)
    2. Generate fix    (agent — generate_fix)
    3. Build tests     (agent — build_test_cases)
    4. Run regression  (deterministic — _run_test)
    5. Re-diagnose     (deterministic — Layer 1+2 on the re-run output)
    6. Developer review (human — consumes the FixReport)

The agent (steps 2-3) is the only probabilistic part, and it is sandwiched
between deterministic verification. Re-running the model is injected as a
`rerun` callable so the framework has no hard dependency on any LLM:

    rerun(system_prompt, user_prompt, chunks, temperature) -> output_text
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable

from debugai.agents.types import (
    ESCALATED, FAILED, MITIGATED, PENDING_RERUN, VERIFIED,
    FixCandidate, FixReport, TestCase, TestResult,
)
from debugai.analyze import analyze
from debugai.schema import CaptureRecord
from debugai.signals import _extract_entities

log = logging.getLogger("debugai.agents")

Rerun = Callable[[str, str, list, "float | None"], str]


@dataclass
class _Applied:
    system_prompt: str
    chunks: list[str]
    similarity_scores: list[float]
    temperature: float | None


class FixAgent(ABC):
    name: str = "fix-agent"
    handles: str = ""  # failure id this agent targets
    # When False, the fix lives in the pipeline (e.g. re-chunking) and a prompt-only
    # rerun can't structurally clear the failure — tests verify an interim guard,
    # and a clean test pass yields a MITIGATED (not VERIFIED) verdict.
    verifiable_by_rerun: bool = True

    # --- selection ---------------------------------------------------------
    def can_handle(self, diagnosis: dict) -> bool:
        primary = (diagnosis or {}).get("primary") or {}
        return primary.get("failure") == self.handles

    # --- agent-specific (subclasses implement) -----------------------------
    @abstractmethod
    def generate_fix(self, diagnosis: dict, record: CaptureRecord) -> FixCandidate: ...

    @abstractmethod
    def build_test_cases(self, diagnosis: dict, record: CaptureRecord) -> list[TestCase]: ...

    # --- the inherited loop ------------------------------------------------
    def run(self, diagnosis: dict, record: CaptureRecord, rerun: Rerun | None = None) -> FixReport:
        candidate = self.generate_fix(diagnosis, record)
        before_conf = ((diagnosis.get("primary") or {}).get("confidence"))

        if candidate.escalate:
            return FixReport(
                agent=self.name, failure=self.handles, verdict=ESCALATED,
                candidate=candidate, diff=self._diff(candidate, record),
                before_confidence=before_conf,
            )

        tests = self.build_test_cases(diagnosis, record)
        report = FixReport(
            agent=self.name, failure=self.handles, verdict=PENDING_RERUN,
            candidate=candidate, diff=self._diff(candidate, record),
            tests_total=len(tests), before_confidence=before_conf,
        )
        if rerun is None:
            # Candidate + tests produced, but nothing to execute them against.
            report.test_results = [TestResult(case=t, passed=False,
                                              failures=["not run (no model)"]) for t in tests]
            return report

        applied = self._apply(candidate, record)

        # Step 4 — deterministic regression tests.
        results = [self._run_test(t, applied, rerun) for t in tests]
        report.test_results = results
        report.tests_passed = sum(1 for r in results if r.passed)

        # Step 5 — re-diagnose the original failing request with the fix applied.
        after, after_output = self._rediagnose(record, applied, rerun)
        report.reverified = True
        report.after_diagnosis = after
        report.after_output = after_output
        cleared = after.get("healthy") or (
            (after.get("primary") or {}).get("failure") != self.handles
        )
        report.reverified_cleared = bool(cleared)

        all_pass = report.tests_passed == report.tests_total
        if not self.verifiable_by_rerun:
            # Pipeline fix: interim guard tests verify, but Layer 1+2 still sees the
            # structural failure until the pipeline change lands.
            report.verdict = MITIGATED if all_pass else FAILED
        else:
            report.verdict = VERIFIED if (all_pass and cleared) else FAILED
        return report

    # --- deterministic helpers --------------------------------------------
    def _apply(self, c: FixCandidate, record: CaptureRecord) -> _Applied:
        system = record.system_prompt
        if c.system_prompt_additions:
            system = (system + "\n\n" + c.system_prompt_additions).strip()
        chunks, scores = list(record.retrieved_chunks), list(record.similarity_scores)
        if c.max_chunks is not None:
            if scores and len(scores) == len(chunks):
                order = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)
                keep = sorted(order[: c.max_chunks])
                chunks = [chunks[i] for i in keep]
                scores = [scores[i] for i in keep]
            else:
                chunks = chunks[: c.max_chunks]
                scores = scores[: c.max_chunks]
        if c.chunk_char_budget is not None:
            # Stand-in for summarization: cap each kept chunk to the budget.
            chunks = [ch[: c.chunk_char_budget] for ch in chunks]
        temp = c.new_temperature if c.new_temperature is not None else record.temperature
        return _Applied(system_prompt=system, chunks=chunks, similarity_scores=scores, temperature=temp)

    def _run_test(self, t: TestCase, applied: _Applied, rerun: Rerun) -> TestResult:
        outputs, failures = [], []
        for _ in range(max(1, t.runs)):
            out = rerun(applied.system_prompt, t.input, applied.chunks, applied.temperature) or ""
            outputs.append(out)
            low = out.lower()
            for kw in t.must_contain:
                if kw.lower() not in low:
                    failures.append(f"missing '{kw}'")
            for kw in t.must_not_contain:
                if kw.lower() in low:
                    failures.append(f"contains '{kw}'")
        return TestResult(case=t, passed=not failures, outputs=outputs, failures=failures)

    def _rediagnose(self, record: CaptureRecord, applied: _Applied, rerun: Rerun) -> tuple[dict, str]:
        new_output = rerun(applied.system_prompt, record.user_prompt, applied.chunks, applied.temperature) or ""
        result = analyze(
            prompt=record.user_prompt,
            output=new_output,
            system_prompt=applied.system_prompt,
            chunks=applied.chunks,
            similarity_scores=applied.similarity_scores,
            temperature=applied.temperature,
            context_window=record.context_window,
            explain_with_llm=False,
        )
        return result, new_output

    def _diff(self, c: FixCandidate, record: CaptureRecord) -> str:
        lines: list[str] = []
        if c.system_prompt_additions:
            lines.append("--- system_prompt (appended)")
            for ln in c.system_prompt_additions.splitlines():
                lines.append("+ " + ln)
        if c.new_temperature is not None:
            lines.append(f"~ temperature: {record.temperature} -> {c.new_temperature}")
        if c.max_chunks is not None:
            lines.append(f"~ retrieved_chunks: {len(record.retrieved_chunks)} -> top {c.max_chunks} by similarity")
        for ex in c.few_shot_examples:
            lines.append(f"+ few-shot: {ex.get('input','')[:48]} -> {ex.get('output','')[:48]}")
        if c.notes:
            lines.append(f"# note: {c.notes}")
        return "\n".join(lines)

    # --- shared NER helper for test generation -----------------------------
    @staticmethod
    def _fabricated_entities(record: CaptureRecord) -> list[str]:
        """Entities in the output that are absent from the retrieved context."""
        out_ents = _extract_entities(record.llm_output)
        ctx = record.context_text.lower()
        return sorted(e for e in out_ents if e not in ctx)

    @staticmethod
    def _grounded_entities(record: CaptureRecord) -> list[str]:
        out_ents = _extract_entities(record.llm_output)
        ctx = record.context_text.lower()
        return sorted(e for e in out_ents if e in ctx)
