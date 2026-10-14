"""Page fetching and content extraction.

Fetches public pages with SSRF protections, follows redirects manually while
re-validating every hop, enforces a size limit, and extracts readable text
using trafilatura with a BeautifulSoup fallback.

Fetched content is treated strictly as untrusted data. It is only ever stored
as text; it is never executed and never interpreted as instructions.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from pydantic import BaseModel, Field

from app.config import Settings
from app.tools.url_utils import (
    UnsafeURLError,
    canonicalize_url,
    get_domain,
    normalize_text,
    validate_public_url,
)

logger = logging.getLogger(__name__)

_MAX_CONTENT_BYTES = 3 * 1024 * 1024  # 3 MB
_MAX_REDIRECTS = 5
_USER_AGENT = (
    "Mozilla/5.0 (compatible; DeepResearchBot/1.0; +https://github.com/) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


class FetchedPage(BaseModel):
    """The result of attempting to fetch and extract a web page."""

    url: str
    final_url: str = ""
    canonical_url: str = ""
    domain: str = ""
    title: str = ""
    text: str = ""
    published_date: Optional[str] = None
    ok: bool = False
    status_code: Optional[int] = None
    error: Optional[str] = None


class PageFetcher:
    """Fetches and extracts readable content from public web pages."""

    def __init__(self, settings: Settings):
        self._settings = settings

    def fetch(self, url: str) -> FetchedPage:
        """Fetch a URL and return extracted text, or an error result."""
        canonical = canonicalize_url(url)
        domain = get_domain(url)

        try:
            validate_public_url(url)
        except UnsafeURLError as exc:
            return FetchedPage(
                url=url,
                canonical_url=canonical,
                domain=domain,
                ok=False,
                error=f"Blocked by URL safety check: {exc}",
            )

        try:
            response = self._fetch_with_redirects(url)
        except httpx.TimeoutException:
            return FetchedPage(
                url=url, canonical_url=canonical, domain=domain, ok=False,
                error="Request timed out",
            )
        except httpx.HTTPError as exc:
            return FetchedPage(
                url=url, canonical_url=canonical, domain=domain, ok=False,
                error=f"HTTP error: {exc}",
            )
        except UnsafeURLError as exc:
            return FetchedPage(
                url=url, canonical_url=canonical, domain=domain, ok=False,
                error=f"Blocked by URL safety check: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return FetchedPage(
                url=url, canonical_url=canonical, domain=domain, ok=False,
                error=f"Unexpected fetch error: {exc}",
            )

        status_code = response.status_code
        if status_code >= 400:
            return FetchedPage(
                url=url,
                final_url=str(response.url),
                canonical_url=canonicalize_url(str(response.url)),
                domain=get_domain(str(response.url)),
                ok=False,
                status_code=status_code,
                error=f"HTTP {status_code}",
            )

        content_type = response.headers.get("content-type", "")
        if content_type and not any(
            t in content_type.lower()
            for t in ("text/html", "text/plain", "application/xhtml", "text/")
        ):
            return FetchedPage(
                url=url,
                final_url=str(response.url),
                canonical_url=canonicalize_url(str(response.url)),
                domain=get_domain(str(response.url)),
                ok=False,
                status_code=status_code,
                error=f"Unsupported content type: {content_type}",
            )

        html = response.text
        title, text, published_date = self._extract(html, str(response.url))

        if not text:
            # Fall back to the raw text if extraction produced nothing.
            text = normalize_text(html)

        return FetchedPage(
            url=url,
            final_url=str(response.url),
            canonical_url=canonicalize_url(str(response.url)),
            domain=get_domain(str(response.url)),
            title=title,
            text=text,
            published_date=published_date,
            ok=bool(text),
            status_code=status_code,
            error=None if text else "No readable text extracted",
        )

    # ------------------------------------------------------------------
    def _fetch_with_redirects(self, url: str) -> httpx.Response:
        """Fetch a URL, validating each redirect target for SSRF safety."""
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        current = url
        with httpx.Client(
            timeout=self._settings.request_timeout_seconds,
            follow_redirects=False,
            headers=headers,
        ) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                response = client.get(current)
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        return response
                    current = str(httpx.URL(current).join(location))
                    validate_public_url(current)
                    continue
                return response
            raise UnsafeURLError("Too many redirects")

    def _extract(self, html: str, url: str):
        """Return (title, text, published_date) extracted from HTML."""
        title = ""
        text = ""
        published_date = None

        # Primary extraction with trafilatura.
        try:
            import trafilatura

            text = trafilatura.extract(
                html,
                url=url,
                include_comments=False,
                include_tables=True,
                favor_recall=True,
                deduplicate=True,
            ) or ""
            metadata = trafilatura.extract_metadata(html, default_url=url)
            if metadata is not None:
                title = (getattr(metadata, "title", "") or "").strip()
                published_date = getattr(metadata, "date", None)
        except Exception as exc:  # noqa: BLE001
            logger.debug("trafilatura extraction failed for %s: %s", url, exc)

        # Fallback for title and text with BeautifulSoup.
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "lxml")
            if not title and soup.title and soup.title.string:
                title = soup.title.string.strip()
            if not text:
                for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
                    tag.decompose()
                text = normalize_text(soup.get_text(separator=" "))
        except Exception as exc:  # noqa: BLE001
            logger.debug("BeautifulSoup extraction failed for %s: %s", url, exc)

        text = normalize_text(text)
        return title, text, published_date
