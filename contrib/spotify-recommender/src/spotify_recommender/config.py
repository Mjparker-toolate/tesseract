from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _home() -> Path:
    override = os.getenv("SPOTIFY_RECOMMENDER_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".spotify-recommender"


@dataclass(frozen=True)
class Config:
    client_id: str | None
    client_secret: str | None
    redirect_uri: str
    lastfm_api_key: str | None
    home: Path

    @property
    def db_path(self) -> Path:
        return self.home / "library.sqlite"

    @property
    def token_cache_path(self) -> Path:
        return self.home / ".cache-spotify"

    @property
    def model_path(self) -> Path:
        return self.home / "mood_model.npz"

    @property
    def has_spotify_credentials(self) -> bool:
        """True when at least a Client ID is present (Secret optional under PKCE)."""
        return bool(self.client_id)

    @property
    def use_pkce(self) -> bool:
        """Use PKCE (no Client Secret) when only Client ID is configured."""
        return bool(self.client_id) and not self.client_secret


def load_config(require_spotify: bool = False) -> Config:
    """Load configuration from environment / .env.

    ``require_spotify=True`` enforces the presence of a Client ID (for the
    live-API commands like ``auth`` and ``ingest``). Client Secret is
    optional — when absent, the auth layer uses PKCE. Offline commands
    (``import-export``, ``train``, ``recommend``) run with no credentials.
    """
    home = _home()
    home.mkdir(parents=True, exist_ok=True)
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip() or None
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip() or None
    redirect_uri = os.getenv(
        "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"
    ).strip()
    if require_spotify and not client_id:
        raise RuntimeError(
            "SPOTIFY_CLIENT_ID must be set in .env for this command. "
            "SPOTIFY_CLIENT_SECRET is optional — leave it empty to use "
            "the PKCE flow (recommended for CLI use). For a fully offline "
            "workflow, use `spotify-recommender import-export <path>` instead."
        )
    lastfm = os.getenv("LASTFM_API_KEY", "").strip() or None
    return Config(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        lastfm_api_key=lastfm,
        home=home,
    )


SCOPES = [
    "user-library-read",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-top-read",
    "user-read-recently-played",
]
