"""DebugAI command-line interface.

    debugai analyze --prompt "..." --output "..." --chunk "..." --score 0.4
    debugai diagnose cases.json
    debugai fix cases.json --simulate
    debugai serve --port 8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from debugai import analyze
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

    sv = sub.add_parser("serve", help="launch the web app")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.add_argument("--reload", action="store_true")
    sv.set_defaults(func=cmd_serve)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
