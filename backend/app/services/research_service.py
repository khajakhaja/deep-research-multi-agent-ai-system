"""Research orchestration service.

Owns the lifecycle of a research run: creating the database session,
executing the LangGraph workflow in a background thread, persisting results,
and answering status/report/source queries.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.agents.context import AgentContext, Budget, SourceRegistry
from app.config import Settings, get_settings
from app.constants import RunStatus, Stage
from app.database.models import (
    AgentExecutionRecord,
    EvidenceRecord,
    ReportRecord,
    ResearchSession,
    ResearchTaskRecord,
    ReviewRecord,
    SourceRecord,
)
from app.database.session import get_session_factory
from app.graph import build_graph, build_initial_state, graph_thread_config
from app.graph.builder import get_checkpointer
from app.graph.recorder import DbRunRecorder
from app.logging_config import get_logger
from app.schemas.api import (
    ProgressInfo,
    ReportResponse,
    ResearchCreatedResponse,
    ResearchHistoryItem,
    ResearchHistoryResponse,
    ResearchStatusResponse,
    SourceListResponse,
)
from app.schemas.research import (
    Citation,
    EvidenceItem,
    ResearchConfig,
    ResearchTask,
    ReviewIssue,
    ReviewResult,
    Source,
    SourcePassage,
)
from app.tools import LLMClient, PageFetcher, WebSearchTool

logger = logging.getLogger(__name__)

ToolFactory = Callable[[Settings], Tuple[LLMClient, WebSearchTool, PageFetcher]]
CheckpointerProvider = Callable[[Settings], object]


def default_tool_factory(settings: Settings) -> Tuple[LLMClient, WebSearchTool, PageFetcher]:
    """Build the real, read-only research tools."""
    return LLMClient(settings), WebSearchTool(settings), PageFetcher(settings)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResearchService:
    """Coordinates research runs and persistence."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        session_factory=None,  # noqa: ANN001
        tool_factory: Optional[ToolFactory] = None,
        checkpointer_provider: Optional[CheckpointerProvider] = None,
        executor: Optional[ThreadPoolExecutor] = None,
        max_workers: int = 2,
    ):
        self._settings = settings or get_settings()
        self._session_factory = session_factory or get_session_factory()
        self._tool_factory = tool_factory or default_tool_factory
        self._checkpointer_provider = checkpointer_provider or get_checkpointer
        self._executor = executor or ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="research"
        )
        self._owns_executor = executor is None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------
    def create_research(
        self, question: str, config: Optional[ResearchConfig] = None
    ) -> ResearchCreatedResponse:
        """Create a research session and return its id."""
        session: Session = self._session_factory()
        try:
            record = ResearchSession(
                question=question.strip(),
                status=RunStatus.PENDING,
                stage=Stage.PENDING,
                requested_config=config.model_dump_json() if config else None,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return ResearchCreatedResponse(
                research_id=record.id,
                status=record.status,
                stage=record.stage,
                question=record.question,
                created_at=record.created_at,
            )
        finally:
            session.close()

    def start(
        self, research_id: str, question: str, config: Optional[ResearchConfig] = None
    ) -> None:
        """Submit a research run to the background executor."""
        self._executor.submit(self.run_research, research_id, question, config)

    def run_research(
        self, research_id: str, question: str, config: Optional[ResearchConfig] = None
    ) -> None:
        """Execute the full workflow synchronously (used by worker and tests)."""
        run_logger = logging.LoggerAdapter(logger, {"research_id": research_id})
        settings = self._effective_settings(config)

        self._mark_started(research_id)

        llm, search, fetcher = self._tool_factory(settings)
        budget = Budget(
            max_searches=settings.max_search_requests_per_run,
            max_fetches=settings.max_page_fetches_per_run,
        )
        context = AgentContext(
            settings=settings,
            llm=llm,
            search=search,
            fetcher=fetcher,
            research_id=research_id,
            logger=logging.getLogger("app.research"),
            budget=budget,
            registry=SourceRegistry(),
            deadline=time.monotonic() + settings.run_timeout_seconds,
        )
        recorder = DbRunRecorder(research_id, self._session_factory)

        try:
            checkpointer = self._checkpointer_provider(settings)
            graph = build_graph(context, recorder, checkpointer)
            initial = build_initial_state(research_id, question)
            graph_config = (
                graph_thread_config(research_id)
                if checkpointer
                else {"recursion_limit": 50}
            )
            graph.invoke(initial, config=graph_config)
            run_logger.info("Research workflow finished")
        except Exception as exc:  # noqa: BLE001
            run_logger.exception("Research workflow failed")
            recorder.set_status(RunStatus.FAILED)
            recorder.set_stage(Stage.FAILED)
            recorder.set_error(str(exc)[:2000])
        finally:
            self._mark_finished(research_id)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def get_status(self, research_id: str) -> Optional[ResearchStatusResponse]:
        session = self._session_factory()
        try:
            record = session.get(ResearchSession, research_id)
            if record is None:
                return None

            tasks = [
                ResearchTask(
                    id=t.task_key,
                    title=t.title,
                    description=t.description or "",
                    rationale=t.rationale or "",
                    queries=json.loads(t.queries) if t.queries else [],
                    status=t.status,
                    sources_found=t.sources_found,
                )
                for t in sorted(record.tasks, key=lambda x: x.order_index)
            ]

            evidence = record.evidence
            verified = sum(
                1 for e in evidence if e.verification_status == "verified"
            )

            progress = ProgressInfo(
                tasks_total=len(tasks),
                tasks_completed=sum(1 for t in tasks if t.status == "completed"),
                sources_total=len(record.sources),
                evidence_total=len(evidence),
                verified_claims=verified,
                search_requests_used=record.search_requests_used or 0,
                page_fetches_used=record.page_fetches_used or 0,
                current_stage=record.stage,
                review_retries=record.review_retries or 0,
                research_retries=record.research_retries or 0,
            )

            return ResearchStatusResponse(
                research_id=record.id,
                status=record.status,
                stage=record.stage,
                question=record.question,
                objective=record.objective,
                scope=record.scope,
                tasks=tasks,
                progress=progress,
                error=record.error,
                insufficient_evidence=bool(record.insufficient_evidence),
                created_at=record.created_at,
                updated_at=record.updated_at,
                finished_at=record.finished_at,
            )
        finally:
            session.close()

    def get_report(self, research_id: str) -> Optional[ReportResponse]:
        session = self._session_factory()
        try:
            record = session.get(ResearchSession, research_id)
            if record is None:
                return None

            report = record.report
            review = self._latest_review(record)

            if report is None:
                return ReportResponse(
                    research_id=research_id,
                    status=record.status,
                    title="",
                    markdown="",
                    insufficient_evidence=bool(record.insufficient_evidence),
                    review=review,
                )

            citations = []
            if report.citations:
                citations = [Citation(**c) for c in json.loads(report.citations)]

            return ReportResponse(
                research_id=research_id,
                status=record.status,
                title=report.title or "",
                markdown=report.markdown or "",
                citations=citations,
                source_count=report.source_count or 0,
                citation_count=report.citation_count or 0,
                word_count=report.word_count or 0,
                insufficient_evidence=bool(report.insufficient_evidence),
                review=review,
                created_at=report.created_at,
            )
        finally:
            session.close()

    def get_sources(self, research_id: str) -> Optional[SourceListResponse]:
        session = self._session_factory()
        try:
            record = session.get(ResearchSession, research_id)
            if record is None:
                return None

            sources = [self._to_source(s) for s in record.sources]
            evidence = [self._to_evidence(e) for e in record.evidence]
            return SourceListResponse(
                research_id=research_id, sources=sources, evidence=evidence
            )
        finally:
            session.close()

    def list_history(self, limit: int = 20) -> ResearchHistoryResponse:
        session = self._session_factory()
        try:
            records = (
                session.query(ResearchSession)
                .order_by(ResearchSession.created_at.desc())
                .limit(limit)
                .all()
            )
            items = [
                ResearchHistoryItem(
                    research_id=r.id,
                    question=r.question,
                    status=r.status,
                    stage=r.stage,
                    created_at=r.created_at,
                    finished_at=r.finished_at,
                    source_count=len(r.sources),
                    report_available=r.report is not None,
                )
                for r in records
            ]
            total = session.query(ResearchSession).count()
            return ResearchHistoryResponse(items=items, total=total)
        finally:
            session.close()

    def recover_interrupted(self) -> int:
        """Mark any sessions left running/pending as failed (e.g. after restart)."""
        session = self._session_factory()
        try:
            stale = (
                session.query(ResearchSession)
                .filter(ResearchSession.status.in_((RunStatus.PENDING, RunStatus.RUNNING)))
                .all()
            )
            for record in stale:
                record.status = RunStatus.FAILED
                record.stage = Stage.FAILED
                record.error = (
                    "Run interrupted (server restart or crash) before completion. "
                    "Start a new research run."
                )
                record.finished_at = _utcnow()
            session.commit()
            return len(stale)
        finally:
            session.close()

    def shutdown(self) -> None:
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _effective_settings(self, config: Optional[ResearchConfig]) -> Settings:
        base = self._settings
        if config is None:
            return base
        updates = {}
        if config.max_research_tasks is not None:
            updates["max_research_tasks"] = config.max_research_tasks
        if config.max_search_requests is not None:
            updates["max_search_requests_per_run"] = config.max_search_requests
        if config.max_page_fetches is not None:
            updates["max_page_fetches_per_run"] = config.max_page_fetches
        if config.max_research_retries is not None:
            updates["max_research_retries"] = config.max_research_retries
        if config.max_review_retries is not None:
            updates["max_review_retries"] = config.max_review_retries
        return base.model_copy(update=updates) if updates else base

    def _mark_started(self, research_id: str) -> None:
        session = self._session_factory()
        try:
            record = session.get(ResearchSession, research_id)
            if record is None:
                return
            record.status = RunStatus.RUNNING
            record.stage = Stage.VALIDATING
            record.started_at = _utcnow()
            session.commit()
        finally:
            session.close()

    def _mark_finished(self, research_id: str) -> None:
        session = self._session_factory()
        try:
            record = session.get(ResearchSession, research_id)
            if record is None:
                return
            record.finished_at = _utcnow()
            if record.status in (RunStatus.PENDING, RunStatus.RUNNING):
                record.status = RunStatus.COMPLETED
            session.commit()
        finally:
            session.close()

    def _latest_review(self, record: ResearchSession) -> Optional[ReviewResult]:
        if not record.reviews:
            return None
        latest = max(record.reviews, key=lambda r: r.attempt)
        issues = []
        if latest.issues:
            issues = [ReviewIssue(**i) for i in json.loads(latest.issues)]
        unsupported = json.loads(latest.unsupported_claims) if latest.unsupported_claims else []
        return ReviewResult(
            passed=bool(latest.passed),
            score=latest.score or 0.0,
            summary=latest.summary or "",
            issues=issues,
            citation_coverage=latest.citation_coverage or 0.0,
            unsupported_claims=unsupported,
            feedback=[i.message for i in issues],
        )

    def _to_source(self, s: SourceRecord) -> Source:
        passages = []
        if s.passages:
            passages = [SourcePassage(**p) for p in json.loads(s.passages)]
        return Source(
            id=s.source_key,
            title=s.title or "",
            url=s.url,
            canonical_url=s.canonical_url or s.url,
            domain=s.domain or "",
            retrieved_at=s.retrieved_at,
            published_date=s.published_date,
            snippet=s.snippet or "",
            passages=passages,
            task_id=s.task_id,
            query=s.query,
            accessible=bool(s.accessible),
            verification_status=s.verification_status or "unverified",
            content_hash=s.content_hash or "",
        )

    def _to_evidence(self, e: EvidenceRecord) -> EvidenceItem:
        return EvidenceItem(
            id=e.evidence_key,
            claim=e.claim,
            source_id=e.source_id or "",
            source_url=e.source_url or "",
            source_title=e.source_title or "",
            excerpt=e.excerpt or "",
            support=e.support or "unknown",
            automated_check=e.automated_check or "unknown",
            verification_status=e.verification_status or "unverified",
            confidence=e.confidence or 0.0,
            verified_by=e.verified_by or "",
            notes=e.notes or "",
        )
