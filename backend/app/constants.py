"""Shared constants: workflow stages, statuses, and verification states.

Keeping these in one module avoids magic strings drifting apart between the
agents, the graph, the database layer, and the API/frontend.
"""

from __future__ import annotations


class RunStatus:
    """Lifecycle status of a research session."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"

    ALL = (PENDING, RUNNING, COMPLETED, FAILED, INSUFFICIENT_EVIDENCE)
    TERMINAL = (COMPLETED, FAILED, INSUFFICIENT_EVIDENCE)


class Stage:
    """Named workflow stages used for progress reporting."""

    PENDING = "pending"
    VALIDATING = "validating"
    PLANNING = "planning"
    RESEARCHING = "researching"
    VERIFYING = "verifying"
    FOLLOWUP = "followup_research"
    ANALYZING = "analyzing"
    WRITING = "writing"
    REVIEWING = "reviewing"
    REVISING = "revising"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"

    ORDERED = (
        VALIDATING,
        PLANNING,
        RESEARCHING,
        VERIFYING,
        ANALYZING,
        WRITING,
        REVIEWING,
        FINALIZING,
        COMPLETED,
    )


class TaskStatus:
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class VerificationStatus:
    """Verification state attached to a source or a piece of evidence."""

    VERIFIED = "verified"
    DISPUTED = "disputed"
    UNVERIFIED = "unverified"
    UNSUPPORTED = "unsupported"


class SupportLevel:
    """How well a source supports a claim."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"
