"""Curated failure examples for SDK demos, tests, and onboarding."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


EXAMPLES: dict[str, dict[str, Any]] = {
    "rag_hallucination": {
        "title": "RAG hallucination",
        "description": "Retriever found relevant policy text, but the answer invented unsupported details.",
        "case": {
            "prompt": "What is the refund policy for opened electronics?",
            "system_prompt": "Answer only from the retrieved context and cite the source.",
            "output": (
                "Opened electronics can be returned within 90 days for a full cash refund, "
                "and Galaxy-brand items get a special 1-year no-questions guarantee."
            ),
            "chunks": [
                "Returns: most items may be returned within 30 days with a receipt.",
                "Software and electronics follow the standard 30-day return window when unopened.",
            ],
            "similarity_scores": [0.71, 0.66],
            "temperature": 0.7,
        },
    },
    "retrieval_failure": {
        "title": "Irrelevant retrieval",
        "description": "The model answered a policy question from unrelated retrieved chunks.",
        "case": {
            "prompt": "What is the refund policy for electronics?",
            "output": "Electronics can be returned within 90 days for a full cash refund.",
            "chunks": ["Our store hours are 9am to 5pm.", "Parking is behind the building."],
            "similarity_scores": [0.42, 0.40],
            "temperature": 0.2,
        },
    },
    "schema_violation": {
        "title": "Schema violation",
        "description": "The app expected strict JSON, but the model returned a broken contract.",
        "case": {
            "prompt": "Classify this ticket and return JSON.",
            "output": '{"status": "maybe", "priority": 5}',
            "response_schema": {
                "type": "object",
                "required": ["status", "answer"],
                "properties": {
                    "status": {"type": "string", "enum": ["ok", "error"]},
                    "answer": {"type": "string"},
                },
            },
        },
    },
    "tool_call_failure": {
        "title": "Tool call failure",
        "description": "A freshness-sensitive request had an available search tool, but no tool call happened.",
        "case": {
            "prompt": "Search for the current shipping cutoff and answer the customer.",
            "system_prompt": "Use the search tool for current shipping cutoffs.",
            "output": "The cutoff is 5pm today.",
            "tools_expected": ["search"],
            "tool_calls": [],
        },
    },
    "citation_failure": {
        "title": "Citation failure",
        "description": "The prompt required citations, but the answer referenced a chunk that was not retrieved.",
        "case": {
            "prompt": "Answer with citations: what is the return window?",
            "system_prompt": "Cite every factual claim with retrieved chunk numbers.",
            "output": "The return window is 30 days [3].",
            "chunks": ["Returns are available within 30 days with a receipt."],
            "similarity_scores": [0.91],
        },
    },
    "ambiguous_prompt": {
        "title": "Ambiguous prompt",
        "description": "The user request is underspecified, but the model answered instead of clarifying.",
        "case": {
            "prompt": "Can you do it?",
            "output": " ".join(
                ["I will proceed with the requested task using reasonable assumptions"] * 4
            ),
        },
    },
}


def list_examples() -> list[dict[str, str]]:
    """Return example metadata without mutating the underlying cases."""
    return [
        {"id": key, "title": value["title"], "description": value["description"]}
        for key, value in EXAMPLES.items()
    ]


def get_example(example_id: str) -> dict[str, Any]:
    """Return a deep copy of one example case by id."""
    if example_id not in EXAMPLES:
        known = ", ".join(EXAMPLES)
        raise KeyError(f"unknown example {example_id!r}; expected one of: {known}")
    value = EXAMPLES[example_id]
    return {
        "id": example_id,
        "title": value["title"],
        "description": value["description"],
        "case": deepcopy(value["case"]),
    }


def example_cases() -> list[dict[str, Any]]:
    """Return all example cases as labeled case dictionaries."""
    out: list[dict[str, Any]] = []
    for item in list_examples():
        ex = get_example(item["id"])
        case = ex["case"]
        case["label"] = ex["title"]
        case["id"] = ex["id"]
        out.append(case)
    return out
