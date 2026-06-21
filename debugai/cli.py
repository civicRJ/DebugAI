"""DebugAI command-line interface.

    debugai analyze --prompt "..." --output "..." --chunk "..." --score 0.4
    debugai diagnose cases.json
    debugai fix cases.json --simulate
    debugai audit-prompt --system @prompt.txt --use-case "support RAG bot"
    debugai serve --port 8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from debugai import analyze, agent_report, analyze_pipeline, audit_prompt, evaluate_corpus_file
from debugai.agents import propose_fix
from debugai.examples import example_cases, get_example, list_examples
from debugai.report import (
    analyze_kwargs, capture_record_from_case, debug_report, format_debug_report,
)

_ANSI = {"red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
         "dim": "\033[2m", "bold": "\033[1m", "reset": "\033[0m"}


def _c(text: str, color: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{_ANSI[color]}{text}{_ANSI['reset']}"


def _grounded_stub(system_prompt, user_prompt, chunks, temperature):
    ctx = " ".join(chunks)
    return ("Per the provided context: " + ctx) if ctx else "I don't have that information."


def _case_kwargs(case: dict) -> dict:
    return analyze_kwargs(case)


def _json_arg(value: str | None):
    if not value:
        return None
    raw = value.strip()
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text()
    return json.loads(raw)


def _text_arg(value: str | None) -> str:
    if not value:
        return ""
    raw = value.strip()
    if raw.startswith("@"):
        return Path(raw[1:]).read_text()
    return value


def _print_diagnosis(diag: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(diag, indent=2))
        return
    if diag.get("healthy"):
        print(_c("✓ healthy", "green") + " — no failure detected")
        return
    p = diag["primary"]
    color = "red" if p["severity"] == "critical" else "yellow"
    print(_c(f"✗ {p['failure']}", color) + f"  conf {p['confidence']}  ({p['severity']})")
    print("  " + p["root_cause"])
    print(_c("  fix: ", "dim") + p["fix"])
    if diag.get("secondary"):
        print(_c("  secondary: ", "dim") + ", ".join(s["failure"] for s in diag["secondary"]))


def _load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "cases" in data:
        return [{k: v for k, v in c.items() if k not in ("id", "expected", "_comment")}
                for c in data["cases"]]
    if isinstance(data, list):
        return data
    return [data]


# --------------------------------------------------------------------------- #
def cmd_analyze(args) -> int:
    diag = analyze(
        prompt=args.prompt, output=args.output, system_prompt=args.system or "",
        chunks=args.chunk or None, similarity_scores=args.score or None,
        temperature=args.temperature, context_window=args.context_window,
        tools_expected=args.tool_expected or None,
        tool_calls=[_json_arg(x) for x in (args.tool_call_json or [])] or None,
        response_schema=_json_arg(args.schema_json),
        explain_with_llm=args.explain,
    )
    _print_diagnosis(diag, args.json)
    return 0


def cmd_diagnose(args) -> int:
    cases = _load_cases(Path(args.file))
    results = []
    for c in cases:
        diag = analyze(explain_with_llm=False, **_case_kwargs(c))
        results.append(diag)
        if not args.json:
            label = c.get("label") or (c.get("prompt", "")[:48])
            print(_c(label, "bold"))
            _print_diagnosis(diag, False)
            print()
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        failing = sum(0 if r["healthy"] else 1 for r in results)
        print(_c(f"{failing}/{len(results)} failing", "dim"))
    return 0


def cmd_fix(args) -> int:
    cases = _load_cases(Path(args.file))
    rerun = _grounded_stub if args.simulate else None
    for c in cases:
        kw = _case_kwargs(c)
        diag = analyze(explain_with_llm=False, **kw)
        rec = capture_record_from_case(kw)
        report = propose_fix(diag, rec, rerun=rerun)
        label = c.get("label") or kw.get("prompt", "")[:48]
        print(_c(label, "bold"))
        if report is None:
            print("  healthy / no agent\n")
            continue
        vcolor = {"verified": "green", "mitigated": "yellow", "escalated": "yellow",
                  "failed": "red", "pending_rerun": "dim"}.get(report.verdict, "dim")
        print(f"  {report.agent} → " + _c(report.verdict, vcolor) +
              f"  tests {report.tests_passed}/{report.tests_total}")
        if report.diff:
            print(_c("  " + report.diff.replace("\n", "\n  "), "dim"))
        print()
    return 0


def cmd_report(args) -> int:
    if args.example:
        cases = [get_example(args.example)["case"]]
    else:
        if not args.file:
            raise SystemExit("debugai report requires a file or --example")
        cases = _load_cases(Path(args.file))
    rerun = _grounded_stub if args.simulate else None
    reports = [debug_report(rerun=rerun, **_case_kwargs(c)) for c in cases]
    if args.json:
        print(json.dumps(reports, indent=2))
        return 0
    for i, report in enumerate(reports):
        label = cases[i].get("label") or cases[i].get("id") or cases[i].get("prompt", "")[:48]
        print(_c(str(label), "bold"))
        print(format_debug_report(report))
        print()
    return 0


def cmd_examples(args) -> int:
    if args.json:
        print(json.dumps({"examples": example_cases()}, indent=2))
        return 0
    for item in list_examples():
        print(_c(item["id"], "bold") + f" — {item['title']}")
        print("  " + item["description"])
    return 0


def cmd_audit_prompt(args) -> int:
    result = audit_prompt(
        system_prompt=_text_arg(args.system),
        use_case=args.use_case or "",
        tools=args.tool or None,
        retrieves_external_content=args.retrieves_external_content,
        handles_secrets=args.handles_secrets,
        output_schema=_json_arg(args.schema_json),
        high_risk_actions=args.high_risk_action or None,
        dynamic=args.dynamic,
        llm=args.llm,
    )
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    sev_color = {"critical": "red", "high_risk": "red", "medium_risk": "yellow",
                 "low_risk": "green"}.get(result["grade"], "yellow")
    print(_c(f"prompt audit: {result['grade']}", sev_color) +
          f"  risk {result['risk_score']:.2f}")
    for issue in result["issues"]:
        color = "red" if issue["severity"] == "critical" else "yellow"
        print(_c(f"- {issue['id']}", color) + f" [{issue['severity']}] {issue['title']}")
        print("  " + issue["evidence"])
        print(_c("  fix: ", "dim") + issue["fix"])
    if result["attack_cases"]:
        print(_c(f"\nattack probes: {len(result['attack_cases'])}", "dim"))
        for case in result["attack_cases"]:
            print(f"- {case['id']} ({case['result']}): {case['user_prompt'][:90]}")
    return 0


def cmd_eval(args) -> int:
    result = evaluate_corpus_file(args.file, explain_with_llm=args.explain)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print(_c(f"accuracy {result['accuracy']:.1%}", "green" if result["accuracy"] >= args.min_accuracy else "red") +
          f"  {result['correct']}/{result['total']}")
    if result["misses"]:
        print(_c("misses:", "yellow"))
        for miss in result["misses"][:20]:
            print(f"- {miss['id']}: expected {miss['expected']}, got {miss['got']}")
    return 0 if result["accuracy"] >= args.min_accuracy else 1


def cmd_pipeline(args) -> int:
    path = Path(args.file)
    data = json.loads(path.read_text()) if path.exists() else _json_arg(args.file)
    if isinstance(data, dict):
        stages = data.get("stages") or []
        result = analyze_pipeline(
            stages,
            system_prompt=data.get("system_prompt", ""),
            user_prompt=data.get("prompt") or data.get("user_prompt", ""),
            output_schema=data.get("output_schema"),
        )
    else:
        result = analyze_pipeline(data or [])
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    if result["healthy"]:
        print(_c("pipeline healthy", "green"))
        return 0
    p = result["primary"]
    print(_c(f"{p['stage_id']} → {p['failure']}", "red") + f"  conf {p['confidence']}")
    print("  " + p["root_cause"])
    return 1


def cmd_agent(args) -> int:
    path = Path(args.file)
    data = json.loads(path.read_text()) if path.exists() else _json_arg(args.file)
    if isinstance(data, dict):
        result = agent_report(data, goal=args.goal or None, expected_tools=args.expected_tool or None)
    else:
        result = agent_report(data or [], goal=args.goal, expected_tools=args.expected_tool or None)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    if result["healthy"]:
        print(_c("agent trace healthy", "green"))
        return 0
    p = result["primary"]
    print(_c(f"{p['failure']}", "red") + f"  conf {p['confidence']}")
    print("  " + p["root_cause"])
    print(_c("  fix: ", "dim") + p["fix"])
    return 1


def cmd_serve(args) -> int:
    import uvicorn
    uvicorn.run("server.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="debugai", description="Diagnose & fix LLM failures.")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="diagnose a single prompt/output")
    a.add_argument("--prompt", required=True)
    a.add_argument("--output", required=True)
    a.add_argument("--system", default="")
    a.add_argument("--chunk", action="append", help="a retrieved chunk (repeatable)")
    a.add_argument("--score", action="append", type=float, help="similarity score (repeatable)")
    a.add_argument("--temperature", type=float)
    a.add_argument("--context-window", type=int, dest="context_window")
    a.add_argument("--tool-expected", action="append", help="expected tool name (repeatable)")
    a.add_argument("--tool-call-json", action="append", help="captured tool call JSON object (repeatable)")
    a.add_argument("--schema-json", help="response schema as JSON, or @path/to/schema.json")
    a.add_argument("--explain", action="store_true", help="use the LLM explainer")
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_analyze)

    d = sub.add_parser("diagnose", help="diagnose a JSON file of cases")
    d.add_argument("file")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_diagnose)

    fx = sub.add_parser("fix", help="diagnose + propose/verify a fix for each case")
    fx.add_argument("file")
    fx.add_argument("--simulate", action="store_true", help="run the verify loop with a grounded stub model")
    fx.set_defaults(func=cmd_fix)

    rp = sub.add_parser("report", help="diagnose + return the full debug report artifact")
    rp.add_argument("file", nargs="?", help="JSON case file")
    rp.add_argument("--example", choices=[x["id"] for x in list_examples()])
    rp.add_argument("--simulate", action="store_true", help="verify with a grounded stub model")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_report)

    ex = sub.add_parser("examples", help="list built-in debugging examples")
    ex.add_argument("--json", action="store_true")
    ex.set_defaults(func=cmd_examples)

    ap = sub.add_parser("audit-prompt", help="scan a system prompt for vulnerabilities")
    ap.add_argument("--system", required=True, help="system prompt text, or @path/to/prompt.txt")
    ap.add_argument("--use-case", default="")
    ap.add_argument("--tool", action="append", help="available tool name (repeatable)")
    ap.add_argument("--high-risk-action", action="append", help="side-effect action requiring approval")
    ap.add_argument("--retrieves-external-content", action="store_true")
    ap.add_argument("--handles-secrets", action="store_true")
    ap.add_argument("--schema-json", help="output schema as JSON, or @path/to/schema.json")
    ap.add_argument("--dynamic", action="store_true", help="generate adversarial attack probes")
    ap.add_argument("--llm", action="store_true", help="use the LLM auditor when OPENAI_API_KEY is set")
    ap.add_argument("--json", action="store_true")
    ap.set_defaults(func=cmd_audit_prompt)

    ev = sub.add_parser("eval", help="evaluate a labeled failure corpus")
    ev.add_argument("file")
    ev.add_argument("--min-accuracy", type=float, default=0.8)
    ev.add_argument("--explain", action="store_true")
    ev.add_argument("--json", action="store_true")
    ev.set_defaults(func=cmd_eval)

    pl = sub.add_parser("pipeline", help="diagnose a staged pipeline trace JSON file")
    pl.add_argument("file", help="JSON file or @path containing {'stages': [...]}")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_pipeline)

    ag = sub.add_parser("agent", help="diagnose an agent runtime trace JSON file")
    ag.add_argument("file", help="JSON file, @path, or inline JSON with {'events': [...]}")
    ag.add_argument("--goal", default="", help="agent goal when the trace is a raw event list")
    ag.add_argument("--expected-tool", action="append", help="required tool name for raw event lists")
    ag.add_argument("--json", action="store_true")
    ag.set_defaults(func=cmd_agent)

    sv = sub.add_parser("serve", help="launch the web app")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    sv.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
