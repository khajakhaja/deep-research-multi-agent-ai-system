"""Test graph transitions and routing."""
from app.agents.context import AgentContext, Budget, SourceRegistry
from app.constants import RunStatus
from app.graph import build_graph, build_initial_state
from tests.fakes import FakeFetcher, FakeLLM, FakeSearch

QUESTION = "Analyze Agentic AI adoption in India and fresher hiring over the next three years."


def _context(settings, llm, search, fetcher, rid):
    import logging

    return AgentContext(
        settings=settings,
        llm=llm,
        search=search,
        fetcher=fetcher,
        research_id=rid,
        logger=logging.getLogger(rid),
        budget=Budget(settings.max_search_requests_per_run, settings.max_page_fetches_per_run),
        registry=SourceRegistry(),
    )


def test_graph_reaches_finalization(graph):
    final = graph.invoke(
        build_initial_state("r1", QUESTION),
        config={"configurable": {"thread_id": "t1"}, "recursion_limit": 60},
    )
    assert final["stage"] == "completed"
    assert final["status"] in (RunStatus.COMPLETED, RunStatus.INSUFFICIENT_EVIDENCE)
    assert final["report"] is not None
    assert final["review"] is not None
    assert len(final["sources"]) > 0
    assert len(final["evidence"]) > 0


def test_graph_completes_when_evidence_sufficient(graph):
    final = graph.invoke(
        build_initial_state("r2", QUESTION),
        config={"configurable": {"thread_id": "t2"}, "recursion_limit": 60},
    )
    assert final["sufficiency"]["sufficient"] is True
    assert final["status"] == RunStatus.COMPLETED


def test_followup_research_triggered_when_insufficient(settings):
    """A search that returns nothing forces the follow-up branch."""
    vetted = _context(settings, FakeLLM(), FakeSearch(fail=True), FakeFetcher(), "r3")
    g = build_graph(vetted)
    final = g.invoke(
        build_initial_state("r3", QUESTION),
        config={"configurable": {"thread_id": "t3"}, "recursion_limit": 80},
    )
    # No evidence -> insufficient, and retry loop must have run and stopped.
    assert final["research_retries"] >= 1
    assert final["insufficient_evidence"] is True
    assert final["status"] == RunStatus.INSUFFICIENT_EVIDENCE


def test_review_retry_loop_bounded(settings, monkeypatch):
    from app.agents.reviewer import ReviewerAgent

    original = ReviewerAgent.review
    calls = {"n": 0}

    def always_fail(self, *args, **kwargs):
        calls["n"] += 1
        result = original(self, *args, **kwargs)
        result.passed = False
        return result

    monkeypatch.setattr(ReviewerAgent, "review", always_fail)

    vetted = _context(settings, FakeLLM(), FakeSearch(num_results=3), FakeFetcher(), "r4")
    g = build_graph(vetted)
    final = g.invoke(
        build_initial_state("r4", QUESTION),
        config={"configurable": {"thread_id": "t4"}, "recursion_limit": 100},
    )
    assert final["review"].passed is False
    # retries are bounded by max_review_retries
    assert final["review_retries"] <= settings.max_review_retries + 1
    assert calls["n"] <= settings.max_review_retries + 1
    assert final["status"] == RunStatus.INSUFFICIENT_EVIDENCE


def test_citations_reference_real_sources(graph):
    final = graph.invoke(
        build_initial_state("r5", QUESTION),
        config={"configurable": {"thread_id": "t5"}, "recursion_limit": 60},
    )
    report = final["report"]
    source_ids = {s.id for s in final["sources"]}
    assert report.citations
    for citation in report.citations:
        assert citation.source_id in source_ids


def test_duplicate_sources_deduped(settings):
    vetted = _context(settings, FakeLLM(), FakeSearch(num_results=5), FakeFetcher(), "r6")
    g = build_graph(vetted)
    final = g.invoke(
        build_initial_state("r6", QUESTION),
        config={"configurable": {"thread_id": "t6"}, "recursion_limit": 60},
    )
    canonical = [s.canonical_url for s in final["sources"]]
    assert len(canonical) == len(set(canonical))
