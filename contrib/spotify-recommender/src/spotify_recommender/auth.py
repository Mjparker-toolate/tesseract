from __future__ import annotations

import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyPKCE

from .config import SCOPES, Config


def build_oauth(cfg: Config) -> SpotifyOAuth:
    """Authorization-Code flow — requires Client Secret."""
    return SpotifyOAuth(
        client_id=cfg.client_id,
        client_secret=cfg.client_secret,
        redirect_uri=cfg.redirect_uri,
        scope=" ".join(SCOPES),
        cache_path=str(cfg.token_cache_path),
        open_browser=True,
    )


def build_pkce(cfg: Config) -> SpotifyPKCE:
    """PKCE flow — Client ID only, no Secret. Recommended for CLI use."""
    return SpotifyPKCE(
        client_id=cfg.client_id,
        redirect_uri=cfg.redirect_uri,
        scope=" ".join(SCOPES),
        cache_path=str(cfg.token_cache_path),
        open_browser=True,
    )


def get_client(cfg: Config) -> spotipy.Spotify:
    """Return an authenticated Spotify client, triggering OAuth if needed."""
    auth_manager = build_pkce(cfg) if cfg.use_pkce else build_oauth(cfg)
    token = auth_manager.get_access_token(as_dict=False)
    return spotipy.Spotify(auth=token, requests_timeout=30, retries=3)


def force_auth(cfg: Config) -> tuple[str, str]:
    """Run the interactive OAuth flow. Returns (display_name, flow_used)."""
    client = get_client(cfg)
    me = client.current_user()
    name = me.get("display_name") or me.get("id", "unknown")
    flow = "PKCE" if cfg.use_pkce else "Authorization Code"
    return name, flow
