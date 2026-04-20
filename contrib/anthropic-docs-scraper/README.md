# anthropic-docs-scraper

Small Python CLI that fetches pages from Anthropic's public API docs and emits
a structured list of HTTP endpoints.

Self-contained sidecar under `contrib/` — independent of the Tesseract OCR
codebase. The scraper is read-only and uses no credentials.

## Install

```bash
cd contrib/anthropic-docs-scraper
pip install -e .
```

## Usage

```bash
anthropic-docs-scraper --output endpoints.json
```

Options:

| Flag | Default | Purpose |
|------|---------|---------|
| `--output PATH` | stdout | Write JSON to a file instead of printing. |
| `--urls URL` | bundled seed list | Override the seed list; repeatable. |
| `--sleep SECONDS` | `0.5` | Delay between fetches. |
| `--timeout SECONDS` | `10` | Per-request timeout. |
| `-v`, `--verbose` | off | Log fetch progress to stderr. |

Output is a JSON array of objects:

```json
[
  {
    "method": "POST",
    "path": "/v1/messages",
    "section": "Create a Message",
    "description": "Send a structured list of input messages ...",
    "source_url": "https://platform.claude.com/docs/en/api/messages.md"
  }
]
```

Records are deduplicated on `(method, path)` and sorted by path.

## Source strategy

Anthropic exposes `.md` versions of every docs page (e.g.
`platform.claude.com/docs/en/api/errors.md`). The scraper fetches markdown —
no HTML parsing. It reads `robots.txt` via `urllib.robotparser` and sets a
descriptive `User-Agent`.

## Limitations

- No recursive crawling. The seed list in `seeds.py` is the full discovery
  surface; adding new pages means editing that file or passing `--urls`.
- Depends on Anthropic continuing to publish `.md` variants. If those go away,
  the scraper needs HTML parsing added.
- Method/path matching is regex-based against `` `METHOD /v1/...` `` and
  simple markdown table rows; unusual formatting may be missed.

## Development

```bash
pip install -e .[dev]
pytest
```
