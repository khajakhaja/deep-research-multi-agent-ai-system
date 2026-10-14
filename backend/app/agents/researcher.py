"""Research agent: generates queries, searches the web, fetches pages.

This is the tool-using core of the system. It performs real web searches and
real page fetches, deduplicates sources by canonical URL, extracts relevant
passages, and records failures explicitly instead of inventing results.
"""

from __future__ import annotations

import re
from typing import Dict, List

from pydantic import BaseModel, Field

from app.agents.base import AgentError, BaseAgent
from app.agents.context import BudgetExceeded, TimeoutExceeded
from app.schemas.research import ResearchTask, Source, SourcePassage
from app.tools import SearchError
from app.tools.url_utils import content_hash, get_domain, normalize_text

_QUERY_SYSTEM = (
    "You generate precise web search queries. Output only queries that a "
    "search engine can answer. Never include instructions to the reader."
)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "by", "as", "at", "from", "that",
    "this", "it", "its", "into", "about", "over", "how", "what", "why", "when",
    "which", "who", "will", "can", "could", "should", "would", "may", "might",
    "does", "do", "did", "has", "have", "had", "not", "their", "there", "these",
    "those", "than", "then", "also", "such", "most", "more", "some", "any",
}


class _QueryDraft(BaseModel):
    queries: List[str] = Field(default_factory=list)


def _keywords(*texts: str) -> set:
    words = set()
    for text in texts:
        for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-']+", (text or "").lower()):
            if len(word) > 3 and word not in _STOPWORDS:
                words.add(word)
    return words


def _chunk_text(text: str, size: int = 700, overlap: int = 120) -> List[str]:
    """Split text into overlapping character windows on word boundaries."""
    text = normalize_text(text)
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: List[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        if end < length:
            boundary = text.rfind(" ", start + int(size * 0.6), end)
            if boundary != -1:
                end = boundary
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks


def select_passages(
    text: str, keywords: set, max_passages: int = 3
) -> List[SourcePassage]:
    """Return the passages of ``text`` most relevant to ``keywords``."""
    chunks = _chunk_text(text)
    if not chunks:
        return []

    scored = []
    for chunk in chunks:
        chunk_words = set(re.findall(r"[a-z0-9\-']+", chunk.lower()))
        matches = len(keywords & chunk_words)
        score = matches / max(len(keywords), 1)
        scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)

    selected: List[SourcePassage] = []
    for score, chunk in scored[:max_passages]:
        selected.append(SourcePassage(text=chunk, relevance=round(float(score), 4)))
    return selected


class ResearchAgent(BaseAgent):
    """Collects evidence by searching the web and fetching pages."""

    name = "researcher"

    MAX_QUERIES_PER_TASK = 3
    MAX_SOURCES_PER_TASK = 4
    MAX_PASSAGES_PER_SOURCE = 3

    def generate_queries(self, task: ResearchTask, question: str) -> List[str]:
        """Generate focused search queries for a task."""
        prompt = (
            f"Overall research question:\n{question}\n\n"
            f"Task: {task.title}\n"
            f"Details: {task.description}\n\n"
            f"Generate up to {self.MAX_QUERIES_PER_TASK} specific, high-signal "
            "web search queries for this task. Prefer concrete, searchable "
            "phrasing."
        )
        try:
            draft = self.ctx.llm.complete_json(prompt, _QueryDraft, system=_QUERY_SYSTEM)
            queries = [q.strip() for q in draft.queries if q and q.strip()]
        except Exception as exc:  # noqa: BLE001
            self._log("Query generation failed for %s: %s", task.id, exc)
            queries = []
        return queries[: self.MAX_QUERIES_PER_TASK]

    def research_task(self, task: ResearchTask, question: str) -> Dict:
        """Research a single task; returns sources, queries, and errors."""
        queries = list(task.queries) or self.generate_queries(task, question)
        if not queries:
            queries = [question]

        keywords = _keywords(task.title, task.description, question) | _keywords(*queries)
        result = {"task_id": task.id, "queries": queries, "source_ids": [], "errors": []}
        sources_for_task: List[Source] = []

        for query in queries:
            if len(sources_for_task) >= self.MAX_SOURCES_PER_TASK:
                break
            if not self.ctx.budget.can_search():
                result["errors"].append("Search request budget exhausted for this run")
                break

            try:
                self.ctx.check_deadline()
            except TimeoutExceeded as exc:
                result["errors"].append(str(exc))
                break

            try:
                search_results = self.ctx.search.search(query)
                self.ctx.budget.consume_search()
            except SearchError as exc:
                result["errors"].append(f"Search failed for '{query}': {exc}")
                continue

            for item in search_results:
                if len(sources_for_task) >= self.MAX_SOURCES_PER_TASK:
                    break

                existing = self.ctx.registry.get_by_canonical(item.url)
                if existing is not None:
                    sources_for_task.append(existing)
                    continue

                if not self.ctx.budget.can_fetch():
                    result["errors"].append("Page fetch budget exhausted for this run")
                    break

                try:
                    self.ctx.check_deadline()
                    page = self.ctx.fetcher.fetch(item.url)
                    self.ctx.budget.consume_fetch()
                except TimeoutExceeded as exc:
                    result["errors"].append(str(exc))
                    break
                except Exception as exc:  # noqa: BLE001
                    result["errors"].append(f"Fetch error for {item.url}: {exc}")
                    continue

                if page.ok and page.text:
                    source = self.ctx.registry.register(
                        url=page.final_url or item.url,
                        title=page.title or item.title,
                        snippet=item.content,
                        domain=page.domain or get_domain(item.url),
                        published_date=page.published_date,
                        task_id=task.id,
                        query=query,
                        accessible=True,
                        content_hash_value=content_hash(page.text),
                    )
                    passages = select_passages(
                        page.text, keywords, self.MAX_PASSAGES_PER_SOURCE
                    )
                    self.ctx.registry.add_passages(source, passages)
                    sources_for_task.append(source)
                else:
                    # Record inaccessible/failed sources so they can be flagged.
                    source = self.ctx.registry.register(
                        url=item.url,
                        title=item.title,
                        snippet=item.content,
                        domain=get_domain(item.url),
                        task_id=task.id,
                        query=query,
                        accessible=False,
                    )
                    if page.error:
                        result["errors"].append(f"{item.url}: {page.error}")
                    sources_for_task.append(source)

        result["source_ids"] = [s.id for s in sources_for_task]
        self._log(
            "Researched %s: %d sources, %d errors",
            task.id,
            len(sources_for_task),
            len(result["errors"]),
        )
        return result
