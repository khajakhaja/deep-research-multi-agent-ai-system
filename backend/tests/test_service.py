"""Integration tests for the research service and database persistence."""
from app.constants import RunStatus
from app.services.research_service import ResearchService, default_tool_factory
from app.config import Settings

QUESTION = "Analyze Agentic AI adoption in India and its impact on fresher hiring."


def test_create_research_persists(service):
    created = service.create_research(QUESTION)
    assert created.research_id
    status = service.get_status(created.research_id)
    assert status is not None
    assert status.question == QUESTION
    assert status.status == RunStatus.PENDING


def test_run_research_end_to_end(service):
    created = service.create_research(QUESTION)
    service.run_research(created.research_id, QUESTION)

    status = service.get_status(created.research_id)
    assert status.status in (RunStatus.COMPLETED, RunStatus.INSUFFICIENT_EVIDENCE)
    assert status.progress.sources_total > 0
    assert status.progress.evidence_total > 0
    assert status.progress.verified_claims > 0

    report = service.get_report(created.research_id)
    assert report is not None
    assert "## Executive Summary" in report.markdown
    assert len(report.citations) > 0
    assert report.review is not None

    sources = service.get_sources(created.research_id)
    assert len(sources.sources) > 0
    assert len(sources.evidence) > 0


def test_list_history(service):
    service.run_research(*_new(service))
    history = service.list_history()
    assert history.total >= 1
    assert any(item.report_available for item in history.items)


def test_recover_interrupted(service, session_factory):
    from app.database.models import ResearchSession

    session = session_factory()
    record = ResearchSession(question="stale", status=RunStatus.RUNNING, stage="researching")
    session.add(record)
    session.commit()
    rid = record.id
    session.close()

    recovered = service.recover_interrupted()
    assert recovered >= 1
    status = service.get_status(rid)
    assert status.status == RunStatus.FAILED


def test_missing_llm_credentials_marks_failed(session_factory, db_path):
    """With no LLM key, the run must fail cleanly rather than fabricate."""
    settings = Settings(
        database_url=f"sqlite:///{db_path.as_posix()}",
        openai_api_key=None,
        tavily_api_key=None,
    )
    service = ResearchService(
        settings=settings,
        session_factory=session_factory,
        tool_factory=default_tool_factory,
        checkpointer_provider=lambda _s: None,
    )
    created = service.create_research(QUESTION)
    service.run_research(created.research_id, QUESTION)
    status = service.get_status(created.research_id)
    assert status.status == RunStatus.FAILED
    assert status.error is not None
    assert "OPENAI_API_KEY" in (status.error or "") or "plan" in (status.error or "").lower()


def _new(service):
    created = service.create_research(QUESTION)
    return created.research_id, QUESTION
