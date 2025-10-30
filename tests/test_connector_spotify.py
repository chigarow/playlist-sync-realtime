import asyncio
from typing import Any, Dict, List

import pytest

from playlist_sync.connectors.spotify import SpotifyConnector
from playlist_sync.models import Track
from playlist_sync.storage import JSONStorage


class DummySpotifyOAuth:
    def __init__(self, *args, **kwargs):
        self.last_scope = kwargs.get("scope")

    def get_authorize_url(self):
        return "http://spotify-auth"

    def get_access_token(self, code, check_cache=False):
        return {
            "access_token": "initial-token",
            "refresh_token": "refresh-token",
            "expires_at": 0,
        }

    def refresh_access_token(self, refresh_token):
        return {
            "access_token": "refreshed-token",
            "refresh_token": refresh_token,
            "expires_at": 999999999,
        }


class DummySpotifyClient:
    def __init__(self):
        self.replace_args = None

    def current_user_playlists(self, limit=50):
        return {
            "items": [
                {
                    "id": "playlist-1",
                    "name": "Primary",
                    "tracks": {"total": 2},
                }
            ],
            "next": None,
        }

    def next(self, results):
        return None

    def playlist_items(self, playlist_id, additional_types=None):
        return {
            "items": [
                {
                    "track": {
                        "id": "track-1",
                        "name": "Track Title",
                        "artists": [{"name": "Artist"}],
                        "album": {"name": "Album"},
                        "external_ids": {"isrc": "ISRC123"},
                        "duration_ms": 200000,
                    }
                }
            ],
            "next": None,
        }

    def current_user(self):
        return {"id": "user-id"}

    def user_playlist_create(self, user, name, public, description):
        return {"id": "created", "name": name}

    def playlist_replace_items(self, playlist_id, track_ids):
        self.replace_args = (playlist_id, list(track_ids))

    def search(self, q, type, limit):
        return {
            "tracks": {
                "items": [
                    {
                        "id": "track-1",
                        "name": "Track Title",
                        "artists": [{"name": "Artist"}],
                        "album": {"name": "Album"},
                        "external_ids": {"isrc": "ISRC123"},
                        "duration_ms": 200000,
                    }
                ]
            }
        }


@pytest.mark.asyncio
async def test_spotify_connector_flow(monkeypatch, tmp_path):
    storage = JSONStorage(tmp_path / "spotify.json")
    dummy_client = DummySpotifyClient()

    async def immediate_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("playlist_sync.connectors.spotify.SpotifyOAuth", DummySpotifyOAuth)
    monkeypatch.setattr("playlist_sync.connectors.spotify.spotipy.Spotify", lambda auth=None: dummy_client)
    monkeypatch.setattr("playlist_sync.connectors.spotify.asyncio.to_thread", immediate_to_thread)

    connector = SpotifyConnector(
        storage=storage,
        client_id="client",
        client_secret="secret",
        redirect_uri="http://callback",
    )

    assert connector.is_configured() is True

    url = await connector.oauth_start()
    assert url == "http://spotify-auth"

    await connector.oauth_complete({"code": "abc"})
    assert await connector.token_ready() is True

    playlists = await connector.list_playlists()
    assert playlists[0].name == "Primary"

    tracks = await connector.list_tracks("playlist-1")
    assert tracks[0].title == "Track Title"

    playlist = await connector.ensure_playlist("Primary")
    assert playlist.id == "playlist-1"

    await connector.replace_tracks("playlist-1", tracks)
    assert dummy_client.replace_args[0] == "playlist-1"
    assert dummy_client.replace_args[1] == ["track-1"]

    mapped = await connector.search_track(tracks[0])
    assert isinstance(mapped, Track)
    assert mapped.id == "track-1"
