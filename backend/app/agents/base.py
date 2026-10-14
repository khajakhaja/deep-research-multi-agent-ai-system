"""Base classes and shared helpers for agents."""

from __future__ import annotations

from app.agents.context import AgentContext


class AgentError(RuntimeError):
    """Raised when an agent cannot complete its responsibility."""


class BaseAgent:
    """Common functionality shared by all agents."""

    #: Human-readable agent name used in logs and execution records.
    name: str = "agent"

    def __init__(self, context: AgentContext):
        self.ctx = context
        self.logger = context.logger

    def _log(self, message: str, *args) -> None:  # noqa: ANN001
        self.ctx.log(message, *args)
