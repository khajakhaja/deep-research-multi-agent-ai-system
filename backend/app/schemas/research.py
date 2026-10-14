"""Pydantic schemas for the core research domain.

These models are the contract between agents, the LangGraph workflow, the
database layer, and the API. They are deliberately explicit so that evidence
and citations cannot silently lose structure as they flow through the system.

Security note: web page content is treated as untrusted data. Nothing fetched
from the network is ever executed or used as an instruction; it only ever
populates string fields on these models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Research plan
# ---------------------------------------------------------------------------
class ResearchTask(BaseModel):
    """A single focused research subtask within a plan."""

    id: str = Field(description="Stable identifier such as 'T1'.")
    title: str
    description: str = ""
    rationale: str = ""
    queries: List[str] = Field(default_factory=list)
    depends_on: List[str] = Field(default_factory=list)
    status: str = "pending"
    sources_found: int = 0


class ResearchPlan(BaseModel):
    """The coordinator's structured research plan."""

    objective: str
    scope: str = ""
    tasks: List[ResearchTask] = Field(default_factory=list)
    information_needs: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Sources & evidence
# ---------------------------------------------------------------------------
class SourcePassage(BaseModel):
    """A relevant excerpt extracted from a retrieved page."""

    text: str
    relevance: float = 0.0


class Source(BaseModel):
    """A retrieved web source with provenance metadata."""

    id: str = Field(description="Source identifier such as 'S1'.")
    title: str = ""
    url: str
    canonical_url: str = ""
    domain: str = ""
    retrieved_at: datetime = Field(default_factory=_utcnow)
    published_date: Optional[str] = None
    snippet: str = ""
    passages: List[SourcePassage] = Field(default_factory=list)
    task_id: Optional[str] = None
    query: Optional[str] = None
    accessible: bool = True
    verification_status: str = "unverified"
    content_hash: str = ""

    @field_validator("canonical_url", mode="before")
    @classmethod
    def _default_canonical(cls, value, info):  # noqa: ANN001
        if not value:
            return info.data.get("url", "")
        return value


class EvidenceItem(BaseModel):
    """A claim associated with a specific source and supporting excerpt."""

    id: str = Field(description="Evidence identifier such as 'E1'.")
    claim: str
    source_id: str
    source_url: str = ""
    source_title: str = ""
    excerpt: str = ""
    support: str = "unknown"  # supported | partial | unsupported | contradicted
    automated_check: str = "unknown"  # passed | failed
    verification_status: str = "unverified"  # verified | disputed | unverified | unsupported
    confidence: float = 0.0
    verified_by: str = "automated+llm"
    notes: str = ""


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
class AnalysisFinding(BaseModel):
    """A structured analytical finding derived from verified evidence."""

    title: str
    detail: str
    supporting_source_ids: List[str] = Field(default_factory=list)
    confidence: str = "medium"  # low | medium | high
    kind: str = "fact"  # fact | interpretation


class AnalysisResult(BaseModel):
    """Structured synthesis produced by the analysis agent."""

    summary: str = ""
    findings: List[AnalysisFinding] = Field(default_factory=list)
    trends: List[str] = Field(default_factory=list)
    differences: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------
class ReviewIssue(BaseModel):
    """A single issue flagged during report review."""

    severity: str = "warning"  # info | warning | error
    category: str = ""
    message: str = ""
    location: str = ""


class ReviewResult(BaseModel):
    """Outcome of reviewing a generated report."""

    passed: bool = False
    score: float = 0.0
    summary: str = ""
    issues: List[ReviewIssue] = Field(default_factory=list)
    citation_coverage: float = 0.0
    unsupported_claims: List[str] = Field(default_factory=list)
    feedback: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
class Citation(BaseModel):
    """A resolved citation linking a marker in the report to a source."""

    marker: str
    source_id: str
    title: str = ""
    url: str = ""


class ResearchReport(BaseModel):
    """The final generated research report."""

    title: str = ""
    markdown: str = ""
    citations: List[Citation] = Field(default_factory=list)
    source_count: int = 0
    citation_count: int = 0
    word_count: int = 0
    insufficient_evidence: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Runtime configuration overrides (per request)
# ---------------------------------------------------------------------------
class ResearchConfig(BaseModel):
    """Optional per-run overrides supplied by the API caller."""

    max_research_tasks: Optional[int] = Field(default=None, ge=1, le=12)
    max_search_requests: Optional[int] = Field(default=None, ge=1, le=100)
    max_page_fetches: Optional[int] = Field(default=None, ge=1, le=150)
    max_research_retries: Optional[int] = Field(default=None, ge=0, le=5)
    max_review_retries: Optional[int] = Field(default=None, ge=0, le=5)
