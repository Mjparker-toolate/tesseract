from anthropic_docs_scraper.parse import extract_endpoints


SAMPLE = """# Messages API

Create a message.

`POST /v1/messages`

## Sessions

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/sessions` | Create a session |
| `GET`  | `/v1/sessions` | List sessions |
| `DELETE` | `/v1/sessions/{session_id}` | Delete a session |

## Misc

See also `POST /v1/messages` for the core API.
"""


def test_extract_endpoints_finds_inline_and_table_rows():
    endpoints = extract_endpoints(SAMPLE, source_url="https://example.com/doc.md")
    keys = {(e["method"], e["path"]) for e in endpoints}
    assert ("POST", "/v1/messages") in keys
    assert ("POST", "/v1/sessions") in keys
    assert ("GET", "/v1/sessions") in keys
    assert ("DELETE", "/v1/sessions/{session_id}") in keys


def test_extract_endpoints_dedupes_on_method_and_path():
    endpoints = extract_endpoints(SAMPLE, source_url="https://example.com/doc.md")
    keys = [(e["method"], e["path"]) for e in endpoints]
    assert len(keys) == len(set(keys))


def test_extract_endpoints_captures_section_heading():
    endpoints = extract_endpoints(SAMPLE, source_url="https://example.com/doc.md")
    sessions_post = next(e for e in endpoints if e["method"] == "POST" and e["path"] == "/v1/sessions")
    assert sessions_post["section"] == "Sessions"


def test_extract_endpoints_table_description_uses_last_cell():
    endpoints = extract_endpoints(SAMPLE, source_url="https://example.com/doc.md")
    sessions_get = next(e for e in endpoints if e["method"] == "GET" and e["path"] == "/v1/sessions")
    assert sessions_get["description"] == "List sessions"


def test_extract_endpoints_preserves_source_url():
    url = "https://example.com/doc.md"
    endpoints = extract_endpoints(SAMPLE, source_url=url)
    assert all(e["source_url"] == url for e in endpoints)


def test_extract_endpoints_handles_bold_method_format():
    # Anthropic's API reference uses **post** `/v1/messages` rather than
    # `POST /v1/messages`. Method is lowercase, bolded, separate from the
    # backtick-wrapped path.
    md = """## Create a Message

**post** `/v1/messages`

Send a structured list of input messages with text and/or image content.
"""
    endpoints = extract_endpoints(md, source_url="https://example.com")
    keys = {(e["method"], e["path"]) for e in endpoints}
    assert ("POST", "/v1/messages") in keys
    ep = next(e for e in endpoints if e["path"] == "/v1/messages")
    assert ep["section"] == "Create a Message"
    assert "Send a structured list" in ep["description"]
