"""Config-layer unit tests — no Spotify network calls."""
from __future__ import annotations

import pytest

from spotify_recommender.config import load_config


@pytest.fixture(autouse=True)
def _scratch_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTIFY_RECOMMENDER_HOME", str(tmp_path))
    # Start from a clean slate regardless of what's in the test runner's env.
    for var in (
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "SPOTIFY_REDIRECT_URI",
        "LASTFM_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def test_config_uses_pkce_when_no_secret(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "abc123")
    cfg = load_config()
    assert cfg.client_id == "abc123"
    assert cfg.client_secret is None
    assert cfg.use_pkce is True
    assert cfg.has_spotify_credentials is True


def test_config_uses_auth_code_when_secret_present(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "abc123")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "def456")
    cfg = load_config()
    assert cfg.client_secret == "def456"
    assert cfg.use_pkce is False
    assert cfg.has_spotify_credentials is True


def test_require_spotify_raises_without_id():
    with pytest.raises(RuntimeError, match="SPOTIFY_CLIENT_ID"):
        load_config(require_spotify=True)


def test_require_spotify_passes_with_id_only(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "abc123")
    # Should NOT raise — Secret is optional under PKCE.
    cfg = load_config(require_spotify=True)
    assert cfg.use_pkce is True


def test_empty_strings_are_treated_as_unset(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "  ")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "")
    cfg = load_config()
    assert cfg.client_id is None
    assert cfg.has_spotify_credentials is False
