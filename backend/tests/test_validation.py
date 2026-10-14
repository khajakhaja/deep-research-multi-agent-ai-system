"""Test research question validation and startup configuration checks."""
from datetime import datetime

from fastapi.testclient import TestClient

from app.api.deps import get_research_service
from app.config import Settings, validate_startup_settings
from app.main import app
from app.schemas.api import ResearchCreatedResponse, ResearchHistoryResponse


class _StubService:
    def create_research(self, question, config=None):
        return ResearchCreatedResponse(
            research_id="x",
            status="pending",
            stage="pending",
            question=question,
            created_at=datetime.utcnow(),
        )

    def start(self, research_id, question, config=None):
        return None

    def list_history(self, limit=20):
        return ResearchHistoryResponse(items=[], total=0)


def test_startup_validation_warns_without_keys():
    problems = validate_startup_settings(Settings(openai_api_key=None, tavily_api_key=None))
    assert any("OPENAI_API_KEY" in p for p in problems)
    assert any("TAVILY_API_KEY" in p for p in problems)


def test_startup_validation_clean_with_keys():
    problems = validate_startup_settings(
        Settings(openai_api_key="sk-x", tavily_api_key="tvly-x")
    )
    assert problems == []


def test_api_rejects_short_question():
    app.dependency_overrides[get_research_service] = lambda: _StubService()
    client = TestClient(app)
    response = client.post("/api/research", json={"question": "abc"})
    assert response.status_code == 400
    app.dependency_overrides.clear()


def test_api_rejects_overlong_question():
    app.dependency_overrides[get_research_service] = lambda: _StubService()
    client = TestClient(app)
    response = client.post("/api/research", json={"question": "x" * 5000})
    assert response.status_code == 400
    app.dependency_overrides.clear()


def test_api_accepts_valid_question():
    app.dependency_overrides[get_research_service] = lambda: _StubService()
    client = TestClient(app)
    response = client.post(
        "/api/research",
        json={"question": "What is the impact of Agentic AI on fresher hiring in India?"},
    )
    assert response.status_code == 202
    assert response.json()["research_id"] == "x"
    app.dependency_overrides.clear()
