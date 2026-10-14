"""Benchmark questions and evaluation criteria.

The benchmark is intentionally small and extensible. Each entry pairs a
research question with a category and the evidence signals that a reviewer
would expect to see. Running it against the system measures real behavior; it
never fabricates metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class BenchmarkQuestion:
    """A single benchmark item."""

    id: str
    question: str
    category: str
    #: Substrings that a good report should mention (case-insensitive).
    expected_themes: List[str] = field(default_factory=list)


BENCHMARK: List[BenchmarkQuestion] = [
    BenchmarkQuestion(
        id="agai-india",
        question=(
            "Analyze the current adoption of Agentic AI in India, its impact on "
            "fresher hiring, the skills companies expect, and career "
            "opportunities over the next three years."
        ),
        category="technology-labor",
        expected_themes=["agentic", "hiring", "skills", "India"],
    ),
    BenchmarkQuestion(
        id="ai-regulation",
        question=(
            "Compare how India and the European Union are approaching the "
            "regulation of artificial intelligence, highlighting key "
            "differences and similarities."
        ),
        category="policy",
        expected_themes=["regulation", "India", "European Union"],
    ),
    BenchmarkQuestion(
        id="climate-agriculture",
        question=(
            "Assess the impact of climate change on agricultural productivity "
            "and the main adaptation strategies being adopted."
        ),
        category="climate",
        expected_themes=["climate", "agriculture", "adaptation"],
    ),
    BenchmarkQuestion(
        id="digital-public-infra",
        question=(
            "Evaluate the effectiveness of digital public infrastructure for "
            "financial inclusion, including evidence of benefits and risks."
        ),
        category="economics",
        expected_themes=["digital", "financial inclusion", "risk"],
    ),
]

#: Documented evaluation criteria. Kept as data so changes are explicit.
CRITERIA = {
    "citation_coverage": "Fraction of report paragraphs containing a citation.",
    "evidence_support_rate": "Verified claims divided by total extracted claims.",
    "unsupported_claim_rate": "Unverified/unsupported claims divided by total claims.",
    "source_retrieval_success": "Accessible sources divided by total discovered sources.",
    "research_completion_rate": "Runs reaching a terminal status divided by total runs.",
    "review_pass_rate": "Runs whose final review passed divided by total runs.",
    "avg_execution_time_seconds": "Mean wall-clock time per research run.",
    "estimated_api_cost_usd": "Optional; reported only when provider usage data exists.",
}
