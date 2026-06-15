"""Instruction-adherence judge — diagnoses *behavioural* / prompt-following
failures that the deterministic grounding signals can't see.

Some failures aren't about retrieval or hallucination at all — e.g. a Socratic
tutor that reveals the answer in the first turn or re-asks the same guiding
question. These are violations of the system prompt's own rules. We detect them
with an LLM-as-judge (OpenAI by default), with a deterministic heuristic
fallback so the feature still works without an API key.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field

log = logging.getLogger("debugai.judge")

INSTRUCTION_VIOLATION = "instruction_violation"
DEFAULT_JUDGE_MODEL = os.environ.get("DEBUGAI_JUDGE_MODEL", "gpt-5.5")

_SENT_RE = re.compile(r"[.!?]+")
_WORD_RE = re.compile(r"[A-Za-z0-9']+")


@dataclass
class Violation:
    rule: str
    severity: str = "warning"   # warning | critical
    evidence: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class InstructionDiagnosis:
    healthy: bool
    confidence: float
    violations: list[Violation] = field(default_factory=list)
    model: str = "heuristic"

    def to_dict(self) -> dict:
        return {
            "healthy": self.healthy,
            "confidence": self.confidence,
            "model": self.model,
            "violations": [v.to_dict() for v in self.violations],
        }


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def judge_instructions(system_prompt: str, user_prompt: str, output: str,
                       model: str | None = None,
                       api_key: str | None = None) -> InstructionDiagnosis:
    """Evaluate an assistant ``output`` against the rules in its ``system_prompt``.

    Uses the OpenAI judge when an api_key is provided. Passing api_key=None
    allows the SDK/local CLI env fallback; passing "" disables env fallback."""
    if not (system_prompt or "").strip():
        return InstructionDiagnosis(healthy=True, confidence=0.0, model="n/a")
    model = model or DEFAULT_JUDGE_MODEL
    effective_key = os.environ.get("OPENAI_API_KEY") if api_key is None else api_key
    if effective_key:
        try:
            return _openai_judge(system_prompt, user_prompt, output, model,
                                 api_key=effective_key)
        except Exception as e:  # pragma: no cover - network dependent
            log.warning("OpenAI judge failed (%s); using heuristic fallback", e)
    return _heuristic_judge(system_prompt, user_prompt, output)


# --------------------------------------------------------------------------- #
# LLM-as-judge (OpenAI)
# --------------------------------------------------------------------------- #
_JUDGE_SYSTEM = (
    "You are a strict evaluator of an AI assistant's adherence to its own system "
    "prompt. You are given the assistant's SYSTEM PROMPT (which contains its rules) "
    "and the assistant's RESPONSE to a student. Identify every rule the response "
    "violates — especially pedagogy rules such as revealing too much of the answer "
    "early, asking more than one question, asking a question that merely restates a "
    "previous one, or paraphrasing the student. Respond ONLY as JSON: "
    '{"violations": [{"rule": "<short rule description>", "severity": '
    '"critical|warning", "evidence": "<quote/why>"}], "confidence": <0..1>}. '
    "If the response fully complies, return an empty violations list."
)


def _openai_judge(system_prompt: str, user_prompt: str, output: str,
                  model: str, api_key: str | None = None) -> InstructionDiagnosis:
    from openai import OpenAI

    effective_key = os.environ.get("OPENAI_API_KEY") if api_key is None else api_key
    client = OpenAI(api_key=effective_key,
                    timeout=30.0, max_retries=2)
    payload = (
        f"SYSTEM PROMPT (rules):\n{system_prompt}\n\n"
        f"STUDENT MESSAGE:\n{user_prompt}\n\n"
        f"ASSISTANT RESPONSE:\n{output}"
    )
    resp = client.chat.completions.create(
        model=model,
        response_format={"type": "json_object"},
        messages=[{"role": "system", "content": _JUDGE_SYSTEM},
                  {"role": "user", "content": payload}],
    )
    data = json.loads(resp.choices[0].message.content or "{}")
    violations = [
        Violation(rule=v.get("rule", "rule"), severity=v.get("severity", "warning"),
                  evidence=v.get("evidence", ""))
        for v in data.get("violations", [])
    ]
    conf = float(data.get("confidence", 0.8 if violations else 0.0))
    return InstructionDiagnosis(
        healthy=not violations, confidence=round(conf, 4),
        violations=violations, model=f"openai:{model}",
    )


# --------------------------------------------------------------------------- #
# Deterministic heuristic fallback (no API key)
# --------------------------------------------------------------------------- #
def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_RE.split(text or "") if s.strip()]


def _jaccard(a: str, b: str) -> float:
    sa = {w.lower() for w in _WORD_RE.findall(a or "")}
    sb = {w.lower() for w in _WORD_RE.findall(b or "")}
    return len(sa & sb) / len(sa | sb) if (sa or sb) else 0.0


def _heuristic_judge(system_prompt: str, user_prompt: str, output: str) -> InstructionDiagnosis:
    """Catches the most common Socratic-tutor violations without an LLM.

    These map to typical rules: exactly one question, don't reveal the answer
    early, don't open by paraphrasing the student."""
    sysl = (system_prompt or "").lower()
    violations: list[Violation] = []
    qn = (output or "").count("?")
    words = _WORD_RE.findall(output or "")

    # Rule: exactly one leading question.
    if "one question" in sysl or "socratic" in sysl or "leading question" in sysl:
        if qn == 0:
            violations.append(Violation("No leading question — the turn should advance with one question.",
                                        "critical", "0 question marks in the response."))
        elif qn > 1:
            violations.append(Violation("More than one question in a single turn.",
                                        "warning", f"{qn} question marks found."))

    # Rule: don't reveal the full solution in the first response (length/declarative heuristic).
    if "socratic" in sysl or "do not give away" in sysl or "not give away" in sysl or "leading question" in sysl:
        declarative = [s for s in _sentences(output) if "?" not in s]
        decl_words = sum(len(_WORD_RE.findall(s)) for s in declarative)
        if len(words) > 90 or decl_words > 70:
            violations.append(Violation("Reveals too much — long explanation given before the student reasons.",
                                        "critical", f"{decl_words} words of explanation before the question."))

    # Rule: never open by paraphrasing the student.
    first = _sentences(output)[0] if _sentences(output) else ""
    if first and _jaccard(first, user_prompt) > 0.5:
        violations.append(Violation("Opens by paraphrasing the student's message.",
                                    "warning", "First sentence closely mirrors the student input."))

    # Confidence scales with count + severity.
    if not violations:
        return InstructionDiagnosis(healthy=True, confidence=0.0, model="heuristic")
    crit = sum(1 for v in violations if v.severity == "critical")
    conf = min(0.6 + 0.15 * len(violations) + 0.1 * crit, 0.95)
    return InstructionDiagnosis(healthy=False, confidence=round(conf, 4),
                                violations=violations, model="heuristic")
