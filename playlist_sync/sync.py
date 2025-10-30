from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional

from playlist_sync.connectors.base import Connector
from playlist_sync.models import Playlist, ServiceType, Track
from playlist_sync.storage import JSONStorage


@dataclass
class SyncGroup:
    id: str
    name: str
    primary_service: ServiceType
    playlists: Dict[ServiceType, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "primary_service": self.primary_service.value,
            "playlists": {service.value: playlist_id for service, playlist_id in self.playlists.items()},
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, str]) -> "SyncGroup":
        playlists = {
            ServiceType(service): playlist_id
            for service, playlist_id in (payload.get("playlists") or {}).items()
        }
        return cls(
            id=payload["id"],
            name=payload["name"],
            primary_service=ServiceType(payload["primary_service"]),
            playlists=playlists,
        )


class SyncManager:
    def __init__(self, storage: JSONStorage, connectors: Mapping[ServiceType, Connector]) -> None:
        self.storage = storage
        self.connectors = connectors
        self._sync_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

    async def load_groups(self) -> List[SyncGroup]:
        raw = await self.storage.get("sync_groups", default=[])
        groups = [SyncGroup.from_dict(item) for item in raw]
        return groups

    async def save_groups(self, groups: Iterable[SyncGroup]) -> None:
        payload = [group.to_dict() for group in groups]
        await self.storage.set("sync_groups", payload)

    async def create_group(
        self, name: str, primary_service: ServiceType, playlists: Dict[ServiceType, str]
    ) -> SyncGroup:
        group = SyncGroup(
            id=uuid.uuid4().hex,
            name=name,
            primary_service=primary_service,
            playlists=playlists,
        )
        groups = await self.load_groups()
        groups.append(group)
        await self.save_groups(groups)
        return group

    async def update_group(self, group_id: str, playlists: Dict[ServiceType, str]) -> Optional[SyncGroup]:
        groups = await self.load_groups()
        for idx, group in enumerate(groups):
            if group.id == group_id:
                group.playlists = playlists
                groups[idx] = group
                await self.save_groups(groups)
                return group
        return None

    async def delete_group(self, group_id: str) -> None:
        groups = [group for group in await self.load_groups() if group.id != group_id]
        await self.save_groups(groups)
        await self.storage.delete(f"sync_snapshot::{group_id}")

    async def stop(self) -> None:
        self._stop_event.set()

    async def run(self, interval_seconds: int) -> None:
        while not self._stop_event.is_set():
            async with self._sync_lock:
                await self.run_once()
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_seconds)
            except asyncio.TimeoutError:
                continue

    async def run_once(self) -> None:
        groups = await self.load_groups()
        for group in groups:
            await self._sync_group(group)

    async def _sync_group(self, group: SyncGroup) -> None:
        primary_connector = self.connectors.get(group.primary_service)
        if not primary_connector:
            return
        if not await primary_connector.token_ready():
            return

        source_playlist_id = group.playlists.get(group.primary_service)
        if not source_playlist_id:
            return

        source_tracks = await primary_connector.list_tracks(source_playlist_id)
        snapshot_key = f"sync_snapshot::{group.id}"
        digest = self._tracks_digest(source_tracks)
        previous = await self.storage.get(snapshot_key)
        if previous == digest:
            return

        await self._sync_targets(group, source_tracks)
        await self.storage.set(snapshot_key, digest)

    async def _sync_targets(self, group: SyncGroup, source_tracks: List[Track]) -> None:
        primary_service = group.primary_service
        for service, playlist_id in group.playlists.items():
            if service == primary_service:
                continue
            connector = self.connectors.get(service)
            if not connector:
                continue
            if not await connector.token_ready():
                continue
            if not source_tracks:
                await connector.replace_tracks(playlist_id, [])
                continue
            mapped_tracks: List[Track] = []
            for track in source_tracks:
                matched = await connector.search_track(track)
                if matched:
                    mapped_tracks.append(matched)
            await connector.replace_tracks(playlist_id, mapped_tracks)

    @staticmethod
    def _tracks_digest(tracks: List[Track]) -> str:
        payload = [
            {
                "id": track.id,
                "title": track.title,
                "artists": track.artists,
                "album": track.album,
                "isrc": track.isrc,
            }
            for track in tracks
        ]
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
