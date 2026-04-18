from __future__ import annotations

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from .config import SCOPES, Config


def build_oauth(cfg: Config) -> SpotifyOAuth:
    return SpotifyOAuth(
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
        redirect_uri=cfg.redirect_uri,
        scope=" ".join(SCOPES),
        cache_path=str(cfg.token_cache_path),
        open_browser=True,
    )


def get_client(cfg: Config) -> spotipy.Spotify:
    """Return an authenticated Spotify client, triggering OAuth if needed."""
    oauth = build_oauth(cfg)
    token = oauth.get_access_token(as_dict=False)
    return spotipy.Spotify(auth=token, requests_timeout=30, retries=3)


def force_auth(cfg: Config) -> str:
    """Run the interactive OAuth flow and return the username."""
    client = get_client(cfg)
    me = client.current_user()
    return me.get("display_name") or me.get("id", "unknown")
