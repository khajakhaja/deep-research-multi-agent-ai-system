"""Deterministic fakes for external services used in tests.

These fakes let the whole workflow run without paid APIs or live internet.
They are used for unit and integration tests only; the application always uses
the real tools at runtime.
"""

from __future__ import annotations

import hashlib
from typing import Callable, Dict, List, Optional

from app.agents.coordinator import _PlanDraft, _TaskDraft
from app.agents.researcher import _QueryDraft
from app.agents.reviewer import _ReviewDraft
from app.agents.verifier import _ClaimItem, _ClaimsDraft
from app.schemas.research import AnalysisFinding, AnalysisResult
from app.tools.page_fetcher import FetchedPage
from app.tools.web_search import SearchError, SearchResult

# A passage that contains the excerpt below, so the automated support check
# passes for the fake claim.
SOURCE_TEXT = (
    "Agentic AI adoption in India has grown rapidly since 2023. Indian "
    "enterprises are deploying autonomous agents for customer support, coding, "
    "and back-office operations. Early data suggests demand for AI skills is "
    "rising across engineering and analytics roles in Indian firms."
)
CLAIM_TEXT = "Agentic AI adoption in India has grown rapidly since 2023."
EXCERPT_TEXT = "Agentic AI adoption in India has grown rapidly since 2023."


class FakeLLM:
    """A fake LLM client returning canned, schema-appropriate responses."""

    def __init__(
        self,
        overrides: Optional[Dict[str, object]] = None,
        text_response: Optional[str] = None,
        fail: bool = False,
    ):
        self.overrides = overrides or {}
        self.calls: List[tuple] = []
        self.fail = fail
        self.text_response = text_response

    def complete_text(self, user: str, system: str = "") -> str:
        self.calls.append(("text", user, system))
        if self.fail:
            raise RuntimeError("fake LLM failure")
        if self.text_response is not None:
            return self.text_response
        return _default_report()

    def complete_json(self, user, schema, system: str = "", max_retries: int = 2):  # noqa: ANN001
        self.calls.append(("json", schema.__name__, user, system))
        if self.fail:
            raise RuntimeError("fake LLM failure")
        if schema.__name__ in self.overrides:
            override = self.overrides[schema.__name__]
            if callable(override):
                return override(user)
            return override
        return _default_json(schema)


def _default_json(schema):  # noqa: ANN001
    name = schema.__name__
    if name == "_PlanDraft":
        return _PlanDraft(
            objective="Analyze Agentic AI adoption in India.",
            scope="India, 2023-2026.",
            information_needs=["adoption", "hiring", "skills"],
            tasks=[
                _TaskDraft(
                    title="Adoption of Agentic AI in India",
                    description="Current adoption levels.",
                    rationale="Core question.",
                    queries=["Agentic AI adoption India"],
                )
            ],
        )
    if name == "_QueryDraft":
        return _QueryDraft(queries=["Agentic AI adoption India statistics"])
    if name == "_ClaimsDraft":
        return _ClaimsDraft(
            claims=[
                _ClaimItem(claim=CLAIM_TEXT, excerpt=EXCERPT_TEXT, support="supported")
            ]
        )
    if name == "AnalysisResult":
        return AnalysisResult(
            summary="Adoption is growing in India.",
            findings=[
                AnalysisFinding(
                    title="Rapid adoption",
                    detail=CLAIM_TEXT,
                    supporting_source_ids=["S1"],
                    confidence="medium",
                    kind="fact",
                )
            ],
            trends=["Growing enterprise adoption"],
            limitations=["Limited public data"],
        )
    if name == "_ReviewDraft":
        return _ReviewDraft(
            passed=True,
            score=0.9,
            summary="Report is well supported.",
            issues=[],
            unsupported_claims=[],
            feedback=[],
        )
    # Generic fallback: try to instantiate defaults.
    try:
        return schema()
    except Exception:  # pragma: no cover
        raise


def _default_report() -> str:
    return (
        "# Agentic AI Adoption in India\n\n"
        "## Executive Summary\n"
        f"{CLAIM_TEXT} Indian enterprises are deploying autonomous agents for "
        "customer support, coding, and back-office operations, and early data "
        "points to rising demand for AI skills across engineering and analytics "
        "roles in Indian firms over the coming years [S1].\n\n"
        "## Methodology\n"
        "This report was produced by a multi-agent workflow that searched the "
        "web, fetched accessible pages, extracted passages, and verified each "
        "factual claim against a quoted excerpt before it was used [S1].\n\n"
        "## Findings\n"
        "Enterprise adoption of Agentic AI in India is rising across several "
        "sectors, with customer support, software engineering, and back-office "
        "operations among the earliest and most visible use cases reported by "
        "the retrieved sources [S1].\n\n"
        "## Analysis\n"
        "Taken together, the evidence points to sustained growth in adoption "
        "and in demand for supporting skills, although the volume of public, "
        "verifiable data remains limited and conclusions should be treated as "
        "provisional rather than definitive [S1].\n\n"
        "## Limitations\n"
        "Public, verifiable data on Agentic AI adoption in India is limited and "
        "the retrieved sources may over-represent early adopters; the findings "
        "in this report are therefore provisional and should be independently "
        "verified [S1].\n\n"
        "## Conclusion\n"
        "Agentic AI adoption in India is increasing, and the retrieved evidence "
        "supports a cautiously positive outlook for skills and career "
        "opportunities over the next three years [S1].\n"
    )


class FakeSearch:
    """A fake web search tool."""

    def __init__(self, num_results: int = 3, fail: bool = False, fail_queries=None):  # noqa: ANN001
        self.num_results = num_results
        self.fail = fail
        self.fail_queries = set(fail_queries or [])
        self.queries: List[str] = []

    @property
    def available(self) -> bool:
        return True

    def search(self, query: str, max_results: Optional[int] = None) -> List[SearchResult]:
        self.queries.append(query)
        if self.fail or query in self.fail_queries:
            raise SearchError(f"fake search failure for '{query}'")
        slug = hashlib.md5(query.encode("utf-8")).hexdigest()[:8]
        count = self.num_results
        results = []
        for i in range(count):
            results.append(
                SearchResult(
                    title=f"Source about {query[:30]} ({i + 1})",
                    url=f"https://example.com/{slug}/article-{i + 1}",
                    content=f"Snippet about {query}.",
                    score=0.9 - i * 0.1,
                )
            )
        return results


class FakeFetcher:
    """A fake page fetcher returning deterministic pages."""

    def __init__(self, text: str = SOURCE_TEXT, ok: bool = True, fail: bool = False):
        self.text = text
        self.ok = ok
        self.fail = fail
        self.urls: List[str] = []

    def fetch(self, url: str) -> FetchedPage:
        self.urls.append(url)
        if self.fail:
            return FetchedPage(url=url, canonical_url=url, domain="example.com", ok=False,
                               error="fake fetch failure")
        return FetchedPage(
            url=url,
            final_url=url,
            canonical_url=url,
            domain="example.com",
            title="Example Source",
            text=self.text,
            published_date="2024-01-01",
            ok=self.ok,
            status_code=200 if self.ok else 404,
            error=None if self.ok else "not found",
        )
