"""Shared pytest fixtures.

All external services are faked so tests need no paid APIs or live internet.
"""
import pytest

from app.agents.context import AgentContext, Budget, SourceRegistry
from app.config import Settings
from app.database.session import dispose_engine, get_session_factory, init_db, init_engine
from app.services.research_service import ResearchService
from tests.fakes import FakeFetcher, FakeLLM, FakeSearch


@pytest.fixture(autouse=True)
def _clean_engine():
    """Ensure each test starts and ends with a fresh database engine."""
    dispose_engine()
    yield
    dispose_engine()


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "research_test.db"


@pytest.fixture
def settings(db_path):
    return Settings(
        openai_api_key="sk-test-key",
        openai_model="gpt-4o-mini",
        tavily_api_key="tvly-test-key",
        database_url=f"sqlite:///{db_path.as_posix()}",
        max_research_tasks=3,
        max_search_requests_per_run=10,
        max_page_fetches_per_run=10,
        max_research_retries=1,
        max_review_retries=1,
        run_timeout_seconds=120,
    )


@pytest.fixture
def db_engine(settings):
    engine = init_engine(settings.database_url)
    init_db()
    return engine


@pytest.fixture
def session_factory(settings, db_path):
    init_engine(settings.database_url)
    init_db()
    return get_session_factory()


@pytest.fixture
def llm():
    return FakeLLM()


@pytest.fixture
def search():
    return FakeSearch(num_results=3)


@pytest.fixture
def fetcher():
    return FakeFetcher()


@pytest.fixture
def context(settings, db_path):
    """A fresh AgentContext with fakes for graph tests."""
    import logging

    return AgentContext(
        settings=settings,
        llm=FakeLLM(),
        search=FakeSearch(num_results=3),
        fetcher=FakeFetcher(),
        research_id="graph-test",
        logger=logging.getLogger("test"),
        budget=Budget(settings.max_search_requests_per_run, settings.max_page_fetches_per_run),
        registry=SourceRegistry(),
    )


@pytest.fixture
def graph(context):
    from app.graph import build_graph

    return build_graph(context)


@pytest.fixture
def service(settings, session_factory, db_path):
    """A ResearchService wired to fakes and the test database."""

    def tool_factory(_settings):
        return FakeLLM(), FakeSearch(num_results=3), FakeFetcher()

    return ResearchService(
        settings=settings,
        session_factory=session_factory,
        tool_factory=tool_factory,
        checkpointer_provider=lambda _s: None,
    )
