from __future__ import annotations

import asyncio
from typing import Dict, Iterable, List, Optional

import httpx

from playlist_sync.connectors.base import Connector, OAuthError
from playlist_sync.models import Playlist, ServiceType, Track
from playlist_sync.storage import JSONStorage


class AppleMusicConnector(Connector):
    service = ServiceType.APPLE_MUSIC
    api_base = "https://api.music.apple.com/v1"

    def __init__(self, storage: JSONStorage, developer_token: str | None) -> None:
        self.storage = storage
        self.developer_token = developer_token

    def is_configured(self) -> bool:
        return bool(self.developer_token)

    async def oauth_start(self) -> str:
        # Web UI presents the Apple Music login flow inline.
        return "/auth/apple"

    async def oauth_complete(self, query_params: Dict[str, str]) -> None:
        developer_token = query_params.get("developer_token") or self.developer_token
        music_user_token = query_params.get("music_user_token")
        if not developer_token or not music_user_token:
            raise OAuthError("Apple Music authentication requires developer and music user tokens.")
        await self.storage.set(
            "apple_music_tokens",
            {
                "developer_token": developer_token,
                "music_user_token": music_user_token,
            },
        )
        self.developer_token = developer_token

    async def set_developer_token(self, developer_token: str) -> None:
        existing = await self.storage.get("apple_music_tokens") or {}
        await self.storage.set(
            "apple_music_tokens",
            {
                "developer_token": developer_token,
                "music_user_token": existing.get("music_user_token"),
            },
        )
        self.developer_token = developer_token

    async def token_ready(self) -> bool:
        tokens = await self.storage.get("apple_music_tokens")
        return bool(tokens and tokens.get("developer_token") and tokens.get("music_user_token"))

    async def _auth_headers(self) -> Dict[str, str]:
        tokens = await self.storage.get("apple_music_tokens")
        if not tokens:
            raise OAuthError("Apple Music tokens are missing.")
        developer_token = tokens.get("developer_token") or self.developer_token
        music_user_token = tokens.get("music_user_token")
        if not developer_token or not music_user_token:
            raise OAuthError("Apple Music tokens are incomplete.")
        return {
            "Authorization": f"Bearer {developer_token}",
            "Music-User-Token": music_user_token,
        }

    async def list_playlists(self) -> List[Playlist]:
        headers = await self._auth_headers()
        playlists: List[Playlist] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{self.api_base}/me/library/playlists"
            while url:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()
                for item in payload.get("data", []):
                    attributes = item.get("attributes") or {}
                    playlists.append(
                        Playlist(
                            id=item.get("id"),
                            name=attributes.get("name", "Untitled"),
                            service=self.service,
                            track_count=attributes.get("trackCount", 0),
                        )
                    )
                url = payload.get("next")
                if url:
                    url = f"{self.api_base}{url}"
        return playlists

    async def list_tracks(self, playlist_id: str) -> List[Track]:
        headers = await self._auth_headers()
        tracks: List[Track] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{self.api_base}/me/library/playlists/{playlist_id}/tracks"
            while url:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()
                for item in payload.get("data", []):
                    attributes = item.get("attributes") or {}
                    artists = []
                    if attributes.get("artistName"):
                        artists.append(attributes["artistName"])
                    tracks.append(
                        Track(
                            id=item.get("id") or attributes.get("playParams", {}).get("catalogId", ""),
                            title=attributes.get("name", ""),
                            artists=artists,
                            album=attributes.get("albumName"),
                            isrc=attributes.get("isrc"),
                            duration_ms=attributes.get("durationInMillis"),
                        )
                    )
                url = payload.get("next")
                if url:
                    url = f"{self.api_base}{url}"
        return tracks

    async def ensure_playlist(self, name: str) -> Playlist:
        playlists = await self.list_playlists()
        for playlist in playlists:
            if playlist.name == name:
                return playlist

        headers = await self._auth_headers()
        body = {
            "attributes": {
                "name": name,
                "description": "Synced by playlist-sync.",
            }
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.api_base}/me/library/playlists",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        data = (payload.get("data") or [])[0]
        attributes = data.get("attributes") or {}
        return Playlist(
            id=data.get("id"),
            name=attributes.get("name", name),
            service=self.service,
            track_count=0,
        )

    async def replace_tracks(self, playlist_id: str, tracks: Iterable[Track]) -> None:
        headers = await self._auth_headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            # First clear playlist
            existing = await self.list_tracks(playlist_id)
            if existing:
                delete_payload = {
                    "data": [{"id": track.id, "type": "library-songs"} for track in existing if track.id]
                }
                # Apple Music API expects catalog/library type hints. We skip errors silently.
                await client.request(
                    "DELETE",
                    f"{self.api_base}/me/library/playlists/{playlist_id}/tracks",
                    headers=headers,
                    json=delete_payload,
                )
            # Add new tracks in batches of 100
            to_add = [track for track in tracks if track.id]
            for start in range(0, len(to_add), 100):
                chunk = to_add[start : start + 100]
                payload = {
                    "data": [
                        {
                            "id": track.id,
                            "type": "library-songs" if track.id.startswith("i.") else "songs",
                        }
                        for track in chunk
                    ]
                }
                await client.post(
                    f"{self.api_base}/me/library/playlists/{playlist_id}/tracks",
                    headers=headers,
                    json=payload,
                )

    async def search_track(self, track: Track) -> Optional[Track]:
        headers = await self._auth_headers()
        query_parts = [track.title]
        if track.artists:
            query_parts.append(" ".join(track.artists))
        if track.album:
            query_parts.append(track.album)
        params = {"term": " ".join(query_parts), "types": "songs", "limit": 5}
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{self.api_base}/catalog/us/search",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
        songs = ((payload.get("results") or {}).get("songs") or {}).get("data", [])
        for item in songs:
            attributes = item.get("attributes") or {}
            artists = []
            if attributes.get("artistName"):
                artists.append(attributes["artistName"])
            candidate = Track(
                id=item.get("id"),
                title=attributes.get("name", ""),
                artists=artists,
                album=attributes.get("albumName"),
                isrc=attributes.get("isrc"),
                duration_ms=attributes.get("durationInMillis"),
            )
            if candidate.normalized_signature() == track.normalized_signature():
                return candidate
        if songs:
            item = songs[0]
            attributes = item.get("attributes") or {}
            artists = []
            if attributes.get("artistName"):
                artists.append(attributes["artistName"])
            return Track(
                id=item.get("id"),
                title=attributes.get("name", ""),
                artists=artists,
                album=attributes.get("albumName"),
                isrc=attributes.get("isrc"),
                duration_ms=attributes.get("durationInMillis"),
            )
        return None
