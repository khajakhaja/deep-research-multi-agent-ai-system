"""Evaluation runner.

Runs a set of benchmark questions through the research service and computes
the documented metrics. It reports only what it actually measures; missing
data (for example provider cost) is reported as ``None`` rather than invented.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from app.constants import RunStatus
from app.evaluation.benchmark import BENCHMARK, CRITERIA, BenchmarkQuestion
from app.services.research_service import ResearchService

_CITATION_RE = re.compile(r"\[S\d+\]")


@dataclass
class RunResult:
    """Metrics for a single benchmark run."""

    benchmark_id: str
    question: str
    status: str
    citation_coverage: float
    evidence_support_rate: float
    unsupported_claim_rate: float
    source_retrieval_success: float
    review_passed: bool
    execution_time_seconds: float
    themes_matched: List[str] = field(default_factory=list)


class Evaluator:
    """Runs benchmark questions and aggregates metrics."""

    def __init__(
        self,
        service: ResearchService,
        questions: Optional[List[BenchmarkQuestion]] = None,
    ):
        self.service = service
        self.questions = BENCHMARK if questions is None else questions

    def run(self) -> Dict:
        """Run all benchmark questions and return the aggregated report."""
        results: List[RunResult] = []

        for item in self.questions:
            created = self.service.create_research(item.question)
            start = time.perf_counter()
            self.service.run_research(created.research_id, item.question)
            elapsed = time.perf_counter() - start

            status = self.service.get_status(created.research_id)
            report = self.service.get_report(created.research_id)
            sources = self.service.get_sources(created.research_id)

            results.append(self._measure(item, status, report, sources, elapsed))

        return {
            "runs": [asdict(r) for r in results],
            "aggregate": self._aggregate(results),
            "criteria": CRITERIA,
        }

    def _measure(self, item, status, report, sources, elapsed) -> RunResult:  # noqa: ANN001
        markdown = report.markdown if report else ""
        prose = "\n".join(
            line for line in markdown.splitlines() if not line.strip().startswith("#")
        )
        blocks = [b.strip() for b in prose.split("\n\n") if len(b.strip()) >= 80]
        citation_coverage = (
            sum(1 for b in blocks if _CITATION_RE.search(b)) / len(blocks) if blocks else 0.0
        )

        evidence = sources.evidence if sources else []
        total_claims = len(evidence)
        verified = sum(1 for e in evidence if e.verification_status == "verified")
        unverified = sum(
            1 for e in evidence if e.verification_status in ("unverified", "disputed")
        )
        evidence_support_rate = verified / total_claims if total_claims else 0.0
        unsupported_claim_rate = unverified / total_claims if total_claims else 0.0

        all_sources = sources.sources if sources else []
        accessible = sum(1 for s in all_sources if s.accessible)
        source_success = accessible / len(all_sources) if all_sources else 0.0

        review_passed = bool(report and report.review and report.review.passed)
        themes = [t for t in item.expected_themes if t.lower() in markdown.lower()]

        return RunResult(
            benchmark_id=item.id,
            question=item.question,
            status=status.status if status else "unknown",
            citation_coverage=round(citation_coverage, 3),
            evidence_support_rate=round(evidence_support_rate, 3),
            unsupported_claim_rate=round(unsupported_claim_rate, 3),
            source_retrieval_success=round(source_success, 3),
            review_passed=review_passed,
            execution_time_seconds=round(elapsed, 2),
            themes_matched=themes,
        )

    def _aggregate(self, results: List[RunResult]) -> Dict:
        if not results:
            return {}
        n = len(results)
        terminal = sum(
            1
            for r in results
            if r.status in (RunStatus.COMPLETED, RunStatus.INSUFFICIENT_EVIDENCE, RunStatus.FAILED)
        )
        passes = sum(1 for r in results if r.review_passed)
        return {
            "runs": n,
            "citation_coverage": round(sum(r.citation_coverage for r in results) / n, 3),
            "evidence_support_rate": round(sum(r.evidence_support_rate for r in results) / n, 3),
            "unsupported_claim_rate": round(sum(r.unsupported_claim_rate for r in results) / n, 3),
            "source_retrieval_success": round(sum(r.source_retrieval_success for r in results) / n, 3),
            "research_completion_rate": round(terminal / n, 3),
            "review_pass_rate": round(sum(1 for r in results if r.review_passed) / n, 3),
            "avg_execution_time_seconds": round(
                sum(r.execution_time_seconds for r in results) / n, 2
            ),
            "estimated_api_cost_usd": None,  # only reported when provider usage exists
        }


def format_report(result: Dict) -> str:
    """Render an evaluation result as readable text."""
    lines = ["=" * 60, "Deep Research AI - Evaluation Report", "=" * 60, ""]
    lines.append("Aggregate metrics:")
    for key, value in result.get("aggregate", {}).items():
        lines.append(f"  {key}: {value}")
    lines.append("")
    lines.append("Per-question results:")
    for run in result.get("runs", []):
        lines.append(
            f"  [{run['benchmark_id']}] status={run['status']} "
            f"citation_coverage={run['citation_coverage']} "
            f"evidence_support={run['evidence_support_rate']} "
            f"source_success={run['source_retrieval_success']} "
            f"review_passed={run['review_passed']} "
            f"time={run['execution_time_seconds']}s"
        )
    return "\n".join(lines)


def report_to_json(result: Dict) -> str:
    return json.dumps(result, indent=2)
