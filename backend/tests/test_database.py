"""Tests for the database engine and models."""
from datetime import datetime, timezone

from app.database import check_database, create_db_engine, init_db, init_engine, get_session_factory
from app.database.models import EvidenceRecord, ReportRecord, ResearchSession, SourceRecord


def test_init_and_health(db_path):
    init_engine(f"sqlite:///{db_path.as_posix()}")
    init_db()
    assert check_database() == "ok"


def test_session_roundtrip(session_factory):
    session = session_factory()
    record = ResearchSession(question="Why is the sky blue?", status="pending", stage="pending")
    session.add(record)
    session.commit()
    rid = record.id

    stored = session.get(ResearchSession, rid)
    assert stored is not None
    assert stored.question == "Why is the sky blue?"

    session.add(
        SourceRecord(
            session_id=rid,
            source_key="S1",
            title="Source",
            url="https://example.com",
            canonical_url="https://example.com",
            domain="example.com",
            retrieved_at=datetime.now(timezone.utc),
        )
    )
    session.add(
        EvidenceRecord(
            session_id=rid,
            evidence_key="E1",
            claim="A claim",
            source_id="S1",
            verification_status="verified",
        )
    )
    session.add(
        ReportRecord(session_id=rid, title="R", markdown="# hi", source_count=1, citation_count=1)
    )
    session.commit()

    assert len(stored.sources) == 1
    assert len(stored.evidence) == 1
    assert stored.report is not None
    session.close()


def test_create_engine_sqlite_creates_parent_dir(tmp_path):
    db_file = tmp_path / "nested" / "dir" / "x.db"
    engine = create_db_engine(f"sqlite:///{db_file.as_posix()}")
    assert engine is not None
    assert db_file.parent.exists()
