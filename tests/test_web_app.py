import pytest
from fastapi.testclient import TestClient

from playlist_sync.config import AppConfig
from playlist_sync.connectors.apple_music import AppleMusicConnector
from playlist_sync.connectors.base import Connector
from playlist_sync.models import Playlist, ServiceType, Track
from playlist_sync.storage import JSONStorage
from playlist_sync.sync import SyncManager
from playlist_sync.web import build_app


class WebStubConnector(Connector):
    def __init__(self, service: ServiceType, configured: bool = True, token_ready: bool = True):
        self.service = service
        self._configured = configured
        self._token_ready = token_ready
        self._playlists = [
            Playlist(id=f"{service.value}-1", name=f"{service.value} playlist", service=service, track_count=1)
        ]
        self.replaced = {}

    def is_configured(self) -> bool:
        return self._configured

    async def oauth_start(self) -> str:
        return "http://auth.example"

    async def oauth_complete(self, query_params):
        self._token_ready = True

    async def token_ready(self) -> bool:
        return self._token_ready

    async def list_playlists(self):
        return self._playlists

    async def list_tracks(self, playlist_id: str):
        return [
            Track(id="track-1", title="Title", artists=["Artist"], album="Album"),
        ]

    async def ensure_playlist(self, name: str) -> Playlist:
        playlist = Playlist(id=f"{self.service.value}-new", name=name, service=self.service, track_count=0)
        self._playlists.append(playlist)
        return playlist

    async def replace_tracks(self, playlist_id: str, tracks):
        self.replaced[playlist_id] = list(tracks)

    async def search_track(self, track: Track):
        return Track(id=f"{self.service.value}-{track.title}", title=track.title, artists=track.artists, album=track.album)


class WebAppleConnector(AppleMusicConnector):
    def __init__(self, storage: JSONStorage):
        super().__init__(storage=storage, developer_token="dev-token")
        self.service = ServiceType.APPLE_MUSIC
        self._configured = True
        self._token_ready = True
        self._playlists = [
            Playlist(id="apple-1", name="Apple playlist", service=ServiceType.APPLE_MUSIC, track_count=1)
        ]
        self.developer_token_value = "dev-token"
        self.music_user_token_value = "music-user"

    def is_configured(self) -> bool:
        return self._configured

    async def token_ready(self) -> bool:
        return self._token_ready

    async def list_playlists(self):
        return self._playlists

    async def list_tracks(self, playlist_id: str):
        return [
            Track(id="apple-track", title="Title", artists=["Artist"], album="Album"),
        ]

    async def ensure_playlist(self, name: str) -> Playlist:
        playlist = Playlist(id="apple-new", name=name, service=ServiceType.APPLE_MUSIC, track_count=0)
        self._playlists.append(playlist)
        return playlist

    async def replace_tracks(self, playlist_id: str, tracks):
        return None

    async def search_track(self, track: Track):
        return Track(id="apple-search", title=track.title, artists=track.artists, album=track.album)

    async def oauth_complete(self, query_params):
        self.music_user_token_value = query_params.get("music_user_token", "")
        self._token_ready = True

    async def set_developer_token(self, developer_token: str) -> None:
        self.developer_token_value = developer_token


@pytest.fixture()
def web_app(tmp_path):
    storage = JSONStorage(tmp_path / "state.json")
    connectors = {
        ServiceType.SPOTIFY: WebStubConnector(ServiceType.SPOTIFY),
        ServiceType.APPLE_MUSIC: WebAppleConnector(storage),
        ServiceType.YOUTUBE_MUSIC: WebStubConnector(ServiceType.YOUTUBE_MUSIC),
    }
    sync_manager = SyncManager(storage=storage, connectors=connectors)
    config = AppConfig(data_dir=tmp_path, host="127.0.0.1", port=8888, poll_interval_seconds=1)
    app = build_app(config=config, storage=storage, connectors=connectors, sync_manager=sync_manager)
    return app, sync_manager, connectors, storage


def test_index_route(web_app):
    app, manager, connectors, _ = web_app
    client = TestClient(app)
    manager_loop = manager  # keep reference
    response = client.get("/")
    assert response.status_code == 200
    assert "Playlist Sync Service" in response.text


def test_groups_api_crud(web_app):
    app, manager, connectors, storage = web_app
    client = TestClient(app)

    response = client.post(
        "/api/groups",
        json={
            "name": "New Group",
            "primary_service": "spotify",
            "playlists": {"spotify": "spotify-1", "apple_music": "apple-1"},
        },
    )
    assert response.status_code == 200
    group_id = response.json()["id"]

    list_response = client.get("/api/groups")
    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == group_id

    delete_response = client.delete(f"/api/groups/{group_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["ok"] is True


def test_apple_token_endpoints(web_app):
    app, _, connectors, _ = web_app
    client = TestClient(app)

    response = client.post("/api/apple/developer-token", json={"developer_token": "updated-token"})
    assert response.status_code == 200
    assert connectors[ServiceType.APPLE_MUSIC].developer_token_value == "updated-token"

    response = client.post(
        "/api/apple/token",
        json={"developer_token": "updated-token", "music_user_token": "user-token"},
    )
    assert response.status_code == 200
    assert connectors[ServiceType.APPLE_MUSIC].music_user_token_value == "user-token"
