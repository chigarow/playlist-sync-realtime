import pytest

from playlist_sync.models import Playlist, ServiceType, Track
from playlist_sync.storage import JSONStorage
from playlist_sync.sync import SyncManager
from playlist_sync.connectors.base import Connector


class FakeConnector(Connector):
    def __init__(self, service: ServiceType, *, configured: bool = True, token: bool = True) -> None:
        self.service = service
        self._configured = configured
        self._token_ready = token
        self.playlists = [
            Playlist(id=f"{service.value}-1", name="Base", service=service, track_count=1)
        ]
        self.tracks = [
            Track(id=f"{service.value}-track", title="Song", artists=["Artist"], album="Album")
        ]
        self.created_playlists: list[Playlist] = []
        self.replaced: dict[str, list[Track]] = {}

    def is_configured(self) -> bool:
        return self._configured

    async def oauth_start(self) -> str:
        return "http://auth.example"

    async def oauth_complete(self, query_params):
        self._token_ready = True

    async def token_ready(self) -> bool:
        return self._token_ready

    async def list_playlists(self):
        return self.playlists

    async def list_tracks(self, playlist_id: str):
        return self.tracks

    async def ensure_playlist(self, name: str) -> Playlist:
        playlist = Playlist(id=f"{self.service.value}-new", name=name, service=self.service, track_count=0)
        self.created_playlists.append(playlist)
        return playlist

    async def replace_tracks(self, playlist_id: str, tracks):
        self.replaced[playlist_id] = list(tracks)

    async def search_track(self, track: Track):
        # Mirror incoming track with new id to simulate mapping success
        return Track(
            id=f"{self.service.value}-{track.title}",
            title=track.title,
            artists=track.artists,
            album=track.album,
        )


@pytest.mark.asyncio
async def test_sync_manager_group_lifecycle(tmp_path):
    storage = JSONStorage(tmp_path / "state.json")
    connectors = {
        ServiceType.SPOTIFY: FakeConnector(ServiceType.SPOTIFY),
        ServiceType.APPLE_MUSIC: FakeConnector(ServiceType.APPLE_MUSIC),
    }
    manager = SyncManager(storage=storage, connectors=connectors)

    group = await manager.create_group(
        name="Test Group",
        primary_service=ServiceType.SPOTIFY,
        playlists={ServiceType.SPOTIFY: "spotify-1"},
    )
    groups = await manager.load_groups()
    assert groups and groups[0].id == group.id

    await manager.update_group(group.id, {ServiceType.SPOTIFY: "spotify-1", ServiceType.APPLE_MUSIC: "apple-1"})
    updated = await manager.load_groups()
    assert ServiceType.APPLE_MUSIC in updated[0].playlists

    await manager.delete_group(group.id)
    assert await manager.load_groups() == []


@pytest.mark.asyncio
async def test_sync_manager_run_once_skips_without_tokens(tmp_path):
    storage = JSONStorage(tmp_path / "state.json")
    connectors = {
        ServiceType.SPOTIFY: FakeConnector(ServiceType.SPOTIFY, token=True),
        ServiceType.APPLE_MUSIC: FakeConnector(ServiceType.APPLE_MUSIC, token=False),
    }
    manager = SyncManager(storage=storage, connectors=connectors)
    await manager.create_group(
        name="Group",
        primary_service=ServiceType.SPOTIFY,
        playlists={
            ServiceType.SPOTIFY: "spotify-1",
            ServiceType.APPLE_MUSIC: "apple_music-1",
        },
    )

    await manager.run_once()
    assert connectors[ServiceType.APPLE_MUSIC].replaced == {}


@pytest.mark.asyncio
async def test_sync_manager_syncs_tracks(tmp_path):
    storage = JSONStorage(tmp_path / "state.json")
    source_connector = FakeConnector(ServiceType.SPOTIFY, token=True)
    target_connector = FakeConnector(ServiceType.APPLE_MUSIC, token=True)
    connectors = {
        ServiceType.SPOTIFY: source_connector,
        ServiceType.APPLE_MUSIC: target_connector,
    }
    manager = SyncManager(storage=storage, connectors=connectors)
    await manager.create_group(
        name="Mirror",
        primary_service=ServiceType.SPOTIFY,
        playlists={
            ServiceType.SPOTIFY: "spotify-1",
            ServiceType.APPLE_MUSIC: "apple_music-1",
        },
    )

    await manager.run_once()
    assert "apple_music-1" in target_connector.replaced
    assert target_connector.replaced["apple_music-1"][0].id.startswith("apple_music-")

    # Second run should be skipped because snapshot matches
    await manager.run_once()
    assert len(target_connector.replaced["apple_music-1"]) == 1
