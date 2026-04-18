"""Smoke tests that exercise the offline pipeline with a synthetic library.

No Spotify / Last.fm network calls.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from spotify_recommender.features import build_feature_matrix
from spotify_recommender.mood import fit_mood_model, resolve_mood_vector
from spotify_recommender.recommend import recommend
from spotify_recommender.storage import Storage


def _fake_track(tid, name, artist_id, artist_name, popularity=50, year=2020):
    return {
        "id": tid,
        "name": name,
        "popularity": popularity,
        "duration_ms": 200_000,
        "explicit": False,
        "album": {"id": f"alb-{tid}", "name": "Alb", "release_date": f"{year}-01-01"},
        "artists": [{"id": artist_id, "name": artist_name}],
    }


@pytest.fixture()
def store(tmp_path: Path) -> Storage:
    st = Storage(tmp_path / "lib.sqlite")
    # Build three vibe groups with distinct artists/genres.
    groups = [
        ("chill", ["lofi", "ambient", "chillhop"]),
        ("hype", ["house", "edm", "dance"]),
        ("sad", ["sad", "indie", "singer-songwriter"]),
    ]
    with st.conn() as c:
        for g_idx, (vibe, genres) in enumerate(groups):
            for i in range(8):
                artist_id = f"art-{vibe}-{i}"
                track = _fake_track(
                    f"trk-{vibe}-{i}",
                    f"{vibe} song {i}",
                    artist_id,
                    f"{vibe}-artist-{i}",
                )
                st.upsert_track(c, track)
                st.upsert_artist_details(
                    c,
                    {
                        "id": artist_id,
                        "name": f"{vibe}-artist-{i}",
                        "popularity": 40 + i,
                        "genres": genres,
                    },
                )
                st.mark_user_track(c, track["id"], "liked")
    return st


def test_feature_matrix_has_expected_shape(store: Storage) -> None:
    fm = build_feature_matrix(store)
    assert fm.matrix.shape[0] == 24
    assert fm.matrix.shape[1] > 0
    # Rows are L2-normalised.
    norms = np.linalg.norm(fm.matrix.toarray(), axis=1)
    assert np.allclose(norms, 1.0, atol=1e-6)


def test_mood_model_separates_vibes(store: Storage) -> None:
    fm = build_feature_matrix(store)
    model = fit_mood_model(fm, k=3, seed=0)
    assert len(set(model.labels)) == 3
    # Each synthetic vibe group should land predominantly in one cluster.
    for vibe in ("chill", "hype", "sad"):
        idxs = [i for i, tid in enumerate(fm.track_ids) if vibe in tid]
        labels = model.labels[idxs]
        # >= 6 of 8 tracks share the same cluster label
        _, counts = np.unique(labels, return_counts=True)
        assert counts.max() >= 6


def test_recommend_returns_library_tracks(store: Storage) -> None:
    fm = build_feature_matrix(store)
    model = fit_mood_model(fm, k=3, seed=0)
    # Pick the cluster dominated by the "chill" tracks.
    chill_idx = None
    for i in range(3):
        members = [fm.track_ids[j] for j in range(len(fm.track_ids)) if model.labels[j] == i]
        if sum("chill" in m for m in members) >= 6:
            chill_idx = i
            break
    assert chill_idx is not None

    query = model.centroids[chill_idx]
    recs = recommend(
        fm=fm,
        model=model,
        store=store,
        query_vec=query,
        n=5,
        exploration=0.0,  # no network
        sp=None,
    )
    assert len(recs) == 5
    # Most recommendations for the chill centroid should be chill tracks.
    chill_hits = sum(1 for r in recs if "chill" in r.track_id)
    assert chill_hits >= 3


def test_resolve_mood_by_name(store: Storage) -> None:
    fm = build_feature_matrix(store)
    model = fit_mood_model(fm, k=3, seed=0)
    # One of the cluster names or top terms should match a vibe word.
    matched = False
    for vibe in ("chill", "hype", "sad", "lofi", "edm", "indie"):
        try:
            vec, label = resolve_mood_vector(vibe, model, fm)
            assert vec.shape[0] == fm.matrix.shape[1]
            matched = True
            break
        except ValueError:
            continue
    assert matched, "expected at least one vibe word to resolve"
