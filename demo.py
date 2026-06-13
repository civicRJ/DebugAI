"""Quick demo of the DebugAI diagnosis core. Run: python demo.py"""

import json

from debugai import analyze

EXAMPLES = [
    dict(
        label="Retrieval failure",
        prompt="What is the refund policy for electronics?",
        output="Electronics can be returned within 90 days for a full cash refund.",
        chunks=["Our store hours are 9am to 5pm.", "Parking is behind the building."],
        similarity_scores=[0.42, 0.40],
        temperature=0.2,
    ),
    dict(
        label="Hallucination",
        prompt="What does Section 4 of the contract require?",
        output="Section 4 requires arbitration in Delaware under the Marbury Clause "
        "and imposes a $50,000 early-termination penalty.",
        chunks=["Section 4 covers confidentiality between the parties.",
                "The contract is governed by California law."],
        similarity_scores=[0.66, 0.59],
        temperature=0.75,
    ),
    dict(
        label="Healthy",
        prompt="What is the standard return window?",
        output="Most items may be returned within 30 days with a receipt.",
        chunks=["Returns: most items may be returned within 30 days with a receipt."],
        similarity_scores=[0.89],
        temperature=0.1,
    ),
]

for ex in EXAMPLES:
    label = ex.pop("label")
    r = analyze(explain_with_llm=True, **ex)
    print("=" * 70)
    print(f"[{label}]")
    if r["healthy"]:
        print("  → healthy (no failure detected)")
    else:
        p = r["primary"]
        print(f"  → {p['failure']}  (confidence {p['confidence']}, {p['severity']})")
        print(f"  explanation: {r['explanation']}")
        print(f"  fix:         {p['fix']}")
        if r["secondary"]:
            print(f"  secondary:   {[s['failure'] for s in r['secondary']]}")
    print(f"  signals:     {json.dumps({k: v for k, v in r['signals'].items() if isinstance(v, (int, float))})}")
