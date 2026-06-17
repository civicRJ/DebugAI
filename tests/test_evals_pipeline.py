import json

from debugai.evals import evaluate_corpus_file
from debugai.pipeline import analyze_pipeline


def test_evaluate_corpus_file_reports_accuracy(tmp_path):
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps({"cases": [{
        "id": "rf",
        "prompt": "What is the refund policy?",
        "output": "Full refund for 90 days.",
        "chunks": ["Store hours are 9 to 5."],
        "similarity_scores": [0.2],
        "expected_failure": "retrieval_failure",
    }]}))
    result = evaluate_corpus_file(path)
    assert result["accuracy"] == 1.0
    assert result["results"][0]["got"] == "retrieval_failure"


def test_analyze_pipeline_finds_retrieval_stage_failure():
    result = analyze_pipeline([
        {
            "id": "ret",
            "kind": "retrieval",
            "input": "refund policy",
            "chunks": ["parking is behind the building"],
            "similarity_scores": [0.2],
        },
        {
            "id": "gen",
            "kind": "generation",
            "output": "Refunds are available.",
        },
    ], user_prompt="refund policy")
    assert result["healthy"] is False
    assert result["primary"]["stage_id"] == "ret"
    assert result["primary"]["failure"] == "retrieval_failure"
