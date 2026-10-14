"""Pydantic schemas for the HTTP API layer."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.schemas.research import (
    Citation,
    EvidenceItem,
    ResearchConfig,
    ResearchTask,
    ReviewResult,
    Source,
)


class ResearchRequest(BaseModel):
    """Body of ``POST /api/research``."""

    question: str = Field(..., description="The research question to investigate.")
    config: Optional[ResearchConfig] = Field(
        default=None, description="Optional per-run overrides."
    )


class ResearchCreatedResponse(BaseModel):
    """Returned when a research run is accepted."""

    research_id: str
    status: str
    stage: str
    question: str
    created_at: datetime


class ProgressInfo(BaseModel):
    """Progress counters for a running research session."""

    tasks_total: int = 0
    tasks_completed: int = 0
    sources_total: int = 0
    evidence_total: int = 0
    verified_claims: int = 0
    search_requests_used: int = 0
    page_fetches_used: int = 0
    current_stage: str = "pending"
    review_retries: int = 0
    research_retries: int = 0


class ResearchStatusResponse(BaseModel):
    """Returned by ``GET /api/research/{research_id}``."""

    research_id: str
    status: str
    stage: str
    question: str
    objective: Optional[str] = None
    scope: Optional[str] = None
    tasks: List[ResearchTask] = Field(default_factory=list)
    progress: ProgressInfo = Field(default_factory=ProgressInfo)
    error: Optional[str] = None
    insufficient_evidence: bool = False
    created_at: datetime
    updated_at: datetime
    finished_at: Optional[datetime] = None


class ReportResponse(BaseModel):
    """Returned by ``GET /api/research/{research_id}/report``."""

    research_id: str
    status: str
    title: str = ""
    markdown: str = ""
    citations: List[Citation] = Field(default_factory=list)
    source_count: int = 0
    citation_count: int = 0
    word_count: int = 0
    insufficient_evidence: bool = False
    review: Optional[ReviewResult] = None
    created_at: Optional[datetime] = None


class SourceListResponse(BaseModel):
    """Returned by ``GET /api/research/{research_id}/sources``."""

    research_id: str
    sources: List[Source] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list)


class ResearchHistoryItem(BaseModel):
    """A compact summary used for the research history list."""

    research_id: str
    question: str
    status: str
    stage: str
    created_at: datetime
    finished_at: Optional[datetime] = None
    source_count: int = 0
    report_available: bool = False


class ResearchHistoryResponse(BaseModel):
    items: List[ResearchHistoryItem] = Field(default_factory=list)
    total: int = 0


class HealthResponse(BaseModel):
    """Returned by ``GET /health``."""

    status: str = "ok"
    version: str
    database: str = "ok"
    llm_configured: bool = False
    search_configured: bool = False
    timestamp: datetime


class ErrorResponse(BaseModel):
    """Standard error envelope."""

    detail: str
    research_id: Optional[str] = None
