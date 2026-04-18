from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

from .storage import Storage

# Feature mix weights — tuned by intuition, exposed for easy adjustment.
W_GENRE = 1.0
W_TAG = 0.9
W_TFIDF = 0.6
W_NUMERIC = 0.25


@dataclass
class FeatureMatrix:
    track_ids: list[str]
    matrix: csr_matrix  # shape (n_tracks, n_features), L2-normalised rows
    vectorizer: TfidfVectorizer
    genre_vocab: list[str]
    tag_vocab: list[str]
    numeric_stats: dict[str, tuple[float, float]]  # name -> (mean, std)


def _scale(values: np.ndarray) -> tuple[np.ndarray, float, float]:
    mean = float(np.nanmean(values)) if values.size else 0.0
    std = float(np.nanstd(values)) if values.size else 1.0
    if std < 1e-9:
        std = 1.0
    scaled = np.nan_to_num((values - mean) / std, nan=0.0)
    return scaled, mean, std


def build_feature_matrix(store: Storage) -> FeatureMatrix:
    with store.conn() as c:
        tracks = store.track_rows(c)
        artist_genres = store.artist_genres(c)
        artist_tags = store.artist_tags(c)
        artist_names = store.artist_name_map(c)

    if not tracks:
        raise RuntimeError(
            "No tracks in cache. Run `spotify-recommender ingest` first."
        )

    # Build vocabularies.
    genre_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    for row in tracks:
        a_ids = (row["artist_ids"] or "").split(",") if row["artist_ids"] else []
        for aid in a_ids:
            for g in artist_genres.get(aid, []):
                genre_counter[g.lower()] += 1
            for tag, _ in artist_tags.get(aid, []):
                tag_counter[tag] += 1

    genre_vocab = [g for g, _ in genre_counter.most_common()]
    tag_vocab = [t for t, _ in tag_counter.most_common()]
    genre_idx = {g: i for i, g in enumerate(genre_vocab)}
    tag_idx = {t: i for i, t in enumerate(tag_vocab)}

    # Multi-hot / weighted matrices.
    n = len(tracks)
    genre_rows, genre_cols, genre_vals = [], [], []
    tag_rows, tag_cols, tag_vals = [], [], []
    texts: list[str] = []
    pop = np.zeros(n)
    year = np.zeros(n)
    dur = np.zeros(n)
    track_ids: list[str] = []

    for i, row in enumerate(tracks):
        track_ids.append(row["id"])
        a_ids = (row["artist_ids"] or "").split(",") if row["artist_ids"] else []
        artists_for_text: list[str] = []
        gvec: dict[int, float] = {}
        tvec: dict[int, float] = {}
        for aid in a_ids:
            if aid in artist_names:
                artists_for_text.append(artist_names[aid])
            for g in artist_genres.get(aid, []):
                idx = genre_idx[g.lower()]
                gvec[idx] = 1.0  # multi-hot; artists add no extra weight
            for tag, w in artist_tags.get(aid, []):
                idx = tag_idx[tag]
                tvec[idx] = max(tvec.get(idx, 0.0), float(w))
        for idx, v in gvec.items():
            genre_rows.append(i)
            genre_cols.append(idx)
            genre_vals.append(v)
        for idx, v in tvec.items():
            tag_rows.append(i)
            tag_cols.append(idx)
            tag_vals.append(v)

        text_parts = [row["name"] or ""]
        text_parts.extend(artists_for_text)
        text_parts.extend(g for aid in a_ids for g in artist_genres.get(aid, []))
        text_parts.extend(
            tag for aid in a_ids for tag, _ in artist_tags.get(aid, [])
        )
        texts.append(" ".join(text_parts).lower())

        pop[i] = float(row["popularity"] or 0)
        year[i] = float(row["release_year"] or 0)
        dur[i] = float(row["duration_ms"] or 0) / 1000.0  # seconds

    n_genres = max(1, len(genre_vocab))
    n_tags = max(1, len(tag_vocab))
    genre_m = csr_matrix(
        (genre_vals, (genre_rows, genre_cols)), shape=(n, n_genres)
    )
    tag_m = csr_matrix(
        (tag_vals, (tag_rows, tag_cols)), shape=(n, n_tags)
    )

    vectorizer = TfidfVectorizer(
        max_features=4000,
        ngram_range=(1, 2),
        min_df=2,
        sublinear_tf=True,
        stop_words="english",
    )
    try:
        tfidf_m = vectorizer.fit_transform(texts)
    except ValueError:
        # Too little text to fit vocabulary (e.g. tiny library) — fall back.
        tfidf_m = csr_matrix((n, 0))

    pop_s, pop_mean, pop_std = _scale(pop)
    year_s, year_mean, year_std = _scale(year)
    dur_s, dur_mean, dur_std = _scale(dur)
    numeric_m = csr_matrix(np.stack([pop_s, year_s, dur_s], axis=1))

    matrix = hstack(
        [
            genre_m * W_GENRE,
            tag_m * W_TAG,
            tfidf_m * W_TFIDF,
            numeric_m * W_NUMERIC,
        ],
        format="csr",
    )
    matrix = normalize(matrix, norm="l2", axis=1, copy=False)

    return FeatureMatrix(
        track_ids=track_ids,
        matrix=matrix,
        vectorizer=vectorizer,
        genre_vocab=genre_vocab,
        tag_vocab=tag_vocab,
        numeric_stats={
            "popularity": (pop_mean, pop_std),
            "release_year": (year_mean, year_std),
            "duration_s": (dur_mean, dur_std),
        },
    )
