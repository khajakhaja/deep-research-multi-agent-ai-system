"""Tests for LLM wrapper behavior and reliability controls."""
import pytest

from app.config import Settings
from app.tools.llm import LLMClient, LLMError, _extract_json
from app.agents.context import Budget, BudgetExceeded, TimeoutExceeded, AgentContext
import logging


def test_llm_not_available_without_key():
    client = LLMClient(Settings(openai_api_key=None))
    assert client.available is False


def test_llm_raises_without_key():
    client = LLMClient(Settings(openai_api_key=None))
    try:
        client.complete_text("hello")
    except LLMError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected LLMError")


def test_extract_json_from_fenced_block():
    text = "```json\n{\"a\": 1, \"b\": [2, 3]}\n```"
    assert _extract_json(text) == {"a": 1, "b": [2, 3]}


def test_extract_json_from_prose():
    text = "Here is the result: {\"a\": 1} thanks"
    assert _extract_json(text) == {"a": 1}


def test_budget_enforced():
    budget = Budget(max_searches=1, max_fetches=1)
    assert budget.can_search() is True
    budget.consume_search()
    assert budget.can_search() is False
    budget.consume_fetch()
    assert budget.can_fetch() is False


def test_deadline_enforced():
    ctx = AgentContext(
        settings=Settings(),
        llm=LLMClient(Settings(openai_api_key=None)),
        search=None,  # type: ignore[arg-type]
        fetcher=None,  # type: ignore[arg-type]
        research_id="t",
        logger=logging.getLogger("t"),
        budget=Budget(1, 1),
        deadline=0.0,  # already in the past
    )
    try:
        ctx.check_deadline()
    except TimeoutExceeded:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected TimeoutExceeded")


def test_recorder_null_is_noop():
    from app.graph.recorder import NullRecorder

    recorder = NullRecorder()
    recorder.set_stage("x")
    recorder.set_status("y")
    recorder.record_execution("a", "b", "c")
    # no exceptions
