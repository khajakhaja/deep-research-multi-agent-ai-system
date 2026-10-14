"""Shared runtime context for agents.

The :class:`AgentContext` bundles the read-only tools and run-scoped state
that every agent needs. The :class:`Budget` enforces per-run limits on search
requests and page fetches, and the :class:`SourceRegistry` guarantees global
source id assignment and URL deduplication.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from app.config import Settings
from app.schemas.research import Source, SourcePassage
from app.tools import LLMClient, PageFetcher, WebSearchTool
from app.tools.url_utils import canonicalize_url


class BudgetExceeded(RuntimeError):
    """Raised when a per-run budget (searches or fetches) is exhausted."""


class TimeoutExceeded(RuntimeError):
    """Raised when the overall run deadline has passed."""


@dataclass
class Budget:
    """Mutable counters enforcing per-run cost limits."""

    max_searches: int
    max_fetches: int
    searches_used: int = 0
    fetches_used: int = 0

    def can_search(self) -> bool:
        return self.searches_used < self.max_searches

    def can_fetch(self) -> bool:
        return self.fetches_used < self.max_fetches

    def consume_search(self) -> None:
        self.searches_used += 1

    def consume_fetch(self) -> None:
        self.fetches_used += 1

    def to_dict(self) -> Dict[str, int]:
        return {
            "max_searches": self.max_searches,
            "max_fetches": self.max_fetches,
            "searches_used": self.searches_used,
            "fetches_used": self.fetches_used,
        }


class SourceRegistry:
    """Assigns stable ``S#`` ids and deduplicates sources by canonical URL."""

    def __init__(self, existing: Optional[List[Source]] = None):
        self._sources: List[Source] = []
        self._by_canonical: Dict[str, Source] = {}
        self._counter = 0
        for source in existing or []:
            self._sources.append(source)
            self._by_canonical[source.canonical_url or source.url] = source
            self._bump_counter(source.id)

    def _bump_counter(self, source_id: str) -> None:
        if source_id.startswith("S"):
            try:
                self._counter = max(self._counter, int(source_id[1:]))
            except ValueError:
                pass

    def next_id(self) -> str:
        self._counter += 1
        return f"S{self._counter}"

    def get_by_canonical(self, url: str) -> Optional[Source]:
        return self._by_canonical.get(canonicalize_url(url))

    def register(
        self,
        url: str,
        title: str = "",
        snippet: str = "",
        domain: str = "",
        published_date: Optional[str] = None,
        task_id: Optional[str] = None,
        query: Optional[str] = None,
        accessible: bool = True,
        content_hash_value: str = "",
    ) -> Source:
        """Register a source, returning an existing one if the URL is a dupe."""
        canonical = canonicalize_url(url)
        existing = self._by_canonical.get(canonical)
        if existing is not None:
            # Enrich missing metadata on the existing record.
            if not existing.title and title:
                existing.title = title
            if not existing.snippet and snippet:
                existing.snippet = snippet
            if not existing.published_date and published_date:
                existing.published_date = published_date
            return existing

        source = Source(
            id=self.next_id(),
            title=title,
            url=url,
            canonical_url=canonical,
            domain=domain,
            retrieved_at=datetime.now(timezone.utc),
            published_date=published_date,
            snippet=snippet,
            task_id=task_id,
            query=query,
            accessible=accessible,
            content_hash=content_hash_value,
        )
        self._sources.append(source)
        self._by_canonical[canonical] = source
        return source

    def add_passages(self, source: Source, passages: List[SourcePassage]) -> None:
        existing_texts = {p.text for p in source.passages}
        for passage in passages:
            if passage.text not in existing_texts:
                source.passages.append(passage)
                existing_texts.add(passage.text)

    def all(self) -> List[Source]:
        return list(self._sources)

    def accessible(self) -> List[Source]:
        return [s for s in self._sources if s.accessible]

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._sources)


@dataclass
class AgentContext:
    """Everything an agent needs to do its work."""

    settings: Settings
    llm: LLMClient
    search: WebSearchTool
    fetcher: PageFetcher
    research_id: str
    logger: logging.Logger
    budget: Budget
    registry: SourceRegistry = field(default_factory=SourceRegistry)
    deadline: Optional[float] = None
    errors: List[str] = field(default_factory=list)

    def check_deadline(self) -> None:
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise TimeoutExceeded(
                f"Research run exceeded its {self.settings.run_timeout_seconds}s budget"
            )

    def log(self, message: str, *args) -> None:  # noqa: ANN001
        self.logger.info(message, *args, extra={"research_id": self.research_id})


def truncate(text: str, max_chars: int) -> str:
    """Truncate ``text`` to ``max_chars`` characters with an ellipsis."""
    if text is None:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "\u2026"
