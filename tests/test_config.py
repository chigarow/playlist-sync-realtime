import os

from playlist_sync.config import AppConfig, OAuthConfig


def test_app_config_ensure_dirs(monkeypatch, data_dir):
    monkeypatch.setenv("PLAYLIST_SYNC_DATA", str(data_dir))
    config = AppConfig()
    config.ensure_dirs()
    assert config.data_dir.exists()


def test_oauth_config_from_env(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "sid")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret")
    monkeypatch.setenv("SPOTIFY_REDIRECT_URI", "http://localhost/callback")
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "yid")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "ysecret")
    monkeypatch.setenv("APPLE_DEVELOPER_TOKEN", "apple-token")

    oauth = OAuthConfig.from_env()
    assert oauth.spotify_client_id == "sid"
    assert oauth.spotify_client_secret == "secret"
    assert oauth.spotify_redirect_uri == "http://localhost/callback"
    assert oauth.youtube_client_id == "yid"
    assert oauth.youtube_client_secret == "ysecret"
    assert oauth.apple_developer_token == "apple-token"
