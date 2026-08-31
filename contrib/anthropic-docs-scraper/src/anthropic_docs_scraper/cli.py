"""Command-line entry point for the Anthropic docs scraper."""

from __future__ import annotations

import json
import logging
import sys
import time

import click

from . import fetch, parse, seeds


@click.command()
@click.option(
    "--output",
    type=click.Path(dir_okay=False, writable=True),
    default=None,
    help="Write JSON to PATH; default stdout.",
)
@click.option(
    "--urls",
    "url_overrides",
    multiple=True,
    help="Override the bundled seed list (repeatable).",
)
@click.option("--sleep", "sleep_s", type=float, default=0.5, help="Delay between fetches (seconds).")
@click.option("--timeout", type=float, default=10.0, help="Per-request timeout (seconds).")
@click.option("-v", "--verbose", is_flag=True, help="Log fetch progress to stderr.")
def main(
    output: str | None,
    url_overrides: tuple[str, ...],
    sleep_s: float,
    timeout: float,
    verbose: bool,
) -> None:
    """Scrape Anthropic's public API docs into a JSON endpoint list."""
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )
    log = logging.getLogger(__name__)

    urls = list(url_overrides) if url_overrides else list(seeds.DEFAULT_URLS)
    records: list[dict] = []

    for i, url in enumerate(urls):
        if not fetch.is_allowed(url):
            log.warning("robots.txt disallows %s — skipping", url)
            continue
        log.info("fetching %s", url)
        md = fetch.fetch_markdown(url, timeout=timeout)
        if md is None:
            continue
        records.extend(parse.extract_endpoints(md, source_url=url))
        if i < len(urls) - 1:
            time.sleep(sleep_s)

    # Dedupe across pages on (method, path); first occurrence wins.
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for r in records:
        key = (r["method"], r["path"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    unique.sort(key=lambda r: (r["path"], r["method"]))

    if not unique:
        log.error("no endpoints extracted")
        sys.exit(1)

    payload = json.dumps(unique, indent=2)
    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(payload + "\n")
        log.info("wrote %d endpoints to %s", len(unique), output)
    else:
        click.echo(payload)


if __name__ == "__main__":
    main()
