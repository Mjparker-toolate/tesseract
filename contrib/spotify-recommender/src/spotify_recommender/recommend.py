from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import spotipy

from .features import FeatureMatrix
from .mood import MoodModel
from .storage import Storage

# How much to push a track up based on play history / liked status.
FAMILIARITY_BOOST = 0.15
LIKED_BOOST = 0.05
# How heavily to penalise near-duplicate follow-ups (same primary artist).
ARTIST_REPEAT_PENALTY = 0.08


@dataclass
class Recommendation:
    track_id: str
    score: float
    reason: str
    title: str
    artists: str


def _library_ranking(
    query: np.ndarray,
    fm: FeatureMatrix,
    store: Storage,
) -> np.ndarray:
    sims = fm.matrix @ query
    sims = np.asarray(sims).ravel()
    with store.conn() as c:
        play_counts = store.play_counts(c)
        liked = set(
            r[0]
            for r in c.execute(
                "SELECT track_id FROM user_tracks WHERE source='liked'"
            )
        )
    boosts = np.zeros_like(sims)
    for i, tid in enumerate(fm.track_ids):
        pc = play_counts.get(tid, 0)
        if pc > 0:
            boosts[i] += FAMILIARITY_BOOST * min(1.0, np.log1p(pc) / 3.0)
        if tid in liked:
            boosts[i] += LIKED_BOOST
    return sims + boosts


def _diversify(
    ordered_ids: list[str],
    primary_artist: dict[str, str],
    limit: int,
) -> list[str]:
    """Penalise repeated primary artists in adjacent slots."""
    picked: list[str] = []
    seen_artist_counts: dict[str, int] = {}
    for tid in ordered_ids:
        artist = primary_artist.get(tid, "")
        if seen_artist_counts.get(artist, 0) >= 2:
            continue  # cap at 2 per artist in the final list
        picked.append(tid)
        seen_artist_counts[artist] = seen_artist_counts.get(artist, 0) + 1
        if len(picked) >= limit:
            break
    return picked


def _fetch_novel_candidates(
    sp: spotipy.Spotify,
    seed_track_ids: list[str],
    known_ids: set[str],
    n: int,
) -> list[dict]:
    """Pull fresh tracks the user hasn't seen. Falls back gracefully."""
    if not seed_track_ids or n <= 0:
        return []
    seeds = seed_track_ids[:5]  # API max
    # Try /recommendations first.
    try:
        res = sp.recommendations(seed_tracks=seeds, limit=min(100, max(n * 3, 10)))
        tracks = res.get("tracks") or []
        fresh = [t for t in tracks if t.get("id") and t["id"] not in known_ids]
        if fresh:
            return fresh[:n]
    except spotipy.SpotifyException:
        pass

    # Fallback: related-artists of seed artists → top tracks.
    collected: list[dict] = []
    try:
        seed_info = sp.tracks(seeds).get("tracks") or []
        seed_artists = {
            (t.get("artists") or [{}])[0].get("id")
            for t in seed_info
            if t.get("artists")
        }
        seed_artists.discard(None)
        for aid in list(seed_artists)[:5]:
            try:
                related = sp.artist_related_artists(aid).get("artists") or []
            except spotipy.SpotifyException:
                continue
            for ra in related[:5]:
                try:
                    top = sp.artist_top_tracks(ra["id"]).get("tracks") or []
                except spotipy.SpotifyException:
                    continue
                for t in top:
                    if t.get("id") and t["id"] not in known_ids:
                        collected.append(t)
                        if len(collected) >= n * 3:
                            break
                if len(collected) >= n * 3:
                    break
            if len(collected) >= n * 3:
                break
    except spotipy.SpotifyException:
        return collected[:n]
    return collected[:n]


def recommend(
    fm: FeatureMatrix,
    model: MoodModel,
    store: Storage,
    query_vec: np.ndarray,
    n: int,
    exploration: float = 0.15,
    sp: spotipy.Spotify | None = None,
) -> list[Recommendation]:
    scores = _library_ranking(query_vec, fm, store)
    order = np.argsort(-scores)
    ordered_ids = [fm.track_ids[i] for i in order]

    with store.conn() as c:
        primary = store.track_primary_artist(c)
        names = store.artist_name_map(c)
        track_names = {
            r[0]: r[1]
            for r in c.execute("SELECT id, name FROM tracks")
        }
        track_artists: dict[str, list[str]] = {}
        for row in c.execute(
            """SELECT track_id, artist_id FROM track_artists
               ORDER BY track_id, position"""
        ):
            track_artists.setdefault(row[0], []).append(row[1])

    n_novel = int(round(n * exploration))
    n_library = n - n_novel

    lib_ids = _diversify(ordered_ids, primary, n_library)
    id_to_score = {tid: float(scores[i]) for i, tid in enumerate(fm.track_ids)}

    recs: list[Recommendation] = []
    for tid in lib_ids:
        a_names = ", ".join(
            names.get(a, "?") for a in track_artists.get(tid, [])
        ) or "?"
        recs.append(
            Recommendation(
                track_id=tid,
                score=id_to_score.get(tid, 0.0),
                reason="library",
                title=track_names.get(tid, tid),
                artists=a_names,
            )
        )

    if n_novel > 0 and sp is not None:
        known = set(fm.track_ids)
        # Seed with the very top-matching library tracks.
        novel = _fetch_novel_candidates(sp, lib_ids, known, n_novel)
        for t in novel:
            a_names = ", ".join(
                a.get("name", "?") for a in (t.get("artists") or [])
            ) or "?"
            recs.append(
                Recommendation(
                    track_id=t["id"],
                    score=0.0,
                    reason="novel",
                    title=t.get("name", t["id"]),
                    artists=a_names,
                )
            )
    return recs
