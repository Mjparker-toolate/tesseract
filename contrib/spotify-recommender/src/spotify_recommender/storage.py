from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    popularity INTEGER,
    duration_ms INTEGER,
    explicit INTEGER,
    album_id TEXT,
    release_date TEXT,
    release_year INTEGER
);

CREATE TABLE IF NOT EXISTS artists (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    popularity INTEGER,
    genres TEXT  -- JSON array
);

CREATE TABLE IF NOT EXISTS albums (
    id TEXT PRIMARY KEY,
    name TEXT,
    release_date TEXT
);

CREATE TABLE IF NOT EXISTS track_artists (
    track_id TEXT NOT NULL,
    artist_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    PRIMARY KEY (track_id, artist_id)
);

CREATE TABLE IF NOT EXISTS playlists (
    id TEXT PRIMARY KEY,
    name TEXT,
    owner TEXT,
    description TEXT
);

CREATE TABLE IF NOT EXISTS playlist_tracks (
    playlist_id TEXT NOT NULL,
    track_id TEXT NOT NULL,
    added_at TEXT,
    PRIMARY KEY (playlist_id, track_id)
);

-- Where this track was seen: liked, top_short, top_medium, top_long, recent
CREATE TABLE IF NOT EXISTS user_tracks (
    track_id TEXT NOT NULL,
    source TEXT NOT NULL,
    added_at TEXT,
    rank INTEGER,
    PRIMARY KEY (track_id, source)
);

CREATE TABLE IF NOT EXISTS plays (
    track_id TEXT NOT NULL,
    played_at TEXT NOT NULL,
    PRIMARY KEY (track_id, played_at)
);

CREATE TABLE IF NOT EXISTS artist_tags (
    artist_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    weight REAL NOT NULL,
    PRIMARY KEY (artist_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_track_artists_track ON track_artists(track_id);
CREATE INDEX IF NOT EXISTS idx_track_artists_artist ON track_artists(artist_id);
CREATE INDEX IF NOT EXISTS idx_playlist_tracks_track ON playlist_tracks(track_id);
CREATE INDEX IF NOT EXISTS idx_plays_track ON plays(track_id);
"""


class Storage:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(self._path)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ---------- writers ----------

    def upsert_track(self, c: sqlite3.Connection, track: dict) -> None:
        release = (track.get("album") or {}).get("release_date") or ""
        year = int(release[:4]) if release[:4].isdigit() else None
        c.execute(
            """INSERT INTO tracks (id, name, popularity, duration_ms, explicit,
                                    album_id, release_date, release_year)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   name=excluded.name,
                   popularity=excluded.popularity,
                   duration_ms=excluded.duration_ms,
                   explicit=excluded.explicit,
                   album_id=excluded.album_id,
                   release_date=excluded.release_date,
                   release_year=excluded.release_year""",
            (
                track["id"],
                track.get("name", ""),
                track.get("popularity"),
                track.get("duration_ms"),
                1 if track.get("explicit") else 0,
                (track.get("album") or {}).get("id"),
                release,
                year,
            ),
        )
        for i, a in enumerate(track.get("artists") or []):
            if not a.get("id"):
                continue
            c.execute(
                "INSERT OR IGNORE INTO artists (id, name) VALUES (?, ?)",
                (a["id"], a.get("name", "")),
            )
            c.execute(
                """INSERT OR REPLACE INTO track_artists
                   (track_id, artist_id, position) VALUES (?, ?, ?)""",
                (track["id"], a["id"], i),
            )
        album = track.get("album") or {}
        if album.get("id"):
            c.execute(
                """INSERT OR REPLACE INTO albums (id, name, release_date)
                   VALUES (?, ?, ?)""",
                (album["id"], album.get("name"), album.get("release_date")),
            )

    def upsert_artist_details(
        self, c: sqlite3.Connection, artist: dict
    ) -> None:
        c.execute(
            """INSERT INTO artists (id, name, popularity, genres)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   name=excluded.name,
                   popularity=excluded.popularity,
                   genres=excluded.genres""",
            (
                artist["id"],
                artist.get("name", ""),
                artist.get("popularity"),
                json.dumps(artist.get("genres") or []),
            ),
        )

    def mark_user_track(
        self,
        c: sqlite3.Connection,
        track_id: str,
        source: str,
        added_at: str | None = None,
        rank: int | None = None,
    ) -> None:
        c.execute(
            """INSERT INTO user_tracks (track_id, source, added_at, rank)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(track_id, source) DO UPDATE SET
                   added_at=COALESCE(excluded.added_at, user_tracks.added_at),
                   rank=COALESCE(excluded.rank, user_tracks.rank)""",
            (track_id, source, added_at, rank),
        )

    def add_playlist(self, c: sqlite3.Connection, pl: dict) -> None:
        c.execute(
            """INSERT OR REPLACE INTO playlists (id, name, owner, description)
               VALUES (?, ?, ?, ?)""",
            (
                pl["id"],
                pl.get("name"),
                (pl.get("owner") or {}).get("id"),
                pl.get("description"),
            ),
        )

    def add_playlist_track(
        self,
        c: sqlite3.Connection,
        playlist_id: str,
        track_id: str,
        added_at: str | None,
    ) -> None:
        c.execute(
            """INSERT OR REPLACE INTO playlist_tracks
               (playlist_id, track_id, added_at) VALUES (?, ?, ?)""",
            (playlist_id, track_id, added_at),
        )

    def add_play(
        self, c: sqlite3.Connection, track_id: str, played_at: str
    ) -> None:
        c.execute(
            "INSERT OR IGNORE INTO plays (track_id, played_at) VALUES (?, ?)",
            (track_id, played_at),
        )

    def set_artist_tags(
        self,
        c: sqlite3.Connection,
        artist_id: str,
        tags: Iterable[tuple[str, float]],
    ) -> None:
        c.execute("DELETE FROM artist_tags WHERE artist_id=?", (artist_id,))
        c.executemany(
            "INSERT INTO artist_tags (artist_id, tag, weight) VALUES (?, ?, ?)",
            [(artist_id, t, float(w)) for t, w in tags],
        )

    # ---------- readers ----------

    def all_track_ids(self, c: sqlite3.Connection) -> list[str]:
        return [r[0] for r in c.execute("SELECT id FROM tracks")]

    def all_artist_ids(self, c: sqlite3.Connection) -> list[str]:
        return [r[0] for r in c.execute("SELECT id FROM artists")]

    def user_track_ids(self, c: sqlite3.Connection) -> list[str]:
        return [
            r[0]
            for r in c.execute(
                "SELECT DISTINCT track_id FROM user_tracks"
            )
        ]

    def artist_genres(self, c: sqlite3.Connection) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for row in c.execute("SELECT id, genres FROM artists WHERE genres IS NOT NULL"):
            try:
                out[row["id"]] = json.loads(row["genres"]) or []
            except json.JSONDecodeError:
                out[row["id"]] = []
        return out

    def artist_tags(
        self, c: sqlite3.Connection
    ) -> dict[str, list[tuple[str, float]]]:
        out: dict[str, list[tuple[str, float]]] = {}
        for row in c.execute("SELECT artist_id, tag, weight FROM artist_tags"):
            out.setdefault(row["artist_id"], []).append(
                (row["tag"], row["weight"])
            )
        return out

    def track_rows(self, c: sqlite3.Connection) -> list[sqlite3.Row]:
        return list(
            c.execute(
                """SELECT t.id, t.name, t.popularity, t.duration_ms,
                          t.release_year,
                          GROUP_CONCAT(ta.artist_id) AS artist_ids
                   FROM tracks t
                   LEFT JOIN track_artists ta ON ta.track_id = t.id
                   GROUP BY t.id"""
            )
        )

    def artist_name_map(self, c: sqlite3.Connection) -> dict[str, str]:
        return {r[0]: r[1] for r in c.execute("SELECT id, name FROM artists")}

    def track_primary_artist(
        self, c: sqlite3.Connection
    ) -> dict[str, str]:
        out: dict[str, str] = {}
        for row in c.execute(
            """SELECT track_id, artist_id FROM track_artists
               WHERE position = 0"""
        ):
            out[row[0]] = row[1]
        return out

    def play_counts(self, c: sqlite3.Connection) -> dict[str, int]:
        return {
            r[0]: r[1]
            for r in c.execute(
                "SELECT track_id, COUNT(*) FROM plays GROUP BY track_id"
            )
        }

    def recent_plays(
        self, c: sqlite3.Connection, limit: int
    ) -> list[str]:
        return [
            r[0]
            for r in c.execute(
                "SELECT track_id FROM plays ORDER BY played_at DESC LIMIT ?",
                (limit,),
            )
        ]
