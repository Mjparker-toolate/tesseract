from __future__ import annotations

import time
from typing import Iterable, Iterator

import spotipy

from .storage import Storage

# Spotify pagination / batch sizes
TRACKS_PAGE = 50
PLAYLIST_PAGE = 50
PLAYLIST_ITEMS_PAGE = 100
ARTISTS_BATCH = 50


def _iter_saved_tracks(sp: spotipy.Spotify) -> Iterator[dict]:
    offset = 0
    while True:
        res = sp.current_user_saved_tracks(limit=TRACKS_PAGE, offset=offset)
        items = res.get("items") or []
        if not items:
            return
        for item in items:
            yield item
        if not res.get("next"):
            return
        offset += TRACKS_PAGE


def _iter_playlists(sp: spotipy.Spotify) -> Iterator[dict]:
    offset = 0
    while True:
        res = sp.current_user_playlists(limit=PLAYLIST_PAGE, offset=offset)
        items = res.get("items") or []
        if not items:
            return
        for item in items:
            yield item
        if not res.get("next"):
            return
        offset += PLAYLIST_PAGE


def _iter_playlist_tracks(
    sp: spotipy.Spotify, playlist_id: str
) -> Iterator[dict]:
    offset = 0
    while True:
        res = sp.playlist_items(
            playlist_id,
            limit=PLAYLIST_ITEMS_PAGE,
            offset=offset,
            additional_types=["track"],
        )
        items = res.get("items") or []
        if not items:
            return
        for item in items:
            yield item
        if not res.get("next"):
            return
        offset += PLAYLIST_ITEMS_PAGE


def _batched(iterable: Iterable[str], n: int) -> Iterator[list[str]]:
    buf: list[str] = []
    for x in iterable:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


def ingest_liked(sp: spotipy.Spotify, store: Storage) -> int:
    n = 0
    with store.conn() as c:
        for item in _iter_saved_tracks(sp):
            track = item.get("track")
            if not track or not track.get("id"):
                continue
            store.upsert_track(c, track)
            store.mark_user_track(
                c, track["id"], "liked", added_at=item.get("added_at")
            )
            n += 1
    return n


def ingest_playlists(sp: spotipy.Spotify, store: Storage) -> tuple[int, int]:
    pls = 0
    tracks = 0
    me = sp.current_user()
    my_id = me["id"]
    for pl in _iter_playlists(sp):
        with store.conn() as c:
            store.add_playlist(c, pl)
        pls += 1
        # Include all playlists you follow, but only harvest tracks from ones
        # you own or collaborate on for "taste" signal purity. Followed
        # playlists are still recorded for co-occurrence context.
        owner = (pl.get("owner") or {}).get("id")
        collaborative = bool(pl.get("collaborative"))
        for item in _iter_playlist_tracks(sp, pl["id"]):
            track = item.get("track")
            if not track or not track.get("id"):
                continue
            with store.conn() as c:
                store.upsert_track(c, track)
                store.add_playlist_track(
                    c, pl["id"], track["id"], item.get("added_at")
                )
                if owner == my_id or collaborative:
                    store.mark_user_track(
                        c,
                        track["id"],
                        "playlist",
                        added_at=item.get("added_at"),
                    )
            tracks += 1
    return pls, tracks


def ingest_recent(sp: spotipy.Spotify, store: Storage) -> int:
    res = sp.current_user_recently_played(limit=50)
    n = 0
    with store.conn() as c:
        for item in res.get("items") or []:
            track = item.get("track")
            if not track or not track.get("id"):
                continue
            store.upsert_track(c, track)
            store.mark_user_track(
                c, track["id"], "recent", added_at=item.get("played_at")
            )
            store.add_play(c, track["id"], item["played_at"])
            n += 1
    return n


def ingest_top(sp: spotipy.Spotify, store: Storage) -> dict[str, int]:
    counts = {}
    for time_range, label in [
        ("short_term", "top_short"),
        ("medium_term", "top_medium"),
        ("long_term", "top_long"),
    ]:
        res = sp.current_user_top_tracks(limit=50, time_range=time_range)
        n = 0
        with store.conn() as c:
            for rank, track in enumerate(res.get("items") or []):
                if not track.get("id"):
                    continue
                store.upsert_track(c, track)
                store.mark_user_track(c, track["id"], label, rank=rank)
                n += 1
        counts[label] = n
    return counts


def hydrate_artists(sp: spotipy.Spotify, store: Storage) -> int:
    """Fetch genres + popularity for every artist we've seen."""
    with store.conn() as c:
        ids = [
            r[0]
            for r in c.execute(
                "SELECT id FROM artists WHERE genres IS NULL"
            )
        ]
    n = 0
    for batch in _batched(ids, ARTISTS_BATCH):
        res = sp.artists(batch)
        with store.conn() as c:
            for a in res.get("artists") or []:
                if not a or not a.get("id"):
                    continue
                store.upsert_artist_details(c, a)
                n += 1
        time.sleep(0.1)  # gentle on rate limits
    return n
