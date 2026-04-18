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

## Two ways to use it

### A. Offline-only (no OAuth, no developer app)

Request your data from Spotify (Account → Privacy → "Request your data"
and/or "Request extended streaming history"). When the export arrives,
unzip it and feed the folder to the importer. No dashboard, no browser
consent flow, no API keys required.

```bash
cd contrib/spotify-recommender
python -m venv .venv && source .venv/bin/activate
pip install -e .

spotify-recommender import-export ~/Downloads/my_spotify_data
spotify-recommender train --k 8
spotify-recommender moods
spotify-recommender recommend --auto-mood --n 20 --exploration 0
```

The offline path supports every data file Spotify includes:

- ``YourLibrary.json``                  — liked songs + followed artists
- ``Playlist*.json``                    — your playlists and their items
- ``StreamingHistory*.json``            — ~1 year of plays
- ``Streaming_History_Audio_*.json``    — lifetime extended history

Duplicates across formats are collapsed by (artist, title) lookup.

### B. Live API (needs a 5-minute developer-app setup, PKCE — no Secret)

Enables pulling liked / playlists / top / recently-played directly and
injecting a small share of novel tracks (unheard-by-you) into each
recommendation list.

The CLI uses **PKCE by default** — you only need a Client ID, never a
Client Secret. This is Spotify's recommended flow for CLI / desktop apps.

1. **Register the app** at https://developer.spotify.com/dashboard:
   - Click **Create app**.
   - **Redirect URI**: `http://127.0.0.1:8888/callback` (click Add).
   - **APIs used**: check **Web API**.
   - Save.
2. **Copy the Client ID** from the app's Settings page. Ignore "View client secret".
3. **Configure** your local `.env`:
   ```bash
   cp .env.example .env
   # edit .env:
   #   SPOTIFY_CLIENT_ID=<paste your Client ID>
   #   SPOTIFY_CLIENT_SECRET=        # leave empty for PKCE
   ```
4. (Optional) Get a free Last.fm API key for richer tags:
   https://www.last.fm/api/account/create → add to `.env` as `LASTFM_API_KEY`.
5. **Run**:
   ```bash
   spotify-recommender auth          # opens browser, click "Agree"
   spotify-recommender ingest
   spotify-recommender enrich-tags   # optional — needs LASTFM_API_KEY
   spotify-recommender train --k 8
   spotify-recommender recommend --auto-mood --n 20 --exploration 0.15
   ```

Both A and B write to the same SQLite cache, so you can mix them: import
your data export once for deep history, then top it up with live `ingest`
runs when you want recent-plays freshness.

#### Alternative: Authorization-Code flow (with Client Secret)

Only use this if you have a specific reason to. Copy **both** the Client ID
and Secret into `.env`, and the CLI auto-switches to the classic flow.

## Multi-device / cloud

Everything the recommender needs lives under `~/.spotify-recommender/`
(SQLite cache, trained model). To use the tool on multiple machines:

- Simplest: copy that folder.
- Auto-sync, zero code: place it inside Dropbox / iCloud Drive / Google
  Drive / OneDrive (or symlink it there).
- Override the location with `SPOTIFY_RECOMMENDER_HOME=/path/to/shared`.


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
