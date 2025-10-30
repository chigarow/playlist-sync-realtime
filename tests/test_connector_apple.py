from typing import Any, Dict, List, Tuple

import pytest

from playlist_sync.connectors.apple_music import AppleMusicConnector
from playlist_sync.models import Playlist, Track
from playlist_sync.storage import JSONStorage


class DummyResponse:
    def __init__(self, data: Dict[str, Any], status_code: int = 200):
        self._data = data
        self.status_code = status_code

    def json(self) -> Dict[str, Any]:
        return self._data

    def raise_for_status(self) -> None:
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

    async def post(self, url: str, headers=None, json=None):
        self.calls.append(("POST", url))
        if json is not None:
            self.payloads.append(json)
        return self._responses.pop(0)

    async def request(self, method: str, url: str, headers=None, json=None):
        self.calls.append((method, url))
        if json is not None:
            self.payloads.append(json)
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_apple_music_token_storage(monkeypatch, tmp_path):
    storage = JSONStorage(tmp_path / "apple.json")
    connector = AppleMusicConnector(storage=storage, developer_token="dev")

    assert connector.is_configured() is True
    assert await connector.token_ready() is False

    await connector.oauth_complete({"developer_token": "dev", "music_user_token": "music"})
    assert await connector.token_ready() is True

    await connector.set_developer_token("new-dev")
    tokens = await storage.get("apple_music_tokens")
    assert tokens["developer_token"] == "new-dev"


@pytest.mark.asyncio
async def test_apple_music_list_and_search(monkeypatch, tmp_path):
    storage = JSONStorage(tmp_path / "apple.json")
    connector = AppleMusicConnector(storage=storage, developer_token="dev")
    await connector.oauth_complete({"developer_token": "dev", "music_user_token": "music"})

    responses = [
        DummyResponse(
            {
                "data": [
                    {
                        "id": "playlist-1",
                        "attributes": {"name": "Apple Playlist", "trackCount": 1},
                    }
                ],
                "next": None,
            }
        ),
        DummyResponse(
            {
                "data": [
                    {
                        "id": "track-1",
                        "attributes": {
                            "name": "Song",
                            "artistName": "Artist",
                            "albumName": "Album",
                            "isrc": "ISRC",
                            "durationInMillis": 123000,
                            "playParams": {"catalogId": "cat1"},
                        },
                    }
                ],
                "next": None,
            }
        ),
        DummyResponse(
            {
                "results": {
                    "songs": {
                        "data": [
                            {
                                "id": "search-track",
                                "attributes": {
                                    "name": "Song",
                                    "artistName": "Artist",
                                    "albumName": "Album",
                                    "isrc": "ISRC",
                                    "durationInMillis": 123000,
                                },
                            }
                        ]
                    }
                }
            }
        ),
    ]

    monkeypatch.setattr("playlist_sync.connectors.apple_music.httpx.AsyncClient", lambda timeout=30.0: DummyAsyncClient(responses))

    playlists = await connector.list_playlists()
    assert playlists[0].name == "Apple Playlist"

    tracks = await connector.list_tracks("playlist-1")
    assert tracks[0].title == "Song"

    result = await connector.search_track(tracks[0])
    assert isinstance(result, Track)
    assert result.id == "search-track"


@pytest.mark.asyncio
async def test_apple_music_replace_tracks(monkeypatch, tmp_path):
    storage = JSONStorage(tmp_path / "apple.json")
    connector = AppleMusicConnector(storage=storage, developer_token="dev")
    await connector.oauth_complete({"developer_token": "dev", "music_user_token": "music"})

    responses = [
        DummyResponse(
            {
                "data": [
                    {
                        "id": "track-1",
                        "attributes": {
                            "name": "Song",
                            "artistName": "Artist",
                            "albumName": "Album",
                            "isrc": "ISRC",
                            "durationInMillis": 123000,
                            "playParams": {"catalogId": "cat1"},
                        },
                    }
                ],
                "next": None,
            }
        ),
        DummyResponse({}),  # delete request
        DummyResponse({}),  # add request
    ]
    client = DummyAsyncClient(responses)
    monkeypatch.setattr("playlist_sync.connectors.apple_music.httpx.AsyncClient", lambda timeout=30.0: client)

    track = Track(id="track-1", title="Song", artists=["Artist"], album="Album")
    await connector.replace_tracks("playlist-1", [track])

    assert any(call[0] == "DELETE" for call in client.calls)
    assert any(call[0] == "POST" for call in client.calls)
    assert client.payloads[0]["data"][0]["id"] == "track-1"
