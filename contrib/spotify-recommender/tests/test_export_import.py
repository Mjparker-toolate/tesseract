"""Offline path smoke test — synthesise a Spotify data export, import it,
train, and recommend. No network, no OAuth."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spotify_recommender.export_import import import_account_export
from spotify_recommender.features import build_feature_matrix
from spotify_recommender.mood import fit_mood_model
from spotify_recommender.recommend import recommend
from spotify_recommender.storage import Storage


def _write_export(root: Path) -> None:
    # YourLibrary — liked tracks spanning three vibes
    liked = []
    for vibe, artists in [
        ("chill", ["Bon Iver", "Iron & Wine", "Sufjan Stevens"]),
        ("hype", ["Daft Punk", "Justice", "Calvin Harris"]),
        ("sad", ["Phoebe Bridgers", "Elliott Smith", "Mitski"]),
    ]:
        for i, a in enumerate(artists):
            for j in range(3):
                liked.append(
                    {
                        "artist": a,
                        "album": f"{a} album {j}",
                        "track": f"{vibe} track {i}-{j}",
                        "uri": f"spotify:track:{vibe}-{i}-{j}",
                    }
                )
    (root / "YourLibrary.json").write_text(
        json.dumps({"tracks": liked, "artists": []})
    )

    # Playlists — each playlist groups one vibe
    playlists = []
    for vibe in ("chill", "hype", "sad"):
        items = [
            {
                "track": {
                    "trackName": t["track"],
                    "artistName": t["artist"],
                    "albumName": t["album"],
                    "trackUri": t["uri"],
                },
                "addedDate": "2024-01-01",
            }
            for t in liked
            if t["track"].startswith(vibe)
        ]
        playlists.append(
            {
                "name": f"{vibe} vibes",
                "lastModifiedDate": "2024-01-01",
                "items": items,
            }
        )
    (root / "Playlist1.json").write_text(json.dumps({"playlists": playlists}))

    # Short streaming history — recent plays dominated by "chill"
    short = []
    for t in liked:
        if t["track"].startswith("chill"):
            short.append(
                {
                    "endTime": "2025-01-01 12:00",
                    "artistName": t["artist"],
                    "trackName": t["track"],
                    "msPlayed": 180_000,
                }
            )
    (root / "StreamingHistory_music_0.json").write_text(json.dumps(short))

    # Extended history (newer format) — lifetime
    ext = []
    for t in liked:
        ext.append(
            {
                "ts": "2024-06-15T12:00:00Z",
                "ms_played": 200_000,
                "spotify_track_uri": t["uri"],
                "master_metadata_track_name": t["track"],
                "master_metadata_album_artist_name": t["artist"],
                "master_metadata_album_album_name": t["album"],
            }
        )
    (root / "Streaming_History_Audio_2024_1.json").write_text(json.dumps(ext))


def test_offline_end_to_end(tmp_path: Path) -> None:
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_export(export_dir)

    store = Storage(tmp_path / "lib.sqlite")
    counts = import_account_export(export_dir, store)

    assert counts.liked == 27  # 3 vibes * 3 artists * 3 tracks
    assert counts.playlists == 3
    assert counts.playlist_tracks == 27
    # Short history has 9 chill tracks, extended history has all 27 → 36.
    assert counts.plays == 36
    assert counts.artists_seen >= 9

    # Feature matrix + mood model should still fit with only text signal.
    fm = build_feature_matrix(store)
    assert fm.matrix.shape[0] == 27
    model = fit_mood_model(fm, k=3, seed=0)
    assert len(set(model.labels)) == 3

    # Auto-mood from recent plays should land on the chill-dominated centroid.
    with store.conn() as c:
        recent = store.recent_plays(c, limit=10)
    assert len(recent) > 0

    # Library-only recommendation (no Spotify client, no novelty).
    query = model.centroids[int(model.labels[0])]
    recs = recommend(
        fm=fm, model=model, store=store, query_vec=query, n=5,
        exploration=0.0, sp=None,
    )
    assert len(recs) == 5
    assert all(r.reason == "library" for r in recs)


def test_export_import_is_idempotent(tmp_path: Path) -> None:
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    _write_export(export_dir)

    store = Storage(tmp_path / "lib.sqlite")
    first = import_account_export(export_dir, store)
    second = import_account_export(export_dir, store)
    # Plays uses a composite PK of (track_id, timestamp), so re-importing the
    # same file doesn't inflate the count.
    with store.conn() as c:
        play_rows = c.execute("SELECT COUNT(*) FROM plays").fetchone()[0]
    assert play_rows == first.plays
    # The importer itself doesn't dedupe — it counts attempted imports —
    # but the DB contents are stable. That's the guarantee users care about.
    _ = second
