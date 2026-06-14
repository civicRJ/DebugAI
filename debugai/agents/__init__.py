"""Fix Agent Framework (Architecture §8) — diagnose → fix → verify → review."""

from __future__ import annotations

from debugai.agents.base import FixAgent
from debugai.agents.builtin import (
    AmbiguityGateAgent, CitationVerifierAgent, ConstraintAgent, ContextOptimizerAgent,
    DocumentPatchAgent, KnowledgeBaseAgent, PromptRuleAgent, SchemaRepairAgent,
    SocraticTutorAgent, ToolContractAgent,
)
from debugai.agents.registry import FixAgentRegistry
from debugai.agents.types import (
    ESCALATED, FAILED, MITIGATED, PENDING_RERUN, VERIFIED,
    FixCandidate, FixReport, TestCase, TestResult,
)
from debugai.schema import CaptureRecord

# A process-wide default registry with the built-ins.
DEFAULT_REGISTRY = FixAgentRegistry()


def propose_fix(diagnosis: dict, record: CaptureRecord, rerun=None,
                registry: FixAgentRegistry | None = None) -> FixReport | None:
    """Select the right agent for a diagnosis and run the fix-verify loop.

    Returns a FixReport, or None if no agent handles the failure (or the
    request is healthy).
    """
    if not diagnosis or diagnosis.get("healthy"):
        return None
    reg = registry or DEFAULT_REGISTRY
    agent = reg.find_agent(diagnosis)
    if agent is None:
        return None
    return agent.run(diagnosis, record, rerun=rerun)


__all__ = [
    "FixAgent", "FixAgentRegistry", "DEFAULT_REGISTRY", "propose_fix",
    "FixCandidate", "FixReport", "TestCase", "TestResult",
    "PromptRuleAgent", "KnowledgeBaseAgent", "ConstraintAgent",
    "ContextOptimizerAgent", "DocumentPatchAgent", "SocraticTutorAgent",
    "SchemaRepairAgent", "ToolContractAgent", "CitationVerifierAgent",
    "AmbiguityGateAgent",
    "VERIFIED", "MITIGATED", "FAILED", "PENDING_RERUN", "ESCALATED",
]
