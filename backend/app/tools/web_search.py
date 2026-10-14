"""Web search tool backed by Tavily.

The tool performs real web searches. Failures are surfaced as
:class:`SearchError` so the workflow can report an explicit limitation instead
of fabricating results.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from app.config import Settings

logger = logging.getLogger(__name__)


class SearchResult(BaseModel):
    """A single search result (may originate from a snippet)."""

    title: str = ""
    url: str
    content: str = ""
    score: float = 0.0


class SearchError(RuntimeError):
    """Raised when the search provider fails or is not configured."""


class WebSearchTool:
    """Wrapper around the Tavily search API."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self._settings.tavily_api_key)

    def _get_client(self):
        if not self._settings.tavily_api_key:
            raise SearchError(
                "TAVILY_API_KEY is not configured. Set it in your .env file to "
                "enable web search."
            )
        if self._client is None:
            try:
                from tavily import TavilyClient
            except ImportError as exc:  # pragma: no cover - dependency present
                raise SearchError(f"tavily-python is not installed: {exc}") from exc
            try:
                self._client = TavilyClient(api_key=self._settings.tavily_api_key)
            except Exception as exc:
                raise SearchError(f"Failed to initialise search client: {exc}") from exc
        return self._client

    def search(self, query: str, max_results: Optional[int] = None) -> List[SearchResult]:
        """Run a single web search and return normalized results."""
        if not query or not query.strip():
            return []

        client = self._get_client()
        max_results = max_results or self._settings.search_max_results

        try:
            response = client.search(
                query=query,
                max_results=max_results,
                search_depth="basic",
                include_answer=False,
                include_raw_content=False,
            )
        except Exception as exc:  # noqa: BLE001 - provider raises many types
            logger.warning("Search failed for query '%s': %s", query, exc)
            raise SearchError(f"Web search failed: {exc}") from exc

        raw_results = []
        if isinstance(response, dict):
            raw_results = response.get("results", []) or []
        elif isinstance(response, list):
            raw_results = response

        results: List[SearchResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or ""
            if not url:
                continue
            results.append(
                SearchResult(
                    title=(item.get("title") or "").strip(),
                    url=url.strip(),
                    content=(item.get("content") or "").strip(),
                    score=float(item.get("score") or 0.0),
                )
            )
        return results
