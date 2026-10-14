"""Persistence hooks used by graph nodes to record progress.

``RunRecorder`` is the interface the workflow depends on. ``DbRunRecorder``
writes to the configured database; ``NullRecorder`` is a no-op used in tests
and when persistence is disabled.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional, Protocol

from app.schemas.research import (
    AnalysisResult,
    EvidenceItem,
    ResearchPlan,
    ResearchReport,
    ReviewResult,
    Source,
)

logger = logging.getLogger(__name__)


class RunRecorder(Protocol):
    """Interface for recording workflow progress."""

    def set_stage(self, stage: str, status: Optional[str] = None) -> None: ...
    def set_status(self, status: str) -> None: ...
    def set_error(self, error: str) -> None: ...
    def set_insufficient(self, flag: bool) -> None: ...
    def set_objective(self, objective: str, scope: str, information_needs: List[str]) -> None: ...
    def set_budget(self, searches: int, fetches: int) -> None: ...
    def set_retries(self, research: int, review: int) -> None: ...
    def save_plan(self, plan: ResearchPlan) -> None: ...
    def save_sources(self, sources: List[Source]) -> None: ...
    def save_evidence(self, evidence: List[EvidenceItem]) -> None: ...
    def save_report(self, report: ResearchReport) -> None: ...
    def save_review(self, review: ReviewResult, attempt: int) -> None: ...
    def record_execution(
        self,
        agent: str,
        stage: str,
        status: str,
        summary: str = "",
        details: Optional[dict] = None,
        duration_ms: Optional[int] = None,
    ) -> None: ...


class NullRecorder:
    """A recorder that discards everything (used in tests)."""

    def set_stage(self, stage: str, status: Optional[str] = None) -> None:
        return None

    def set_status(self, status: str) -> None:
        return None

    def set_error(self, error: str) -> None:
        return None

    def set_insufficient(self, flag: bool) -> None:
        return None

    def set_objective(self, objective: str, scope: str, information_needs: List[str]) -> None:
        return None

    def set_budget(self, searches: int, fetches: int) -> None:
        return None

    def set_retries(self, research: int, review: int) -> None:
        return None

    def save_plan(self, plan: ResearchPlan) -> None:
        return None

    def save_sources(self, sources: List[Source]) -> None:
        return None

    def save_evidence(self, evidence: List[EvidenceItem]) -> None:
        return None

    def save_report(self, report: ResearchReport) -> None:
        return None

    def save_review(self, review: ReviewResult, attempt: int) -> None:
        return None

    def record_execution(
        self,
        agent: str,
        stage: str,
        status: str,
        summary: str = "",
        details: Optional[dict] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        return None


class DbRunRecorder:
    """A recorder that persists workflow progress to the database.

    Each method opens a short-lived session so the recorder is safe to use
    from a background thread. Failures are logged but never crash the run.
    """

    def __init__(self, research_id: str, session_factory) -> None:  # noqa: ANN001
        self._research_id = research_id
        self._session_factory = session_factory

    def _run(self, fn, default=None):  # noqa: ANN001
        from app.database.models import ResearchSession

        session = self._session_factory()
        try:
            obj = session.get(ResearchSession, self._research_id)
            if obj is None:
                return default
            result = fn(obj, session)
            session.commit()
            return result
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.warning("Recorder operation failed for %s: %s", self._research_id, exc)
            return default
        finally:
            session.close()

    def set_stage(self, stage: str, status: Optional[str] = None) -> None:
        def op(obj, _session):  # noqa: ANN001
            obj.stage = stage
            if status:
                obj.status = status
        self._run(op)

    def set_status(self, status: str) -> None:
        self._run(lambda obj, _s: setattr(obj, "status", status))

    def set_error(self, error: str) -> None:
        self._run(lambda obj, _s: setattr(obj, "error", error))

    def set_insufficient(self, flag: bool) -> None:
        self._run(lambda obj, _s: setattr(obj, "insufficient_evidence", flag))

    def set_objective(self, objective: str, scope: str, information_needs: List[str]) -> None:
        def op(obj, _session):  # noqa: ANN001
            obj.objective = objective
            obj.scope = scope
            obj.information_needs = json.dumps(information_needs)
        self._run(op)

    def set_budget(self, searches: int, fetches: int) -> None:
        def op(obj, _session):  # noqa: ANN001
            obj.search_requests_used = searches
            obj.page_fetches_used = fetches
        self._run(op)

    def set_retries(self, research: int, review: int) -> None:
        def op(obj, _session):  # noqa: ANN001
            obj.research_retries = research
            obj.review_retries = review
        self._run(op)

    def save_plan(self, plan: ResearchPlan) -> None:
        from app.database.models import ResearchTaskRecord

        def op(obj, session):  # noqa: ANN001
            obj.objective = plan.objective
            obj.scope = plan.scope
            obj.information_needs = json.dumps(plan.information_needs)
            session.query(ResearchTaskRecord).filter(
                ResearchTaskRecord.session_id == self._research_id
            ).delete()
            for index, task in enumerate(plan.tasks):
                session.add(
                    ResearchTaskRecord(
                        session_id=self._research_id,
                        task_key=task.id,
                        title=task.title,
                        description=task.description,
                        rationale=task.rationale,
                        queries=json.dumps(task.queries),
                        status=task.status,
                        order_index=index,
                    )
                )
        self._run(op)

    def save_sources(self, sources: List[Source]) -> None:
        from app.database.models import SourceRecord

        def op(_obj, session):  # noqa: ANN001
            existing = {
                row.source_key
                for row in session.query(SourceRecord)
                .filter(SourceRecord.session_id == self._research_id)
                .all()
            }
            for source in sources:
                if source.id in existing:
                    continue
                session.add(
                    SourceRecord(
                        session_id=self._research_id,
                        source_key=source.id,
                        title=source.title,
                        url=source.url,
                        canonical_url=source.canonical_url,
                        domain=source.domain,
                        retrieved_at=source.retrieved_at,
                        published_date=source.published_date,
                        snippet=source.snippet,
                        passages=json.dumps([p.model_dump() for p in source.passages]),
                        task_id=source.task_id,
                        query=source.query,
                        accessible=source.accessible,
                        verification_status=source.verification_status,
                        content_hash=source.content_hash,
                    )
                )
        self._run(op)

    def save_evidence(self, evidence: List[EvidenceItem]) -> None:
        from app.database.models import EvidenceRecord

        def op(_obj, session):  # noqa: ANN001
            session.query(EvidenceRecord).filter(
                EvidenceRecord.session_id == self._research_id
            ).delete()
            for item in evidence:
                session.add(
                    EvidenceRecord(
                        session_id=self._research_id,
                        evidence_key=item.id,
                        claim=item.claim,
                        source_id=item.source_id,
                        source_url=item.source_url,
                        source_title=item.source_title,
                        excerpt=item.excerpt,
                        support=item.support,
                        automated_check=item.automated_check,
                        verification_status=item.verification_status,
                        confidence=item.confidence,
                        verified_by=item.verified_by,
                        notes=item.notes,
                    )
                )
        self._run(op)

    def save_report(self, report: ResearchReport) -> None:
        from app.database.models import ReportRecord

        def op(_obj, session):  # noqa: ANN001
            existing = (
                session.query(ReportRecord)
                .filter(ReportRecord.session_id == self._research_id)
                .one_or_none()
            )
            citations = json.dumps([c.model_dump() for c in report.citations])
            if existing is not None:
                existing.title = report.title
                existing.markdown = report.markdown
                existing.citations = citations
                existing.source_count = report.source_count
                existing.citation_count = report.citation_count
                existing.word_count = report.word_count
                existing.insufficient_evidence = report.insufficient_evidence
            else:
                session.add(
                    ReportRecord(
                        session_id=self._research_id,
                        title=report.title,
                        markdown=report.markdown,
                        citations=citations,
                        source_count=report.source_count,
                        citation_count=report.citation_count,
                        word_count=report.word_count,
                        insufficient_evidence=report.insufficient_evidence,
                    )
                )
        self._run(op)

    def save_review(self, review: ReviewResult, attempt: int) -> None:
        from app.database.models import ReviewRecord

        def op(_obj, session):  # noqa: ANN001
            session.add(
                ReviewRecord(
                    session_id=self._research_id,
                    attempt=attempt,
                    passed=review.passed,
                    score=review.score,
                    summary=review.summary,
                    issues=json.dumps([i.model_dump() for i in review.issues]),
                    citation_coverage=review.citation_coverage,
                    unsupported_claims=json.dumps(review.unsupported_claims),
                )
            )
        self._run(op)

    def record_execution(
        self,
        agent: str,
        stage: str,
        status: str,
        summary: str = "",
        details: Optional[dict] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        from app.database.models import AgentExecutionRecord

        def op(_obj, session):  # noqa: ANN001
            session.add(
                AgentExecutionRecord(
                    session_id=self._research_id,
                    agent=agent,
                    stage=stage,
                    status=status,
                    summary=summary,
                    details=json.dumps(details) if details else None,
                    duration_ms=duration_ms,
                )
            )
        self._run(op)
