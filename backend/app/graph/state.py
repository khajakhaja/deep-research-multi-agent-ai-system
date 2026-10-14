"""Typed LangGraph workflow state."""

from __future__ import annotations

from typing import Any, Dict, List

from typing_extensions import TypedDict

from app.schemas.research import (
    AnalysisResult,
    EvidenceItem,
    ResearchPlan,
    ResearchReport,
    ResearchTask,
    ReviewResult,
    Source,
)


class ResearchState(TypedDict, total=False):
    """State threaded through the research workflow.

    ``total=False`` lets individual nodes return partial updates. Complex
    domain objects are stored as their Pydantic models, which LangGraph's
    serializer supports.
    """

    research_id: str
    question: str

    plan: ResearchPlan
    tasks: List[ResearchTask]

    sources: List[Source]
    evidence: List[EvidenceItem]

    analysis: AnalysisResult
    report: ResearchReport
    review: ReviewResult
    sufficiency: Dict[str, Any]

    followup_queries: List[str]
    research_retries: int
    review_retries: int

    stage: str
    status: str
    insufficient_evidence: bool
    errors: List[str]


def build_initial_state(research_id: str, question: str) -> ResearchState:
    """Create the initial workflow state for a run."""
    return ResearchState(
        research_id=research_id,
        question=question,
        tasks=[],
        sources=[],
        evidence=[],
        followup_queries=[],
        research_retries=0,
        review_retries=0,
        stage="pending",
        status="pending",
        insufficient_evidence=False,
        errors=[],
    )
