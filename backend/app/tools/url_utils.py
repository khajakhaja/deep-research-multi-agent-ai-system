"""URL and text utilities shared by the research tools.

Includes SSRF protections used before fetching any user-influenced URL.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
from typing import List, Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

_TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
}

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
}

_WHITESPACE_RE = re.compile(r"\s+")


def canonicalize_url(url: str) -> str:
    """Return a normalized URL for deduplication.

    Lowercases the scheme/host, strips fragments and common tracking
    parameters, and removes a trailing slash.
    """
    if not url:
        return ""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url.strip()

    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    query_pairs = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in _TRACKING_PARAMS]
    query = urlencode(query_pairs)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    return urlunparse((scheme, netloc, path, "", query, ""))


def get_domain(url: str) -> str:
    """Return the registrable-ish hostname for a URL."""
    try:
        return urlparse(url).netloc.lower()
    except ValueError:
        return ""


def normalize_text(text: str) -> str:
    """Collapse all whitespace runs to single spaces and strip."""
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text).strip()


def content_hash(text: str) -> str:
    """Return a stable SHA-256 hash of normalized text."""
    return hashlib.sha256(normalize_text(text).encode("utf-8", errors="ignore")).hexdigest()


def _is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


class UnsafeURLError(ValueError):
    """Raised when a URL fails SSRF / scheme safety checks."""


def validate_public_url(url: str, allowed_schemes: Optional[tuple] = None) -> str:
    """Validate a URL is http(s) and resolves only to public IP addresses.

    Raises :class:`UnsafeURLError` otherwise. This mitigates SSRF against
    internal services and cloud metadata endpoints.
    """
    allowed_schemes = allowed_schemes or ("http", "https")
    if not url or not isinstance(url, str):
        raise UnsafeURLError("Empty URL")

    try:
        parsed = urlparse(url.strip())
    except ValueError as exc:
        raise UnsafeURLError(f"Malformed URL: {exc}") from exc

    if parsed.scheme.lower() not in allowed_schemes:
        raise UnsafeURLError(f"Scheme '{parsed.scheme}' is not allowed")

    hostname = parsed.hostname
    if not hostname:
        raise UnsafeURLError("URL has no hostname")

    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise UnsafeURLError(f"Host '{hostname}' is blocked")

    # If the host is already an IP literal, check it directly.
    try:
        ipaddress.ip_address(hostname)
        if not _is_public_ip(hostname):
            raise UnsafeURLError(f"IP address '{hostname}' is not public")
        return url
    except ValueError:
        pass

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UnsafeURLError(f"Could not resolve host '{hostname}': {exc}") from exc

    resolved_ips: List[str] = []
    for family, _type, _proto, _canon, sockaddr in addr_info:
        if family == socket.AF_INET:
            resolved_ips.append(sockaddr[0])
        elif family == socket.AF_INET6:
            resolved_ips.append(sockaddr[0])

    if not resolved_ips:
        raise UnsafeURLError(f"Host '{hostname}' did not resolve to any address")

    for ip_str in resolved_ips:
        # Strip IPv6 zone identifiers.
        candidate = ip_str.split("%", 1)[0]
        if not _is_public_ip(candidate):
            raise UnsafeURLError(
                f"Host '{hostname}' resolves to non-public address '{candidate}'"
            )

    return url
