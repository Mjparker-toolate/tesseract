from __future__ import annotations

import time

import requests

from .storage import Storage

LASTFM_ROOT = "https://ws.audioscrobbler.com/2.0/"
MAX_TAGS_PER_ARTIST = 15


def fetch_artist_tags(
    api_key: str, artist_name: str, timeout: int = 10
) -> list[tuple[str, float]]:
    """Return (tag, weight) pairs for an artist. Weight is 0..1."""
    params = {
        "method": "artist.gettoptags",
        "artist": artist_name,
        "api_key": api_key,
        "format": "json",
        "autocorrect": 1,
    }
    try:
        r = requests.get(LASTFM_ROOT, params=params, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException:
        return []
    data = r.json()
    tags = (data.get("toptags") or {}).get("tag") or []
    out: list[tuple[str, float]] = []
    for t in tags[:MAX_TAGS_PER_ARTIST]:
        name = (t.get("name") or "").strip().lower()
        count = t.get("count")
        if not name:
            continue
        try:
            weight = max(0.0, min(1.0, float(count) / 100.0))
        except (TypeError, ValueError):
            weight = 0.0
        if weight > 0:
            out.append((name, weight))
    return out


def enrich_all_artists(
    api_key: str, store: Storage, sleep_s: float = 0.2
) -> int:
    """Populate artist_tags for every known artist that isn't tagged yet."""
    with store.conn() as c:
        rows = list(
            c.execute(
                """SELECT a.id, a.name FROM artists a
                   LEFT JOIN artist_tags t ON t.artist_id = a.id
                   WHERE t.artist_id IS NULL
                   GROUP BY a.id"""
            )
        )
    n = 0
    for row in rows:
        tags = fetch_artist_tags(api_key, row["name"])
        if tags:
            with store.conn() as c:
                store.set_artist_tags(c, row["id"], tags)
            n += 1
        time.sleep(sleep_s)
    return n
