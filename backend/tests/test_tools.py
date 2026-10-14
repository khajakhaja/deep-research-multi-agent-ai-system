"""Tests for URL safety and the page fetcher."""
import pytest

from app.config import Settings
from app.tools import PageFetcher
from app.tools.url_utils import (
    UnsafeURLError,
    canonicalize_url,
    get_domain,
    validate_public_url,
)


def test_canonicalize_removes_tracking_and_fragment():
    url = "HTTPS://Example.com/Path/?utm_source=x&id=7#frag"
    assert canonicalize_url(url) == "https://example.com/Path?id=7"


def test_get_domain():
    assert get_domain("https://news.example.co.uk/a/b") == "news.example.co.uk"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/admin",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/",
        "http://192.168.1.1/",
        "ftp://example.com/file",
        "http://metadata.google.internal/",
    ],
)
def test_ssrf_blocked(url):
    with pytest.raises(UnsafeURLError):
        validate_public_url(url)


def test_public_url_allowed():
    # example.com resolves publicly; if DNS is unavailable this raises UnsafeURLError,
    # so we accept either a pass or a resolution failure.
    try:
        result = validate_public_url("https://example.com/page")
        assert result.startswith("https://")
    except UnsafeURLError as exc:
        assert "resolve" in str(exc).lower() or "public" in str(exc).lower()


def test_fetcher_blocks_private_hosts():
    fetcher = PageFetcher(Settings())
    page = fetcher.fetch("http://127.0.0.1/secret")
    assert page.ok is False
    assert "safety" in (page.error or "").lower()


def test_fetcher_extracts_content(respx_mock):
    # Use a public IP literal so no live DNS is required; respx intercepts HTTP.
    html = (
        "<html><head><title>Test Title</title></head><body>"
        "<article><p>Some meaningful article text about AI adoption in India "
        "that is long enough to be extracted as readable content.</p></article>"
        "</body></html>"
    )
    respx_mock.get("http://93.184.216.34/page").mock(
        return_value=__import__("httpx").Response(200, text=html)
    )
    fetcher = PageFetcher(Settings())
    page = fetcher.fetch("http://93.184.216.34/page")
    assert page.ok is True
    assert page.title == "Test Title"
    assert "AI adoption" in page.text


def test_fetcher_reports_http_error(respx_mock):
    respx_mock.get("http://93.184.216.34/missing").mock(
        return_value=__import__("httpx").Response(404, text="not found")
    )
    fetcher = PageFetcher(Settings())
    page = fetcher.fetch("http://93.184.216.34/missing")
    assert page.ok is False
    assert page.status_code == 404
