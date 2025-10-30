import asyncio
from typing import Any, Dict, List, Tuple

import pytest

from playlist_sync.connectors.youtube_music import YouTubeMusicConnector
from playlist_sync.models import Track
from playlist_sync.storage import JSONStorage


class DummyOAuthSession:
    def __init__(self, *args, **kwargs):
        self.state = kwargs.get("state")

    def authorization_url(self, *args, **kwargs):
        return "http://youtube-auth", "oauth-state"

    def fetch_token(self, *args, **kwargs):
        return {
            "access_token": "youtube-token",
            "refresh_token": "refresh",
            "expires_at": 999999999,
        }


class DummyCredentials:
    def __init__(self, token, refresh_token, token_uri, client_id, client_secret, scopes):
        self.token = token
        self.refresh_token = refresh_token
        self.expired = False

    def refresh(self, request):
        self.token = "refreshed-token"


class DummyResponse:
    def __init__(self, data: Dict[str, Any], status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def json(self) -> Dict[str, Any]:
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")


class DummyAsyncClient:
    def __init__(self, responses: List[DummyResponse]):
        self._responses = responses
        self.calls: List[Tuple[str, str]] = []
        self.payloads: List[Dict[str, Any]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url: str, headers=None, params=None):
        self.calls.append(("GET", url))
        return self._responses.pop(0)

    async def delete(self, url: str, headers=None, params=None):
        self.calls.append(("DELETE", url))
        return self._responses.pop(0)

    async def post(self, url: str, headers=None, json=None):
        self.calls.append(("POST", url))
        if json is not None:
            self.payloads.append(json)
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_youtube_music_connector(monkeypatch, tmp_path):
    storage = JSONStorage(tmp_path / "youtube.json")
    connector = YouTubeMusicConnector(
        storage=storage,
        client_id="client",
        client_secret="secret",
        redirect_uri="http://callback",
    )

    async def immediate_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("playlist_sync.connectors.youtube_music.OAuth2Session", DummyOAuthSession)
    monkeypatch.setattr("playlist_sync.connectors.youtube_music.Credentials", DummyCredentials)
    monkeypatch.setattr("playlist_sync.connectors.youtube_music.asyncio.to_thread", immediate_to_thread)

    response_sets = []

    def client_factory(timeout=30.0):
        if not response_sets:
            raise RuntimeError("No responses configured")
        return DummyAsyncClient(response_sets.pop(0))

    monkeypatch.setattr("playlist_sync.connectors.youtube_music.httpx.AsyncClient", client_factory)

    url = await connector.oauth_start()
    assert url == "http://youtube-auth"

    await connector.oauth_complete({"code": "auth-code"})
    assert await connector.token_ready() is True

    # Prepare responses for list_playlists
    response_sets.append(
        [
            DummyResponse(
                {
                    "items": [
                        {
                            "id": "playlist-1",
                            "snippet": {"title": "YT Playlist"},
                            "contentDetails": {"itemCount": 1},
                        }
                    ],
                    "nextPageToken": None,
                }
            )
        ]
    )

    playlists = await connector.list_playlists()
    assert playlists[0].name == "YT Playlist"

    # Responses for list_tracks
    response_sets.append(
        [
            DummyResponse(
                {
                    "items": [
                        {
                            "snippet": {
                                "resourceId": {"videoId": "video-1"},
                                "title": "Song",
                                "videoOwnerChannelTitle": "Channel",
                            }
                        }
                    ],
                    "nextPageToken": None,
                }
            )
        ]
    )
    tracks = await connector.list_tracks("playlist-1")
    assert tracks[0].id == "video-1"

    # Responses for replace_tracks
    response_sets.append(
        [
            DummyResponse(
                {
                    "items": [{"id": "item-1"}],
                    "nextPageToken": None,
                }
            ),
            DummyResponse({}),  # delete
            DummyResponse({}),  # post
        ]
    )
    await connector.replace_tracks("playlist-1", [Track(id="video-1", title="Song", artists=["Artist"])])

    # Responses for search_track
    response_sets.append(
        [
            DummyResponse(
                {
                    "items": [
                        {
                            "id": {"videoId": "search-video"},
                            "snippet": {"title": "Song", "channelTitle": "Channel"},
                        }
                    ]
                }
            )
        ]
    )
    found = await connector.search_track(tracks[0])
    assert isinstance(found, Track)
    assert found.id == "search-video"
