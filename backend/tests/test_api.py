"""Test API endpoints with fake service."""
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import get_research_service
from app.schemas.api import (
    ResearchCreatedResponse,
    ResearchStatusResponse,
    ProgressInfo,
    ReportResponse,
    SourceListResponse,
    ResearchHistoryResponse,
    HealthResponse,
)
from datetime import datetime


class StubService:
    def __init__(self):
        self.started = []
    def create_research(self, q, c=None):
        from app.schemas.api import ResearchCreatedResponse
        return ResearchCreatedResponse(research_id="rid123", status="pending", stage="pending", question=q, created_at=datetime.utcnow())
    def start(self, rid, q, c=None):
        self.started.append(rid)
    def get_status(self, rid):
        if rid != "rid123":
            return None
        return ResearchStatusResponse(
            research_id="rid123",
            status="completed",
            stage="completed",
            question="Q",
            tasks=[],
            progress=ProgressInfo(),
            error=None,
            insufficient_evidence=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            finished_at=datetime.utcnow(),
        )
    def get_report(self, rid):
        if rid != "rid123":
            return None
        return ReportResponse(research_id="rid123", status="completed", markdown="# ok")
    def get_sources(self, rid):
        if rid != "rid123":
            return None
        from app.schemas.api import SourceListResponse
        return SourceListResponse(research_id="rid123", sources=[], evidence=[])
    def list_history(self, limit=20):
        return ResearchHistoryResponse(items=[], total=0)
    def recover_interrupted(self): return 0
    def shutdown(self): pass


def test_health():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"


def test_create_research_accepted():
    app.dependency_overrides[get_research_service] = lambda: StubService()
    client = TestClient(app)
    r = client.post("/api/research", json={"question": "What is the impact of Agentic AI on fresher hiring in India?"})
    assert r.status_code == 202
    data = r.json()
    assert data["research_id"] == "rid123"
    app.dependency_overrides.clear()


def test_get_status_404():
    app.dependency_overrides[get_research_service] = lambda: StubService()
    client = TestClient(app)
    r = client.get("/api/research/doesnotexist")
    assert r.status_code == 404
    app.dependency_overrides.clear()


def test_get_report_ok():
    app.dependency_overrides[get_research_service] = lambda: StubService()
    client = TestClient(app)
    r = client.get("/api/research/rid123/report")
    assert r.status_code == 200
    assert "# ok" in r.json()["markdown"]
    app.dependency_overrides.clear()


def test_get_sources_ok():
    app.dependency_overrides[get_research_service] = lambda: StubService()
    client = TestClient(app)
    r = client.get("/api/research/rid123/sources")
    assert r.status_code == 200
    app.dependency_overrides.clear()
