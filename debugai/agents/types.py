"""Data types for the Fix Agent Framework (Architecture §8)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Verdicts for a fix attempt.
VERIFIED = "verified"          # tests pass AND re-diagnosis clears the failure
MITIGATED = "mitigated"        # interim guard verified, but full fix needs a pipeline change
FAILED = "failed"             # fix did not clear the failure / tests failed
PENDING_RERUN = "pending_rerun"  # candidate + tests produced, but no model to verify
ESCALATED = "escalated"        # agent declined to auto-fix; flagged for a human


@dataclass
class FixCandidate:
    """A candidate fix produced by an agent. The modifications are applied
    deterministically by the loop before re-running the model."""

    agent: str
    failure: str
    strategy: str
    rationale: str = ""
    # Modifications (any subset applies):
    system_prompt_additions: str = ""
    new_temperature: float | None = None
    max_chunks: int | None = None
    chunk_char_budget: int | None = None   # summarize/truncate each kept chunk
    few_shot_examples: list[dict] = field(default_factory=list)
    # Advisory output (not auto-applied):
    notes: str = ""
    escalate: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TestCase:
    """One deterministic regression check (§8.4)."""

    __test__ = False  # not a pytest test class

    input: str
    must_contain: list[str] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)
    category: str = "regression"   # original | edge | regression | variance
    runs: int = 1                  # variance checks run 3x

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TestResult:
    __test__ = False  # not a pytest test class

    case: TestCase
    passed: bool
    outputs: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "input": self.case.input,
            "category": self.case.category,
            "runs": self.case.runs,
            "passed": self.passed,
            "failures": self.failures,
            "must_contain": self.case.must_contain,
            "must_not_contain": self.case.must_not_contain,
        }


@dataclass
class FixReport:
    """The full diagnose-fix-verify report presented for developer review (§8.1)."""

    agent: str
    failure: str
    verdict: str
    candidate: FixCandidate
    diff: str = ""
    test_results: list[TestResult] = field(default_factory=list)
    tests_passed: int = 0
    tests_total: int = 0
    reverified: bool = False
    reverified_cleared: bool | None = None
    before_confidence: float | None = None
    after_diagnosis: dict | None = None
    after_output: str | None = None

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "failure": self.failure,
            "verdict": self.verdict,
            "candidate": self.candidate.to_dict(),
            "diff": self.diff,
            "tests_passed": self.tests_passed,
            "tests_total": self.tests_total,
            "test_results": [t.to_dict() for t in self.test_results],
            "reverified": self.reverified,
            "reverified_cleared": self.reverified_cleared,
            "before_confidence": self.before_confidence,
            "after_diagnosis": self.after_diagnosis,
            "after_output": self.after_output,
        }
