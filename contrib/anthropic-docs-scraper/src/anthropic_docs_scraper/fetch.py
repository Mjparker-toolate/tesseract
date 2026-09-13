"""HTTP fetching with robots.txt checks and polite defaults."""

from __future__ import annotations

import logging
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

logger = logging.getLogger(__name__)

USER_AGENT = (
    "anthropic-docs-scraper/0.1 "
    "(+https://github.com/Mjparker-toolate/tesseract/tree/main/contrib/anthropic-docs-scraper)"
)

_robots_cache: dict[str, RobotFileParser] = {}


def _robots_for(url: str) -> RobotFileParser:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(origin)
    if rp is not None:
        return rp
    rp = RobotFileParser()
    robots_url = urljoin(origin, "/robots.txt")
    rp.set_url(robots_url)
    # Fetch robots.txt with our real User-Agent (some sites 403 Python-urllib).
    # A 403 on robots.txt itself makes robotparser disallow everything, so we
    # bypass urllib's default fetch and feed the content in directly.
    try:
        resp = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=10)
        if resp.status_code == 200:
            rp.parse(resp.text.splitlines())
        elif resp.status_code in (401, 403):
            rp.disallow_all = True
        else:
            rp.allow_all = True
    except requests.RequestException as exc:
        logger.warning("failed to read robots.txt for %s: %s — defaulting to allow", origin, exc)
        rp.allow_all = True
    _robots_cache[origin] = rp
    return rp


def is_allowed(url: str) -> bool:
    """Return True if robots.txt permits fetching *url* for our User-Agent."""
    return _robots_for(url).can_fetch(USER_AGENT, url)


def fetch_markdown(url: str, *, timeout: float = 10.0) -> str | None:
    """Fetch *url* and return the body text, or None on any failure.

    Errors are logged, not raised, so a single broken URL doesn't kill a
    multi-URL scrape.
    """
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("fetch failed for %s: %s", url, exc)
        return None
    return resp.text
