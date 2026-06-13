"""CLI smoke tests — exercise the argparse commands via main()."""

import json

from debugai import cli


def test_analyze_command_json(capsys):
    rc = cli.main([
        "analyze",
        "--prompt", "What is the refund policy?",
        "--output", "Full 90-day cash refund, no receipt.",
        "--chunk", "Store hours are 9 to 5.",
        "--score", "0.41",
        "--json",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["primary"]["failure"] == "retrieval_failure"


def test_diagnose_command_on_dataset(capsys, tmp_path):
    cases = {"cases": [
        {"label": "rf", "prompt": "refund policy?", "output": "Full cash refund in 90 days.",
         "chunks": ["Store hours are 9 to 5."], "similarity_scores": [0.2], "temperature": 0.1},
        {"label": "ok", "prompt": "HQ?", "output": "HQ is in Austin, Texas.",
         "chunks": ["The company is headquartered in Austin, Texas."],
         "similarity_scores": [0.9], "temperature": 0.0},
    ]}
    f = tmp_path / "cases.json"
    f.write_text(json.dumps(cases))
    rc = cli.main(["diagnose", str(f), "--json"])
    assert rc == 0
    results = json.loads(capsys.readouterr().out)
    assert results[0]["primary"]["failure"] == "retrieval_failure"
    assert results[1]["healthy"] is True


def test_fix_command_simulate(capsys, tmp_path):
    case = {"cases": [{"label": "hall",
        "prompt": "What does Section 4 require?",
        "output": "Section 4 requires arbitration in Delaware under the Marbury Clause.",
        "chunks": ["Section 4 covers confidentiality.", "Governed by California law."],
        "similarity_scores": [0.66, 0.59], "temperature": 0.75}]}
    f = tmp_path / "c.json"
    f.write_text(json.dumps(case))
    rc = cli.main(["fix", str(f), "--simulate"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Prompt Rule Agent" in out and "verified" in out
