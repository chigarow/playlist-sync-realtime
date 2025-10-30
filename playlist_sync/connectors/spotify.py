from __future__ import annotations

import asyncio
import time
from typing import Dict, Iterable, List, Optional

import spotipy
from spotipy.oauth2 import SpotifyOAuth

from playlist_sync.connectors.base import Connector, OAuthError
from playlist_sync.models import Playlist, ServiceType, Track
from playlist_sync.storage import JSONStorage

SPOTIFY_SCOPE = "playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public"


class SpotifyConnector(Connector):
    service = ServiceType.SPOTIFY

    def __init__(
        self,
        storage: JSONStorage,
        client_id: str | None,
        client_secret: str | None,
        redirect_uri: str | None,
    ) -> None:
        self.storage = storage
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri or "http://127.0.0.1:8080/auth/spotify/callback"

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _oauth(self) -> SpotifyOAuth:
        if not self.is_configured():
            raise OAuthError("Spotify credentials are not configured.")
        return SpotifyOAuth(
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            scope=SPOTIFY_SCOPE,
        )

    async def oauth_start(self) -> str:
        oauth = self._oauth()
        return await asyncio.to_thread(oauth.get_authorize_url)

    async def oauth_complete(self, query_params: Dict[str, str]) -> None:
        if "code" not in query_params:
            raise OAuthError("Spotify callback missing code parameter.")
        oauth = self._oauth()

        def _complete() -> Dict[str, str]:
            return oauth.get_access_token(code=query_params["code"], check_cache=False)

        token = await asyncio.to_thread(_complete)
        await self.storage.set("spotify_token", token)

    async def token_ready(self) -> bool:
        token = await self.storage.get("spotify_token")
        return bool(token and token.get("access_token"))

    async def _ensure_token(self) -> Dict[str, str]:
        token: Dict[str, str] | None = await self.storage.get("spotify_token")
        if not token:
            raise OAuthError("Spotify is not authenticated.")
        if token.get("expires_at", 0) - 30 < int(time.time()):
            oauth = self._oauth()

            def _refresh() -> Dict[str, str]:
                return oauth.refresh_access_token(token["refresh_token"])

            token = await asyncio.to_thread(_refresh)
            await self.storage.set("spotify_token", token)
        return token

    async def _client(self) -> spotipy.Spotify:
        token = await self._ensure_token()
        return spotipy.Spotify(auth=token["access_token"])

    async def list_playlists(self) -> List[Playlist]:
        spotify_client = await self._client()

        async def _fetch() -> List[Playlist]:
            results = await asyncio.to_thread(
                spotify_client.current_user_playlists, limit=50
            )
            playlists: List[Playlist] = []
            while results:
                for item in results["items"]:
                    playlists.append(
                        Playlist(
                            id=item["id"],
                            name=item["name"],
                            service=self.service,
                            track_count=item.get("tracks", {}).get("total", 0),
                        )
                    )
                if results.get("next"):
                    results = await asyncio.to_thread(spotify_client.next, results)
                else:
                    break
            return playlists

        return await _fetch()

    async def list_tracks(self, playlist_id: str) -> List[Track]:
        client = await self._client()

        async def _fetch() -> List[Track]:
            tracks: List[Track] = []
            results = await asyncio.to_thread(
                client.playlist_items,
                playlist_id,
                additional_types=("track",),
            )
            while results:
                for item in results["items"]:
                    track = item.get("track") or {}
                    if not track:
                        continue
                    artists = [artist["name"] for artist in track.get("artists", [])]
                    tracks.append(
                        Track(
                            id=track["id"],
                            title=track.get("name", ""),
                            artists=artists,
                            album=(track.get("album") or {}).get("name"),
                            isrc=(track.get("external_ids") or {}).get("isrc"),
                            duration_ms=track.get("duration_ms"),
                        )
                    )
                if results.get("next"):
                    results = await asyncio.to_thread(client.next, results)
                else:
                    break
            return tracks

        return await _fetch()

    async def ensure_playlist(self, name: str) -> Playlist:
        client = await self._client()

        async def _create() -> Playlist:
            me = await asyncio.to_thread(client.current_user)
            created = await asyncio.to_thread(
                client.user_playlist_create,
                user=me["id"],
                name=name,
                public=False,
                description="Synced by playlist-sync.",
            )
            return Playlist(
                id=created["id"],
                name=created["name"],
                service=self.service,
                track_count=0,
            )

        # Try to find existing playlist by name first.
        playlists = await self.list_playlists()
        for playlist in playlists:
            if playlist.name == name:
                return playlist
        return await _create()

    async def replace_tracks(self, playlist_id: str, tracks: Iterable[Track]) -> None:
        client = await self._client()
        track_ids = [track.id for track in tracks if track.id]

        async def _replace() -> None:
            await asyncio.to_thread(client.playlist_replace_items, playlist_id, track_ids)

        if track_ids:
            await _replace()
        else:
            # Spotify requires at least an empty call to clear items.
            await asyncio.to_thread(client.playlist_replace_items, playlist_id, [])

    async def search_track(self, track: Track) -> Optional[Track]:
        client = await self._client()
        query_parts = [track.title]
        if track.artists:
            query_parts.append(" ".join(track.artists))
        if track.album:
            query_parts.append(track.album)
        query = " ".join(query_parts)

        async def _search() -> Optional[Track]:
            results = await asyncio.to_thread(client.search, q=query, type="track", limit=5)
            items = (results.get("tracks") or {}).get("items", [])
            for item in items:
                artists = [artist["name"] for artist in item.get("artists", [])]
                candidate = Track(
                    id=item["id"],
                    title=item.get("name", ""),
                    artists=artists,
                    album=(item.get("album") or {}).get("name"),
                    isrc=(item.get("external_ids") or {}).get("isrc"),
                    duration_ms=item.get("duration_ms"),
                )
                if candidate.normalized_signature() == track.normalized_signature():
                    return candidate
            if items:
                item = items[0]
                artists = [artist["name"] for artist in item.get("artists", [])]
                return Track(
                    id=item["id"],
                    title=item.get("name", ""),
                    artists=artists,
                    album=(item.get("album") or {}).get("name"),
                    isrc=(item.get("external_ids") or {}).get("isrc"),
                    duration_ms=item.get("duration_ms"),
                )
            return None

        return await _search()
