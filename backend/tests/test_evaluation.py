"""Tests for the evaluation framework."""
from app.evaluation import BENCHMARK, CRITERIA, Evaluator
from app.evaluation.benchmark import BenchmarkQuestion
from app.evaluation.runner import format_report, report_to_json


def test_evaluator_runs_benchmark(service):
    questions = BENCHMARK[:2]
    report = Evaluator(service, questions).run()

    assert report["aggregate"]["runs"] == 2
    assert 0.0 <= report["aggregate"]["citation_coverage"] <= 1.0
    assert 0.0 <= report["aggregate"]["evidence_support_rate"] <= 1.0
    assert 0.0 <= report["aggregate"]["research_completion_rate"] <= 1.0
    assert report["aggregate"]["estimated_api_cost_usd"] is None
    assert report["criteria"] == CRITERIA
    assert len(report["runs"]) == 2


def test_evaluator_single_question(service):
    q = BenchmarkQuestion(
        id="unit",
        question="What is the impact of AI on healthcare diagnostics?",
        category="health",
        expected_themes=["AI"],
    )
    report = Evaluator(service, [q]).run()
    run = report["runs"][0]
    assert run["benchmark_id"] == "unit"
    assert run["status"] in ("completed", "insufficient_evidence", "failed")
    assert run["source_retrieval_success"] >= 0.0


def test_evaluator_empty_benchmark(service):
    report = Evaluator(service, []).run()
    assert report["aggregate"] == {}
    assert report["runs"] == []


def test_formatters(service):
    report = Evaluator(service, BENCHMARK[:1]).run()
    text = format_report(report)
    assert "Evaluation Report" in text
    assert "citation_coverage" in text
    parsed = report_to_json(report)
    assert '"aggregate"' in parsed
