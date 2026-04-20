"""Extract HTTP endpoint definitions from Anthropic docs markdown."""

from __future__ import annotations

import re

# Methods restricted to a known set to avoid false positives on prose words.
_METHODS = "GET|POST|PUT|PATCH|DELETE"
_PATH_CHARS = r"/v1/[A-Za-z0-9_./{}\-]+"

# `METHOD /v1/...` in a single inline code span.
_INLINE_RE = re.compile(
    rf"`(?P<method>{_METHODS})\s+(?P<path>{_PATH_CHARS})`",
    re.IGNORECASE,
)
# `**method**` (bold, often lowercase) followed by a backtick path — the
# format Anthropic's API reference pages use, e.g. `**post** /v1/messages`.
_BOLD_RE = re.compile(
    rf"\*\*(?P<method>{_METHODS})\*\*\s+`(?P<path>{_PATH_CHARS})`",
    re.IGNORECASE,
)
# Markdown-table row: `| POST | /v1/messages | ... |`.
_TABLE_RE = re.compile(
    rf"^\s*\|\s*`?(?P<method>{_METHODS})`?\s*\|\s*`?(?P<path>{_PATH_CHARS})`?\s*\|(?P<rest>.*?)\|?\s*$",
    re.MULTILINE | re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(?P<title>.+?)\s*$", re.MULTILINE)


def _preceding_heading(md: str, offset: int) -> str | None:
    """Return the nearest heading at or before *offset*."""
    last = None
    for m in _HEADING_RE.finditer(md, 0, offset):
        last = m
    return last.group("title").strip() if last else None


def _context_sentence(md: str, start: int, end: int) -> str:
    """Return a short description near the match.

    Prefers the table row's own trailing cell; otherwise the line itself, then
    the following non-blank line.
    """
    line_start = md.rfind("\n", 0, start) + 1
    line_end = md.find("\n", end)
    if line_end == -1:
        line_end = len(md)
    line = md[line_start:line_end].strip()

    # Strip markdown table pipes if present, keep the last populated cell.
    if line.startswith("|"):
        cells = [c.strip() for c in line.strip("|").split("|")]
        tail = [c for c in cells[2:] if c]
        if tail:
            return tail[-1]

    # Otherwise, look ahead to the first non-empty, non-heading line.
    after = md[line_end + 1 : line_end + 500]
    for candidate in after.split("\n"):
        stripped = candidate.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("```"):
            return stripped
    return line


def extract_endpoints(md: str, source_url: str) -> list[dict]:
    """Extract endpoint records from a markdown document.

    Returns a list of dicts with keys: method, path, section, description,
    source_url. Deduplicated on (method, path); the first occurrence wins.
    """
    seen: set[tuple[str, str]] = set()
    out: list[dict] = []

    for regex in (_TABLE_RE, _BOLD_RE, _INLINE_RE):
        for m in regex.finditer(md):
            method = m.group("method").upper()
            path = m.group("path")
            key = (method, path)
            if key in seen:
                continue
            seen.add(key)
            section = _preceding_heading(md, m.start())
            description = _context_sentence(md, m.start(), m.end())
            out.append(
                {
                    "method": method,
                    "path": path,
                    "section": section,
                    "description": description,
                    "source_url": source_url,
                }
            )

    return out
