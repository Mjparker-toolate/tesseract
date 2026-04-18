from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.cluster import KMeans
from sklearn.preprocessing import normalize

from .features import FeatureMatrix

TOP_LABELS_PER_CLUSTER = 6


@dataclass
class MoodModel:
    centroids: np.ndarray  # (k, n_features), L2-normalised
    labels: np.ndarray  # (n_tracks,) cluster index per track
    track_ids: list[str]
    cluster_names: list[str]
    cluster_top_terms: list[list[str]]  # human-readable top terms per cluster

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            pickle.dump(self, fh)

    @classmethod
    def load(cls, path: Path) -> "MoodModel":
        with path.open("rb") as fh:
            return pickle.load(fh)


def _name_cluster(terms: list[str]) -> str:
    """Cheap heuristic label. Users can rename via --rename later if added."""
    vibe_words = {
        "chill", "mellow", "dreamy", "ambient", "lofi", "relaxing",
        "sad", "melancholy", "moody", "dark", "atmospheric",
        "happy", "upbeat", "feel good", "sunny", "bright",
        "hype", "energetic", "banger", "party", "dance",
        "romantic", "love",
        "angry", "aggressive", "heavy",
        "nostalgic", "retro", "vintage",
        "indie", "alternative", "rock", "pop", "hip hop", "rap",
        "electronic", "house", "techno", "jazz", "soul", "folk",
        "classical", "country", "r&b",
    }
    for t in terms:
        tl = t.lower()
        if tl in vibe_words:
            return tl
    return terms[0].lower() if terms else "vibe"


def _top_terms_for_cluster(
    centroid: np.ndarray,
    vocab: list[str],
    offset: int,
    length: int,
    k: int,
) -> list[str]:
    if length == 0 or not vocab:
        return []
    slice_ = centroid[offset : offset + length]
    if slice_.size == 0:
        return []
    idxs = np.argsort(-slice_)[:k]
    return [vocab[i] for i in idxs if slice_[i] > 0]


def fit_mood_model(fm: FeatureMatrix, k: int = 8, seed: int = 13) -> MoodModel:
    n = fm.matrix.shape[0]
    k = max(2, min(k, n))  # sanity clamp
    km = KMeans(
        n_clusters=k, n_init=10, random_state=seed, max_iter=300
    )
    labels = km.fit_predict(fm.matrix)
    centroids = normalize(km.cluster_centers_, norm="l2", axis=1)

    # Derive human-readable labels from the genre + tag + tfidf blocks.
    n_genres = len(fm.genre_vocab)
    n_tags = len(fm.tag_vocab)
    tfidf_vocab = fm.vectorizer.get_feature_names_out().tolist() if hasattr(
        fm.vectorizer, "get_feature_names_out"
    ) else []
    tfidf_len = len(tfidf_vocab)

    names: list[str] = []
    top_terms_per_cluster: list[list[str]] = []
    for i in range(k):
        c = centroids[i]
        # Keep a mix: tags first (best vibe signal), then genres, then tfidf.
        terms: list[str] = []
        terms += _top_terms_for_cluster(
            c, fm.tag_vocab, n_genres, n_tags, TOP_LABELS_PER_CLUSTER
        )
        terms += _top_terms_for_cluster(
            c, fm.genre_vocab, 0, n_genres, TOP_LABELS_PER_CLUSTER
        )
        terms += _top_terms_for_cluster(
            c, tfidf_vocab, n_genres + n_tags, tfidf_len, TOP_LABELS_PER_CLUSTER
        )
        # De-dup preserving order.
        seen = set()
        uniq: list[str] = []
        for t in terms:
            if t not in seen:
                uniq.append(t)
                seen.add(t)
        top_terms_per_cluster.append(uniq[: TOP_LABELS_PER_CLUSTER * 2])
        names.append(_name_cluster(uniq))

    # Disambiguate duplicate names with a numeric suffix.
    counts: dict[str, int] = {}
    final_names: list[str] = []
    for nm in names:
        counts[nm] = counts.get(nm, 0) + 1
        final_names.append(nm if counts[nm] == 1 else f"{nm}-{counts[nm]}")

    return MoodModel(
        centroids=centroids,
        labels=labels,
        track_ids=list(fm.track_ids),
        cluster_names=final_names,
        cluster_top_terms=top_terms_per_cluster,
    )


def resolve_mood_vector(
    mood: str | None,
    model: MoodModel,
    fm: FeatureMatrix,
    recent_track_ids: list[str] | None = None,
) -> tuple[np.ndarray, str]:
    """Return a query vector and a label for the resolved mood."""
    if recent_track_ids:
        id_to_row = {tid: i for i, tid in enumerate(fm.track_ids)}
        rows = [id_to_row[t] for t in recent_track_ids if t in id_to_row]
        if rows:
            sub = fm.matrix[rows]
            mean = np.asarray(sub.mean(axis=0)).ravel()
            vec = normalize(mean.reshape(1, -1), norm="l2")[0]
            # Snap to nearest cluster for labelling.
            sims = model.centroids @ vec
            idx = int(np.argmax(sims))
            return vec, f"auto:{model.cluster_names[idx]}"

    if mood:
        mood_l = mood.strip().lower()
        for i, name in enumerate(model.cluster_names):
            if mood_l == name or mood_l in model.cluster_top_terms[i]:
                return model.centroids[i], name
        # Soft match against any top term.
        for i, terms in enumerate(model.cluster_top_terms):
            if any(mood_l in t or t in mood_l for t in terms):
                return model.centroids[i], model.cluster_names[i]
        raise ValueError(
            f"Unknown mood '{mood}'. Run `spotify-recommender moods` to list."
        )

    raise ValueError("Provide --mood or --auto-mood.")
