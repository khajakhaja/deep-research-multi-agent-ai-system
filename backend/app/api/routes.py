"""API routes for research endpoints.

Endpoints:
- POST /api/research: create and start a research run
- GET /api/research: list research history
- GET /api/research/{research_id}: fetch status and progress
- GET /api/research/{research_id}/report: fetch completed report
- GET /api/research/{research_id}/sources: fetch sources and evidence
- GET /health: health check
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_research_service
from app.config import get_settings
from app.schemas.api import (
    ErrorResponse,
    HealthResponse,
    ReportResponse,
    ResearchCreatedResponse,
    ResearchHistoryResponse,
    ResearchRequest,
    ResearchStatusResponse,
    SourceListResponse,
)
from app.services.research_service import ResearchService
from app.database.session import check_database

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version="1.0.0",
        database=check_database(),
        llm_configured=settings.llm_configured,
        search_configured=settings.search_configured,
        timestamp=datetime.utcnow(),
    )


@router.post(
    "/api/research",
    response_model=ResearchCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_research(
    request: ResearchRequest,
    service: ResearchService = Depends(get_research_service),
) -> ResearchCreatedResponse:
    question = request.question.strip()
    settings = get_settings()
    if len(question) < settings.min_question_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Question must be at least {settings.min_question_length} characters long.",
        )
    if len(question) > settings.max_question_length:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Question must be at most {settings.max_question_length} characters long.",
        )

    created = service.create_research(question, request.config)
    service.start(created.research_id, question, request.config)
    return created


@router.get("/api/research", response_model=ResearchHistoryResponse)
async def list_research(
    limit: int = Query(20, ge=1, le=100),
    service: ResearchService = Depends(get_research_service),
) -> ResearchHistoryResponse:
    return service.list_history(limit)


@router.get(
    "/api/research/{research_id}",
    response_model=ResearchStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_status(
    research_id: str,
    service: ResearchService = Depends(get_research_service),
) -> ResearchStatusResponse:
    status_resp = service.get_status(research_id)
    if status_resp is None:
        raise HTTPException(status_code=404, detail="Research session not found")
    return status_resp


@router.get(
    "/api/research/{research_id}/report",
    response_model=ReportResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_report(
    research_id: str,
    service: ResearchService = Depends(get_research_service),
) -> ReportResponse:
    report_resp = service.get_report(research_id)
    if report_resp is None:
        raise HTTPException(status_code=404, detail="Research session not found")
    return report_resp


@router.get(
    "/api/research/{research_id}/sources",
    response_model=SourceListResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_sources(
    research_id: str,
    service: ResearchService = Depends(get_research_service),
) -> SourceListResponse:
    src_resp = service.get_sources(research_id)
    if src_resp is None:
        raise HTTPException(status_code=404, detail="Research session not found")
    return src_resp
