# spotify-recommender

An adaptive, mood-aware song recommender trained on your own Spotify library.

It ingests your liked songs, playlists, top tracks, and recent plays; learns
"vibe" clusters from genres, Last.fm tags, and TF-IDF embeddings of track
metadata; then ranks candidates against a mood query. A small, tunable slice
of each recommendation list is reserved for novel tracks you haven't heard.

> This project lives as a self-contained sidecar under `contrib/` and is
> independent of the Tesseract OCR codebase that hosts it.

## Why it works the way it does

Spotify deprecated the Audio Features and Audio Analysis endpoints for new
apps in late 2024, so this tool does **not** depend on valence / energy /
danceability. Instead it builds a vibe signal from:

- **Artist genres** (still available via `/artists`)
- **Last.fm top tags** per artist (optional, needs a free API key)
- **Playlist co-occurrence** (tracks you group together share a vibe)
- **TF-IDF over title + artist + genre + tag tokens**
- **Recency/popularity/release-era metadata**

Clustering over that feature space gives labelled moods. A mood query is
resolved either to a named cluster (`--mood chill`) or inferred from the
centroid of your last N plays (`--auto-mood`).

## Prerequisites

- Python 3.10+
- A Spotify Developer app: https://developer.spotify.com/dashboard
  - Redirect URI: `http://127.0.0.1:8888/callback`
- (Optional) Last.fm API key: https://www.last.fm/api/account/create
- (Optional) Your Spotify Extended Streaming History JSON export
  (Account → Privacy → "Request extended streaming history")

## Setup

```bash
cd contrib/spotify-recommender
python -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env
# edit .env with your Spotify (and optional Last.fm) credentials
```

## Usage

```bash
# 1. One-time OAuth (opens a browser)
spotify-recommender auth

# 2. Pull your library into a local SQLite cache
spotify-recommender ingest

# 3. (Optional) enrich with Last.fm tags
spotify-recommender enrich-tags

# 4. (Optional) import extended streaming history
spotify-recommender import-history ~/Downloads/Spotify_Extended_History

# 5. Train the mood model
spotify-recommender train --k 8

# 6. Inspect learned vibes
spotify-recommender moods

# 7. Get recommendations
spotify-recommender recommend --mood chill --n 20
spotify-recommender recommend --auto-mood --n 20 --exploration 0.15
```

## Data flow

```
Spotify API  ──┐
Last.fm API  ──┼──►  SQLite cache  ──►  Feature matrix  ──►  KMeans vibes
History JSON ──┘                                          └──►  Ranker ──► recs
                                                                   ▲
                                                          new-track candidates
                                                          (Spotify /recommendations
                                                           or related-artists fallback)
```

## Known limits

- Spotify `/recommendations` is itself being deprecated for new apps. The
  recommender falls back to `related-artists → top-tracks` if it 403s.
- `recently-played` only returns the last 50 tracks. For real long-term
  trend analysis, import the extended history export.
- Last.fm tags are artist-level, not track-level, unless a track is
  well-known. That's fine for vibe modelling but coarse for ballad-vs-banger
  distinctions within the same artist.
- No audio is analysed locally. If you have your own audio files, extending
  `features.py` with `librosa` features is straightforward.

## License

Apache-2.0 (matches the hosting repo).
