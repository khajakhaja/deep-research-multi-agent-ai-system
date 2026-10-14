"""FastAPI dependencies."""
from __future__ import annotations

from functools import lru_cache

from fastapi import Depends

from app.config import Settings, get_settings
from app.services.research_service import ResearchService


@lru_cache
def _service_for_settings() -> ResearchService:
    return ResearchService(get_settings())


def get_research_service(
    settings: Settings = Depends(get_settings),
) -> ResearchService:
    # For simplicity, cache per settings. For per-request settings changes, use
    # a factory. This matches the current design.
    return _service_for_settings()
