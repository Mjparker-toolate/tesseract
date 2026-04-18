"""Parse Spotify's 'Download your data' account export.

No OAuth, no developer app, no network required. The user requests their
data from Account → Privacy → "Request your data" and feeds the resulting
folder (or zip) to this importer.

Supported files (all optional; importer tolerates any subset):

- ``YourLibrary.json``          — liked tracks and followed artists
- ``Playlist1.json`` (or many)  — user's playlists with their items
- ``StreamingHistory*.json``    — ~1 year of plays (short export)
- ``Streaming_History_Audio_*.json`` — lifetime extended history

Older exports don't include track URIs; in that case a stable synthetic
track ID of the form ``local:<hash>`` is synthesised from "artist - title"
so the storage schema still works end-to-end.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

from .storage import Storage


@dataclass
class ImportCounts:
    liked: int = 0
    playlists: int = 0
    playlist_tracks: int = 0
    plays: int = 0
    artists_seen: int = 0
    followed_artists: int = 0
    files: list[str] = field(default_factory=list)


def _synthetic_track_id(artist: str, title: str) -> str:
    key = f"{artist.strip().lower()}\0{title.strip().lower()}"
    return "local:" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def _synthetic_artist_id(name: str) -> str:
    return "local-a:" + hashlib.sha1(
        name.strip().lower().encode("utf-8")
    ).hexdigest()[:20]


def _synthetic_playlist_id(name: str, owner: str = "") -> str:
    return "local-pl:" + hashlib.sha1(
        f"{owner}\0{name}".encode("utf-8")
    ).hexdigest()[:20]


def _track_id_from_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    if ":" in uri:
        return uri.split(":")[-1]
    return uri


def _artist_id_from_uri(uri: str | None) -> str | None:
    return _track_id_from_uri(uri)


def _iter_json_files(root: Path, patterns: tuple[str, ...]) -> Iterator[Path]:
    seen: set[Path] = set()
    for pat in patterns:
        for f in sorted(root.rglob(pat)):
            if f in seen or not f.is_file():
                continue
            seen.add(f)
            yield f


def _load_json(path: Path) -> object | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _ensure_artist(
    c,
    store: Storage,
    name: str,
    uri: str | None = None,
) -> str:
    aid = _artist_id_from_uri(uri) or _synthetic_artist_id(name)
    c.execute(
        "INSERT OR IGNORE INTO artists (id, name) VALUES (?, ?)",
        (aid, name),
    )
    return aid


def _lookup_existing_track_id(
    c, artist_name: str, title: str
) -> str | None:
    """Find an existing track by (primary artist, title) — case-insensitive."""
    row = c.execute(
        """SELECT t.id
             FROM tracks t
             JOIN track_artists ta
               ON ta.track_id = t.id AND ta.position = 0
             JOIN artists a ON a.id = ta.artist_id
            WHERE LOWER(t.name) = ?
              AND LOWER(a.name) = ?
            LIMIT 1""",
        (title.strip().lower(), artist_name.strip().lower()),
    ).fetchone()
    return row[0] if row else None


def _ensure_track(
    c,
    store: Storage,
    track_uri: str | None,
    title: str,
    artist_name: str,
    album_name: str | None = None,
    duration_ms: int | None = None,
) -> str:
    tid = _track_id_from_uri(track_uri)
    if tid is None:
        # No URI — reuse any existing track with matching (artist, title)
        # so short-history and URI-bearing imports collapse onto one row.
        tid = _lookup_existing_track_id(c, artist_name, title)
    if tid is None:
        tid = _synthetic_track_id(artist_name, title)
    track = {
        "id": tid,
        "name": title,
        "popularity": None,
        "duration_ms": duration_ms,
        "explicit": False,
        "album": {"id": None, "name": album_name or "", "release_date": ""},
        "artists": [{"id": _ensure_artist(c, store, artist_name), "name": artist_name}],
    }
    # Upsert without clobbering existing popularity/release if later enriched.
    c.execute(
        """INSERT INTO tracks (id, name, popularity, duration_ms, explicit,
                                album_id, release_date, release_year)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               name=excluded.name,
               duration_ms=COALESCE(excluded.duration_ms, tracks.duration_ms)""",
        (tid, title, None, duration_ms, 0, None, "", None),
    )
    aid = _ensure_artist(c, store, artist_name)
    c.execute(
        """INSERT OR REPLACE INTO track_artists
           (track_id, artist_id, position) VALUES (?, ?, ?)""",
        (tid, aid, 0),
    )
    return tid


def _import_your_library(
    data: dict, store: Storage, counts: ImportCounts
) -> None:
    tracks = data.get("tracks") or []
    artists = data.get("artists") or []
    with store.conn() as c:
        for t in tracks:
            title = t.get("track") or t.get("trackName") or ""
            artist_name = t.get("artist") or t.get("artistName") or ""
            if not title or not artist_name:
                continue
            album = t.get("album") or ""
            tid = _ensure_track(
                c,
                store,
                t.get("uri") or t.get("trackUri"),
                title,
                artist_name,
                album,
            )
            store.mark_user_track(c, tid, "liked")
            counts.liked += 1
        for a in artists:
            name = a.get("name") or a.get("artistName")
            if not name:
                continue
            _ensure_artist(c, store, name, a.get("uri"))
            counts.followed_artists += 1


def _import_playlists(
    data: dict, store: Storage, counts: ImportCounts
) -> None:
    playlists = data.get("playlists") or []
    with store.conn() as c:
        for pl in playlists:
            name = pl.get("name") or "Untitled"
            pl_id = _synthetic_playlist_id(name)
            c.execute(
                """INSERT OR REPLACE INTO playlists
                   (id, name, owner, description) VALUES (?, ?, ?, ?)""",
                (pl_id, name, pl.get("ownerName") or "", pl.get("description")),
            )
            counts.playlists += 1
            items = pl.get("items") or []
            for it in items:
                track = it.get("track") or {}
                title = track.get("trackName") or track.get("name")
                artist_name = track.get("artistName") or (
                    (track.get("artists") or [{}])[0].get("name")
                )
                if not title or not artist_name:
                    continue
                tid = _ensure_track(
                    c,
                    store,
                    track.get("trackUri") or track.get("uri"),
                    title,
                    artist_name,
                    track.get("albumName"),
                )
                store.add_playlist_track(c, pl_id, tid, it.get("addedDate"))
                # Playlists in the export belong to the user — counts as taste.
                store.mark_user_track(c, tid, "playlist", added_at=it.get("addedDate"))
                counts.playlist_tracks += 1


def _import_streaming_history(
    data: list, store: Storage, counts: ImportCounts, extended: bool
) -> None:
    with store.conn() as c:
        for entry in data:
            if extended:
                uri = entry.get("spotify_track_uri")
                title = entry.get("master_metadata_track_name")
                artist = entry.get("master_metadata_album_artist_name")
                album = entry.get("master_metadata_album_album_name")
                ts = entry.get("ts")
                ms = entry.get("ms_played")
            else:
                uri = None
                title = entry.get("trackName")
                artist = entry.get("artistName")
                album = None
                ts = entry.get("endTime")
                ms = entry.get("msPlayed")
            if not title or not artist or not ts:
                continue
            tid = _ensure_track(c, store, uri, title, artist, album, ms)
            store.add_play(c, tid, ts)
            counts.plays += 1


def import_account_export(path: str | Path, store: Storage) -> ImportCounts:
    """Import a Spotify account-data export (directory or .zip).

    Returns per-category counts. Safe to run multiple times — all writes
    are upserts keyed on stable IDs.
    """
    src = Path(path).expanduser()
    counts = ImportCounts()

    if src.is_file() and src.suffix.lower() == ".zip":
        with TemporaryDirectory() as tmp:
            with zipfile.ZipFile(src) as zf:
                zf.extractall(tmp)
            return import_account_export(Path(tmp), store)

    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(
            f"Export path not found or not a directory: {src}"
        )

    # 1. Library
    for f in _iter_json_files(src, ("YourLibrary*.json",)):
        data = _load_json(f)
        if isinstance(data, dict):
            _import_your_library(data, store, counts)
            counts.files.append(f.name)

    # 2. Playlists
    for f in _iter_json_files(src, ("Playlist*.json",)):
        data = _load_json(f)
        if isinstance(data, dict):
            _import_playlists(data, store, counts)
            counts.files.append(f.name)

    # 3. Short streaming history (1-year export)
    for f in _iter_json_files(src, ("StreamingHistory*.json",)):
        if f.name.startswith("Streaming_History_Audio"):
            continue  # handled below
        data = _load_json(f)
        if isinstance(data, list):
            _import_streaming_history(data, store, counts, extended=False)
            counts.files.append(f.name)

    # 4. Extended streaming history (lifetime)
    for f in _iter_json_files(src, ("Streaming_History_Audio_*.json",)):
        data = _load_json(f)
        if isinstance(data, list):
            _import_streaming_history(data, store, counts, extended=True)
            counts.files.append(f.name)

    with store.conn() as c:
        counts.artists_seen = c.execute(
            "SELECT COUNT(*) FROM artists"
        ).fetchone()[0]

    return counts
