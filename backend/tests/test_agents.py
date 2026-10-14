"""Tests for individual agents."""
import pytest

from app.agents import (
    AgentContext,
    AgentError,
    Budget,
    CoordinatorAgent,
    EvidenceVerificationAgent,
    ResearchAgent,
    ReviewerAgent,
    SourceRegistry,
    automated_excerpt_check,
)
from app.agents.coordinator import _PlanDraft, _TaskDraft
from app.agents.verifier import _ClaimItem, _ClaimsDraft
from app.schemas.research import ResearchPlan, ResearchTask, Source, SourcePassage
from tests.fakes import (
    CLAIM_TEXT,
    EXCERPT_TEXT,
    FakeFetcher,
    FakeLLM,
    FakeSearch,
    SOURCE_TEXT,
)


def _context(settings, **kwargs):
    import logging

    return AgentContext(
        settings=settings,
        llm=kwargs.get("llm", FakeLLM()),
        search=kwargs.get("search", FakeSearch()),
        fetcher=kwargs.get("fetcher", FakeFetcher()),
        research_id="t",
        logger=logging.getLogger("t"),
        budget=kwargs.get("budget", Budget(10, 10)),
        registry=kwargs.get("registry", SourceRegistry()),
    )


def test_coordinator_creates_plan(settings):
    ctx = _context(settings)
    plan = CoordinatorAgent(ctx).create_plan("Question about India AI adoption over three years")
    assert isinstance(plan, ResearchPlan)
    assert 1 <= len(plan.tasks) <= settings.max_research_tasks
    assert plan.tasks[0].id == "T1"


def test_coordinator_clamps_task_count(settings):
    def big_plan(_user):
        return _PlanDraft(
            objective="o",
            tasks=[_TaskDraft(title=f"t{i}") for i in range(20)],
        )

    ctx = _context(settings, llm=FakeLLM(overrides={"_PlanDraft": big_plan}))
    plan = CoordinatorAgent(ctx).create_plan("q")
    assert len(plan.tasks) == settings.max_research_tasks


def test_coordinator_raises_without_llm(settings):
    ctx = _context(settings, llm=FakeLLM(fail=True))
    with pytest.raises(AgentError):
        CoordinatorAgent(ctx).create_plan("q")


def test_researcher_collects_and_dedupes(settings):
    ctx = _context(settings, search=FakeSearch(num_results=3))
    task = ResearchTask(id="T1", title="Adoption", description="d", queries=["q1"])
    result = ResearchAgent(ctx).research_task(task, "q")
    assert len(result["source_ids"]) >= 1
    # run the same task again: no new sources (dedupe by canonical URL)
    before = len(ctx.registry)
    ResearchAgent(ctx).research_task(task, "q")
    assert len(ctx.registry) == before


def test_researcher_reports_search_failure(settings):
    ctx = _context(settings, search=FakeSearch(fail=True))
    task = ResearchTask(id="T1", title="Adoption", queries=["q1"])
    result = ResearchAgent(ctx).research_task(task, "q")
    assert result["source_ids"] == []
    assert any("Search failed" in e for e in result["errors"])


def test_automated_excerpt_check():
    assert automated_excerpt_check(EXCERPT_TEXT, SOURCE_TEXT) is True
    assert automated_excerpt_check("totally unrelated sentence", SOURCE_TEXT) is False
    assert automated_excerpt_check("", SOURCE_TEXT) is False


def test_verifier_marks_verified_only_when_automated_passes(settings):
    ctx = _context(settings)
    source = Source(
        id="S1",
        title="t",
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        domain="example.com",
        task_id="T1",
        passages=[SourcePassage(text=SOURCE_TEXT)],
    )
    ctx.registry._sources.append(source)  # type: ignore[attr-defined]
    evidence, errors, stats = EvidenceVerificationAgent(ctx).verify([source], "q")
    assert len(evidence) == 1
    assert evidence[0].verification_status == "verified"
    assert evidence[0].automated_check == "passed"


def test_verifier_rejects_unfindable_excerpt(settings):
    def bad_claims(_user):
        return _ClaimsDraft(
            claims=[_ClaimItem(claim="X", excerpt="not present text", support="supported")]
        )

    ctx = _context(settings, llm=FakeLLM(overrides={"_ClaimsDraft": bad_claims}))
    source = Source(
        id="S1",
        title="t",
        url="https://example.com/a",
        canonical_url="https://example.com/a",
        task_id="T1",
        passages=[SourcePassage(text=SOURCE_TEXT)],
    )
    evidence, _, _ = EvidenceVerificationAgent(ctx).verify([source], "q")
    assert evidence[0].verification_status == "unverified"
    assert evidence[0].automated_check == "failed"


def test_sufficiency_true_when_verified_coverage(settings):
    from app.agents.verifier import EvidenceVerificationAgent
    from app.schemas.research import EvidenceItem

    ctx = _context(settings)
    source = Source(id="S1", url="u", canonical_url="u", task_id="T1")
    tasks = [ResearchTask(id="T1", title="t")]
    evidence = [
        EvidenceItem(id=f"E{i}", claim="c", source_id="S1", verification_status="verified")
        for i in range(3)
    ]
    result = EvidenceVerificationAgent(ctx).assess_sufficiency(evidence, tasks, [source])
    assert result["sufficient"] is True


def test_sufficiency_false_when_uncovered(settings):
    from app.agents.verifier import EvidenceVerificationAgent
    from app.schemas.research import EvidenceItem

    ctx = _context(settings)
    tasks = [ResearchTask(id="T1", title="t"), ResearchTask(id="T2", title="u"), ResearchTask(id="T3", title="v")]
    evidence = [EvidenceItem(id="E1", claim="c", source_id="S1", verification_status="verified")]
    result = EvidenceVerificationAgent(ctx).assess_sufficiency(evidence, tasks, [])
    assert result["sufficient"] is False


def test_reviewer_flags_fabricated_citation(settings):
    ctx = _context(settings)
    source = Source(id="S1", url="https://example.com", canonical_url="https://example.com", title="t")
    markdown = (
        "## Executive Summary\n" + "word " * 40 + "[S9]\n\n"
        "## Methodology\n" + "word " * 40 + "[S1]\n\n"
        "## Findings\n" + "word " * 40 + "[S1]\n\n"
        "## Analysis\n" + "word " * 40 + "[S1]\n\n"
        "## Limitations\n" + "word " * 40 + "[S1]\n\n"
        "## Conclusion\n" + "word " * 40 + "[S1]\n"
    )
    review = ReviewerAgent(ctx).review(markdown, [source], [], "q")
    assert any("does not match any retrieved source" in i.message for i in review.issues)
    assert review.passed is False


def test_reviewer_flags_missing_sections(settings):
    ctx = _context(settings)
    source = Source(id="S1", url="https://example.com", canonical_url="https://example.com")
    review = ReviewerAgent(ctx).review("Just a paragraph with no structure.", [source], [], "q")
    categories = {i.category for i in review.issues}
    assert "structure" in categories
    assert review.passed is False


def test_writer_builds_references_from_real_sources(settings):
    from app.agents import ReportWriterAgent
    from app.schemas.research import AnalysisResult, EvidenceItem

    ctx = _context(settings, llm=FakeLLM(text_response="# T\n\n## Executive Summary\nHello [S1]\n"))
    source = Source(
        id="S1",
        url="https://real.example.com/page",
        canonical_url="https://real.example.com/page",
        title="Real Source",
    )
    plan = ResearchPlan(objective="o", tasks=[ResearchTask(id="T1", title="t")])
    analysis = AnalysisResult(summary="s")
    report = ReportWriterAgent(ctx).write(
        "q", plan, analysis,
        [EvidenceItem(id="E1", claim="c", source_id="S1", verification_status="verified")],
        [source],
    )
    assert "https://real.example.com/page" in report.markdown
    assert report.citations[0].source_id == "S1"
