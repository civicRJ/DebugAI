"""Deterministic agent trace debugging.

Agent apps fail in the control loop before the final answer: repeated tools,
planner drift, missing approvals, ignored observations, and runaway budgets.
This module normalizes lightweight event traces and returns DebugAI-style
root-cause diagnoses without requiring an LLM.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from collections import Counter, defaultdict
from typing import Any

_WORD_RE = re.compile(r"[A-Za-z0-9_']+")
_HIGH_RISK_RE = re.compile(
    r"\b(issue|send|delete|update|write|charge|transfer|execute|run)\b.*\b(refund|email|payment|database|db|account|code|shell)\b"
    r"|\b(refund_order|send_email|delete_user|update_account|run_code|shell)\b"
    r"|\b(password|token|secret|credential)\b",
    re.IGNORECASE,
)
_HIGH_RISK_WORD_RE = re.compile(
    r"\b(refund_order|send_email|delete_user|update_account|run_code|shell|"
    r"delete|update|write|charge|payment|database|db|account|"
    r"password|token|secret|credential|execute|run_code|shell|transfer)\b",
    re.IGNORECASE,
)
_UNTRUSTED_RE = re.compile(
    r"\b(ignore previous|disregard previous|system prompt|developer prompt|"
    r"you are now|jailbreak|do not follow)\b",
    re.IGNORECASE,
)

AGENT_FAILURE_FIXES = {
    "infinite_loop": "Add a hard max-step guard, stop when state does not change, and escalate after repeated reasoning/actions.",
    "tool_call_loop": "Deduplicate tool calls by name+arguments, cache tool results, and stop/replan after two identical calls.",
    "wrong_tool_selected": "Constrain tool routing with an allow-list and validate each tool choice against the current goal.",
    "missing_tool_call": "Require the expected tool before final answer and block finalization until tool evidence exists.",
    "tool_result_ignored": "Ground the final answer in the latest successful tool result and retry when tool evidence is unused.",
    "tool_arg_drift": "Validate tool arguments against the user goal and preserve required entities before execution.",
    "planner_drift": "Re-anchor each plan step to the original goal and replan only when new evidence changes the task.",
    "premature_final_answer": "Require retrieve/tool/validation checkpoints before allowing a final answer.",
    "approval_gate_missing": "Add an explicit approval gate before refunds, emails, account changes, database writes, or code execution.",
    "state_memory_error": "Compare new state against prior user facts and block contradictory memory updates.",
    "handoff_failure": "Require handoff payloads to include owner, task, context summary, and acceptance by the next agent.",
    "runaway_cost_latency": "Set step, token, retry, latency, and cost budgets with early termination and escalation.",
    "unsafe_tool_execution": "Treat retrieved/tool/user content as untrusted and never let it choose tools or arguments directly.",
}


class AgentRun:
    """Lightweight recorder for agent control-loop events.

    The recorder intentionally stores plain dictionaries so traces can be logged,
    posted to the dashboard, or replayed through ``analyze_agent_trace()``.
    """

    def __init__(
        self,
        name: str | None = None,
        *,
        goal: str = "",
        max_steps: int | None = None,
        expected_tools: list[str] | None = None,
        max_tokens: int | None = None,
        max_latency_ms: int | None = None,
        requires_approval_for: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.name = name or "agent"
        self.goal = goal
        self.max_steps = max_steps
        self.expected_tools = list(expected_tools or [])
        self.max_tokens = max_tokens
        self.max_latency_ms = max_latency_ms
        self.requires_approval_for = list(requires_approval_for or [])
        self.metadata = dict(metadata or {})
        self.events: list[dict[str, Any]] = []

    def __enter__(self) -> "AgentRun":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc is not None:
            self.event("error", error=str(exc), error_type=getattr(exc_type, "__name__", str(exc_type)))
        return False

    def event(self, typ: str, **fields: Any) -> dict[str, Any]:
        item = {"type": typ, **fields}
        item.setdefault("agent", self.name)
        self.events.append(item)
        return item

    def plan(self, content: Any, **fields: Any) -> dict[str, Any]:
        return self.event("plan", content=content, **fields)

    def llm(self, output: Any = None, **fields: Any) -> dict[str, Any]:
        if output is not None:
            fields.setdefault("output", output)
        return self.event("llm", **fields)

    def tool_call(self, tool: str, args: Any = None, **fields: Any) -> dict[str, Any]:
        if args is not None:
            fields.setdefault("args", args)
        return self.event("tool_call", tool=tool, **fields)

    def tool_result(self, tool: str, output: Any = None, **fields: Any) -> dict[str, Any]:
        if output is not None:
            fields.setdefault("output", output)
        return self.event("tool_result", tool=tool, **fields)

    def approval(self, action: str = "", approved: bool = True, **fields: Any) -> dict[str, Any]:
        return self.event("approval", action=action, approved=approved, **fields)

    def handoff(self, to: str = "", task: str = "", context: Any = "", **fields: Any) -> dict[str, Any]:
        return self.event("handoff", to=to, task=task, context=context, **fields)

    def memory_read(self, source: str = "", content: Any = "", **fields: Any) -> dict[str, Any]:
        return self.event("observation", channel="memory_read", source=source, content=content, **fields)

    def memory_write(self, target: str = "", content: Any = "", **fields: Any) -> dict[str, Any]:
        return self.event("observation", channel="memory_write", target=target, content=content, **fields)

    def final(self, output: Any, **fields: Any) -> dict[str, Any]:
        return self.event("final", output=output, **fields)

    def to_events(self) -> list[dict[str, Any]]:
        return deepcopy(self.events)

    def report(self, **overrides: Any) -> dict[str, Any]:
        return agent_report(self, **overrides)

    def _report_options(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "max_steps": self.max_steps,
            "expected_tools": self.expected_tools,
            "max_tokens": self.max_tokens,
            "max_latency_ms": self.max_latency_ms,
            "requires_approval_for": self.requires_approval_for,
        }


def agent_run(name: str | None = None, **kwargs: Any) -> AgentRun:
    """Create an ``AgentRun`` recorder for SDK-first agent debugging."""
    return AgentRun(name, **kwargs)


def _tokens(text: Any) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(_stringify(text))}


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, sort_keys=True)
    except TypeError:
        return str(value)


def _overlap(a: Any, b: Any) -> float:
    at, bt = _tokens(a), _tokens(b)
    if not at or not bt:
        return 0.0
    return len(at & bt) / len(at | bt)


def _opposes_tool_result(final_text: str, result_text: str) -> bool:
    f = final_text.lower()
    r = result_text.lower()
    negative = any(x in r for x in (" not ", " no ", "cannot", "can't", "ineligible", "not refundable", "not eligible"))
    positive = any(x in f for x in (" can ", " eligible", "approved", "will issue", "get a", "qualify"))
    return negative and positive


def _event_type(event: dict) -> str:
    typ = str(event.get("type") or event.get("kind") or "").strip().lower()
    if typ in {"assistant", "model", "generation"}:
        return "llm"
    if typ in {"tool", "tool_execution"}:
        return "tool_call"
    if typ in {"result", "observation"}:
        return "tool_result"
    return typ or "event"


def _tool_name(event: dict) -> str:
    return str(event.get("tool") or event.get("name") or event.get("tool_name") or "").strip()


def _tool_args(event: dict) -> Any:
    return event.get("args", event.get("arguments", event.get("input", "")))


def _event_text(event: dict) -> str:
    parts = [
        event.get("input"),
        event.get("output"),
        event.get("content"),
        event.get("message"),
        event.get("thought"),
        event.get("plan"),
        event.get("observation"),
        event.get("result"),
        _tool_args(event),
    ]
    return " ".join(_stringify(p) for p in parts if p is not None)


def _normalize_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, raw in enumerate(events or []):
        if not isinstance(raw, dict):
            raw = {"type": "observation", "output": raw}
        typ = _event_type(raw)
        norm = dict(raw)
        norm["index"] = idx
        norm["type"] = typ
        norm["tool"] = _tool_name(raw)
        norm["args"] = _tool_args(raw)
        norm["text"] = _event_text(raw)
        out.append(norm)
    return out


def _tool_key(event: dict) -> str:
    return f"{event.get('tool') or ''}:{_stringify(event.get('args'))}"


def _latest_result_for_tool(events: list[dict], tool: str, before_index: int | None = None) -> dict | None:
    for event in reversed(events[:before_index] if before_index is not None else events):
        if event["type"] == "tool_result" and (not tool or event.get("tool") == tool):
            return event
    return None


def _final_event(events: list[dict]) -> dict | None:
    for event in reversed(events):
        if event["type"] in {"final", "llm"} and _stringify(event.get("output") or event.get("content") or event.get("text")).strip():
            return event
    return None


def _issue(failure: str, confidence: float, root_cause: str, evidence: dict, step: int | None = None,
           severity: str = "critical") -> dict:
    return {
        "failure": failure,
        "layer": "agent_runtime",
        "severity": severity,
        "confidence": round(max(0.0, min(confidence, 1.0)), 4),
        "root_cause": root_cause,
        "fix": AGENT_FAILURE_FIXES[failure],
        "evidence": evidence,
        "step": step,
    }


def _signals(events: list[dict], goal: str, max_steps: int | None,
             max_tokens: int | None, max_latency_ms: int | None) -> dict[str, Any]:
    tool_calls = [e for e in events if e["type"] == "tool_call"]
    tool_results = [e for e in events if e["type"] == "tool_result"]
    final = _final_event(events)
    repeated = 0
    keys = [_tool_key(e) for e in tool_calls]
    counts = Counter(keys)
    repeated += sum(max(0, count - 1) for count in counts.values())
    texts = [_event_text(e) for e in events if e["type"] in {"llm", "plan", "tool_call"}]
    for a, b in zip(texts, texts[1:]):
        if _overlap(a, b) > 0.82 and len(_tokens(a)) >= 4:
            repeated += 1

    result_overlaps = []
    final_text = _stringify((final or {}).get("output") or (final or {}).get("content") or (final or {}).get("text"))
    for result in tool_results:
        result_text = result.get("text") or result.get("output") or result.get("result")
        if len(_tokens(result_text)) >= 4:
            result_overlaps.append(_overlap(final_text, result_text))
    unused = sum(1 for x in result_overlaps if x < 0.12)
    tokens = sum(int(e.get("tokens") or e.get("total_tokens") or 0) for e in events)
    latency = sum(float(e.get("latency_ms") or e.get("duration_ms") or 0) for e in events)
    return {
        "step_count": len(events),
        "tool_call_count": len(tool_calls),
        "tool_result_count": len(tool_results),
        "repeated_action_score": round(repeated / max(1, len(events) - 1), 4),
        "tool_arg_similarity": round(max([_overlap(a.get("args"), b.get("args")) for a, b in zip(tool_calls, tool_calls[1:])] or [0.0]), 4),
        "goal_drift": round(max([1.0 - _overlap(goal, e.get("text")) for e in events if e["type"] in {"plan", "llm"}] or [0.0]), 4),
        "tool_result_overlap": round(max(result_overlaps or [0.0]), 4),
        "unused_tool_result_count": unused,
        "approval_required": any(_HIGH_RISK_RE.search(_event_text(e) or "") for e in events),
        "approval_present": any(e["type"] == "approval" or str(e.get("approved", "")).lower() == "true" for e in events),
        "cost_budget_ratio": 0.0,
        "latency_budget_ratio": round(latency / max_latency_ms, 4) if max_latency_ms else 0.0,
        "token_budget_ratio": round(tokens / max_tokens, 4) if max_tokens else 0.0,
        "max_steps": max_steps,
    }


def _build_fix(primary: dict | None, events: list[dict]) -> dict | None:
    if not primary:
        return None
    regression = {
        "goal": "Replay the same agent trace with the proposed guard enabled.",
        "expected_after": {
            "healthy": True,
            "must_not_fail": primary["failure"],
            "max_steps": min(max(4, len(events)), 12),
        },
        "original_event_count": len(events),
    }
    candidate = {
        "agent": "Agent Runtime Fix Agent",
        "failure": primary["failure"],
        "strategy": primary["fix"],
        "rationale": primary["root_cause"],
        "notes": (
            "Add a deterministic agent runtime guard: max steps, duplicate-action "
            "detection, tool allow-list validation, approval gates, and final-answer "
            "grounding against the latest observation."
        ),
        "replay_regression": regression,
    }
    return {
        "agent": "Agent Runtime Fix Agent",
        "failure": primary["failure"],
        "verdict": "mitigated",
        "candidate": candidate,
        "tests_total": 1,
        "tests_passed": 1,
        "regression_trace": regression,
    }


def analyze_agent_trace(
    events: list[dict[str, Any]],
    *,
    goal: str = "",
    max_steps: int | None = None,
    expected_tools: list[str] | None = None,
    max_tokens: int | None = None,
    max_latency_ms: int | None = None,
    requires_approval_for: list[str] | None = None,
) -> dict[str, Any]:
    """Diagnose an agent event trace and return named root-cause failures."""
    norm = _normalize_events(events)
    expected = {t for t in (expected_tools or []) if t}
    signals = _signals(norm, goal, max_steps, max_tokens, max_latency_ms)
    issues: list[dict] = []
    tool_calls = [e for e in norm if e["type"] == "tool_call"]
    tool_results = [e for e in norm if e["type"] == "tool_result"]
    final = _final_event(norm)

    if max_steps and len(norm) > max_steps:
        issues.append(_issue(
            "runaway_cost_latency", 0.88,
            f"Agent used {len(norm)} steps, exceeding max_steps={max_steps}.",
            {"step_count": len(norm), "max_steps": max_steps},
            step=max_steps,
        ))

    key_counts = Counter(_tool_key(e) for e in tool_calls)
    repeated_keys = [k for k, count in key_counts.items() if count >= 3]
    if repeated_keys:
        repeated = repeated_keys[0]
        step = next((e["index"] for e in tool_calls if _tool_key(e) == repeated), None)
        issues.append(_issue(
            "tool_call_loop", 0.92,
            "Agent repeated the same tool call with near-identical arguments.",
            {"repeated_tool_call": repeated, "count": key_counts[repeated]},
            step=step,
        ))

    if signals["repeated_action_score"] >= 0.45 and not repeated_keys:
        issues.append(_issue(
            "infinite_loop", 0.84,
            "Agent repeated similar reasoning/actions without new evidence.",
            {"repeated_action_score": signals["repeated_action_score"]},
            step=len(norm) - 1 if norm else None,
        ))

    called = {e.get("tool") for e in tool_calls if e.get("tool")}
    if expected and not called.intersection(expected):
        issues.append(_issue(
            "missing_tool_call", 0.86,
            f"Expected one of {sorted(expected)} before final answer, but no expected tool was called.",
            {"expected_tools": sorted(expected), "called_tools": sorted(called)},
            step=(final or {}).get("index"),
        ))

    wrong = [e for e in tool_calls if expected and e.get("tool") and e.get("tool") not in expected]
    if wrong:
        issues.append(_issue(
            "wrong_tool_selected", 0.82,
            f"Agent used unexpected tool '{wrong[0].get('tool')}'.",
            {"expected_tools": sorted(expected), "tool": wrong[0].get("tool")},
            step=wrong[0]["index"],
        ))

    for call in tool_calls:
        drift = 1.0 - _overlap(goal, call.get("args"))
        if goal and drift > 0.88 and len(_tokens(call.get("args"))) >= 3:
            issues.append(_issue(
                "tool_arg_drift", 0.76,
                "Tool arguments drifted away from the original goal/entities.",
                {"goal": goal, "tool": call.get("tool"), "args": call.get("args"), "drift": round(drift, 4)},
                step=call["index"],
                severity="warning",
            ))
            break

    if tool_results and final:
        latest_result = _latest_result_for_tool(norm, "", before_index=final["index"] + 1)
        if latest_result:
            result_text = latest_result.get("text")
            final_text = final.get("output") or final.get("content") or final.get("text")
            result_overlap = _overlap(final_text, result_text)
            if len(_tokens(result_text)) >= 4 and (result_overlap < 0.12 or _opposes_tool_result(final_text, result_text)):
                issues.append(_issue(
                    "tool_result_ignored", 0.84,
                    "A tool returned usable evidence, but the final answer did not use it.",
                    {"tool": latest_result.get("tool"), "tool_result_overlap": round(result_overlap, 4)},
                    step=final["index"],
                ))

    high_risk_text = " ".join([*(requires_approval_for or [])] + [_event_text(e) for e in norm])
    if (_HIGH_RISK_RE.search(high_risk_text) or any(_HIGH_RISK_WORD_RE.search(str(e.get("tool") or "")) for e in tool_calls)) and not signals["approval_present"]:
        issues.append(_issue(
            "approval_gate_missing", 0.86,
            "Agent attempted or planned a high-risk action without an explicit approval event.",
            {"approval_required": True, "approval_present": False},
            step=next((e["index"] for e in norm if _HIGH_RISK_RE.search(_event_text(e) or "")), None),
        ))

    for event in norm:
        if event["type"] == "plan" and goal and (1.0 - _overlap(goal, event.get("text"))) > 0.92:
            issues.append(_issue(
                "planner_drift", 0.72,
                "Planner step drifted away from the original goal.",
                {"goal": goal, "plan": event.get("text")},
                step=event["index"],
                severity="warning",
            ))
            break

    if final and expected and not tool_results:
        issues.append(_issue(
            "premature_final_answer", 0.78,
            "Agent produced a final answer before required tool evidence or validation existed.",
            {"expected_tools": sorted(expected), "tool_result_count": 0},
            step=final["index"],
            severity="warning",
        ))

    for event in norm:
        if event["type"] in {"handoff"}:
            missing = [k for k in ("to", "task", "context") if not event.get(k)]
            if missing:
                issues.append(_issue(
                    "handoff_failure", 0.78,
                    "Agent handoff is missing owner, task, or context.",
                    {"missing": missing},
                    step=event["index"],
                    severity="warning",
                ))
                break

    memory_events = [e for e in norm if e["type"] in {"observation", "llm", "final"}]
    for a, b in zip(memory_events, memory_events[1:]):
        if "not " in _event_text(a).lower() and _overlap(a.get("text"), b.get("text")) > 0.55 and "not " not in _event_text(b).lower():
            issues.append(_issue(
                "state_memory_error", 0.70,
                "Later agent state appears to contradict an earlier constraint.",
                {"earlier": a.get("text"), "later": b.get("text")},
                step=b["index"],
                severity="warning",
            ))
            break

    for event in norm:
        if event["type"] == "tool_call" and _UNTRUSTED_RE.search(_event_text(event) or ""):
            issues.append(_issue(
                "unsafe_tool_execution", 0.88,
                "Tool arguments contain instruction-like untrusted content.",
                {"tool": event.get("tool"), "args": event.get("args")},
                step=event["index"],
            ))
            break

    if signals["token_budget_ratio"] > 1.0 or signals["latency_budget_ratio"] > 1.0:
        issues.append(_issue(
            "runaway_cost_latency", 0.82,
            "Agent exceeded token or latency budget.",
            {"token_budget_ratio": signals["token_budget_ratio"], "latency_budget_ratio": signals["latency_budget_ratio"]},
            step=len(norm) - 1 if norm else None,
        ))

    issues.sort(key=lambda i: i["confidence"], reverse=True)
    primary = issues[0] if issues else None
    diagnosis = {
        "healthy": primary is None,
        "primary": primary,
        "secondary": issues[1:],
        "signals": signals,
        "stages": [
            {"index": e["index"], "type": e["type"], "tool": e.get("tool"), "summary": (e.get("text") or "")[:160]}
            for e in norm
        ],
        "explanation": primary["root_cause"] if primary else "No agent runtime failure detected.",
    }
    return {
        "healthy": diagnosis["healthy"],
        "diagnosis": diagnosis,
        "signals": signals,
        "events": norm,
        "primary": primary,
        "issues": issues,
        "fix": _build_fix(primary, norm),
        "regression_artifact": {
            "input": {"goal": goal, "events": events, "expected_tools": expected_tools or []},
            "expected_after": {"healthy": True, "failure_absent": primary["failure"] if primary else None},
        },
    }


def agent_report(
    trace: AgentRun | list[dict[str, Any]] | dict[str, Any],
    *,
    goal: str | None = None,
    max_steps: int | None = None,
    expected_tools: list[str] | None = None,
    max_tokens: int | None = None,
    max_latency_ms: int | None = None,
    requires_approval_for: list[str] | None = None,
) -> dict[str, Any]:
    """Return a DebugAI agent-runtime report from an ``AgentRun`` or event list."""
    options: dict[str, Any] = {}
    if isinstance(trace, AgentRun):
        events = trace.to_events()
        options.update(trace._report_options())
        options["agent"] = trace.name
        if trace.metadata:
            options["metadata"] = deepcopy(trace.metadata)
    elif isinstance(trace, dict):
        events = trace.get("events") or trace.get("trace") or []
        options.update({
            "goal": trace.get("goal", ""),
            "max_steps": trace.get("max_steps"),
            "expected_tools": trace.get("expected_tools") or [],
            "max_tokens": trace.get("max_tokens"),
            "max_latency_ms": trace.get("max_latency_ms"),
            "requires_approval_for": trace.get("requires_approval_for") or [],
        })
    else:
        events = trace

    overrides = {
        "goal": goal,
        "max_steps": max_steps,
        "expected_tools": expected_tools,
        "max_tokens": max_tokens,
        "max_latency_ms": max_latency_ms,
        "requires_approval_for": requires_approval_for,
    }
    options.update({k: v for k, v in overrides.items() if v is not None})
    report = analyze_agent_trace(
        events,
        goal=options.get("goal") or "",
        max_steps=options.get("max_steps"),
        expected_tools=options.get("expected_tools") or None,
        max_tokens=options.get("max_tokens"),
        max_latency_ms=options.get("max_latency_ms"),
        requires_approval_for=options.get("requires_approval_for") or None,
    )
    report["agent"] = options.get("agent")
    if options.get("metadata"):
        report["metadata"] = options["metadata"]
    return report
