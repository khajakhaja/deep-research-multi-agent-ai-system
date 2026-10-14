"""Evaluation package."""

from app.evaluation.benchmark import BENCHMARK, CRITERIA, BenchmarkQuestion
from app.evaluation.runner import Evaluator, RunResult, format_report, report_to_json

__all__ = [
    "BENCHMARK",
    "CRITERIA",
    "BenchmarkQuestion",
    "Evaluator",
    "RunResult",
    "format_report",
    "report_to_json",
]
