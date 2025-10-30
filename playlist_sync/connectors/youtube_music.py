from __future__ import annotations

import asyncio
from typing import Dict, Iterable, List, Optional

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from requests_oauthlib import OAuth2Session

from playlist_sync.connectors.base import Connector, OAuthError
from playlist_sync.models import Playlist, ServiceType, Track
from playlist_sync.storage import JSONStorage

YOUTUBE_SCOPE = ["https://www.googleapis.com/auth/youtube"]
AUTHORIZATION_BASE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


class YouTubeMusicConnector(Connector):
    service = ServiceType.YOUTUBE_MUSIC

    def __init__(
        self,
        storage: JSONStorage,
        client_id: str | None,
        client_secret: str | None,
        redirect_uri: str | None = None,
    ) -> None:
        self.storage = storage
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri or "http://127.0.0.1:8080/auth/youtube/callback"

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _session(self, state: str | None = None) -> OAuth2Session:
        if not self.is_configured():
            raise OAuthError("YouTube Music credentials are not configured.")
        return OAuth2Session(
            client_id=self.client_id,
            scope=YOUTUBE_SCOPE,
            redirect_uri=self.redirect_uri,
            state=state,
        )

    async def oauth_start(self) -> str:
        session = self._session()
        authorization_url, state = session.authorization_url(
            AUTHORIZATION_BASE_URL,
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        await self.storage.set("youtube_oauth_state", state)
        return authorization_url

    async def oauth_complete(self, query_params: Dict[str, str]) -> None:
        if "code" not in query_params:
            raise OAuthError("YouTube Music callback missing code parameter.")
        state = await self.storage.get("youtube_oauth_state")
        session = self._session(state=state)
        token = session.fetch_token(
            TOKEN_URL,
            code=query_params["code"],
            client_secret=self.client_secret,
        )
        credentials = {
            "token": token["access_token"],
            "refresh_token": token.get("refresh_token"),
            "token_uri": TOKEN_URL,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scopes": YOUTUBE_SCOPE,
            "expiry": token.get("expires_at"),
        }
        await self.storage.set("youtube_token", credentials)

    async def token_ready(self) -> bool:
        token = await self.storage.get("youtube_token")
        return bool(token and token.get("token"))

    async def _credentials(self) -> Credentials:
        token = await self.storage.get("youtube_token")
        if not token:
            raise OAuthError("YouTube Music is not authenticated.")
        credentials = Credentials(
            token=token["token"],
            refresh_token=token.get("refresh_token"),
            token_uri=TOKEN_URL,
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=YOUTUBE_SCOPE,
        )
        if credentials.expired and credentials.refresh_token:
            await asyncio.to_thread(credentials.refresh, Request())
            await self.storage.set(
                "youtube_token",
                {
                    "token": credentials.token,
                    "refresh_token": credentials.refresh_token,
                    "token_uri": TOKEN_URL,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scopes": YOUTUBE_SCOPE,
                },
            )
        return credentials

    async def _auth_headers(self) -> Dict[str, str]:
        credentials = await self._credentials()
        return {"Authorization": f"Bearer {credentials.token}", "Accept": "application/json"}

    async def list_playlists(self) -> List[Playlist]:
        headers = await self._auth_headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            playlists: List[Playlist] = []
            page_token: Optional[str] = None
            while True:
                params = {
                    "mine": "true",
                    "part": "id,snippet,contentDetails",
                    "maxResults": 50,
                }
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get(
                    "https://www.googleapis.com/youtube/v3/playlists",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
                for item in payload.get("items", []):
                    snippet = item.get("snippet") or {}
                    playlists.append(
                        Playlist(
                            id=item["id"],
                            name=snippet.get("title", "Untitled"),
                            service=self.service,
                            track_count=(item.get("contentDetails") or {}).get("itemCount", 0),
                        )
                    )
                page_token = payload.get("nextPageToken")
                if not page_token:
                    break
        return playlists

    async def list_tracks(self, playlist_id: str) -> List[Track]:
        headers = await self._auth_headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            tracks: List[Track] = []
            page_token: Optional[str] = None
            while True:
                params = {
                    "playlistId": playlist_id,
                    "part": "snippet,contentDetails",
                    "maxResults": 50,
                }
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get(
                    "https://www.googleapis.com/youtube/v3/playlistItems",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
                for item in payload.get("items", []):
                    snippet = item.get("snippet") or {}
                    track_id = (snippet.get("resourceId") or {}).get("videoId", "")
                    title = snippet.get("title", "")
                    channel = snippet.get("videoOwnerChannelTitle")
                    artists: List[str] = []
                    if channel:
                        artists.append(channel)
                    tracks.append(
                        Track(
                            id=track_id,
                            title=title,
                            artists=artists,
                            album=None,
                            isrc=None,
                            duration_ms=None,
                        )
                    )
                page_token = payload.get("nextPageToken")
                if not page_token:
                    break
        return tracks

    async def ensure_playlist(self, name: str) -> Playlist:
        playlists = await self.list_playlists()
        for playlist in playlists:
            if playlist.name == name:
                return playlist
        headers = await self._auth_headers()
        body = {
            "snippet": {"title": name, "description": "Synced by playlist-sync."},
            "status": {"privacyStatus": "private"},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://www.googleapis.com/youtube/v3/playlists?part=snippet,status",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        snippet = payload.get("snippet") or {}
        return Playlist(
            id=payload["id"],
            name=snippet.get("title", name),
            service=self.service,
            track_count=0,
        )

    async def replace_tracks(self, playlist_id: str, tracks: Iterable[Track]) -> None:
        headers = await self._auth_headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Delete existing entries
            existing_items: List[str] = []
            page_token: Optional[str] = None
            while True:
                params = {
                    "playlistId": playlist_id,
                    "part": "id",
                    "maxResults": 50,
                }
                if page_token:
                    params["pageToken"] = page_token
                response = await client.get(
                    "https://www.googleapis.com/youtube/v3/playlistItems",
                    headers=headers,
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
                for item in payload.get("items", []):
                    existing_items.append(item["id"])
                page_token = payload.get("nextPageToken")
                if not page_token:
                    break
            for item_id in existing_items:
                await client.delete(
                    "https://www.googleapis.com/youtube/v3/playlistItems",
                    headers=headers,
                    params={"id": item_id},
                )
            # Add new tracks
            for track in tracks:
                if not track.id:
                    continue
                payload = {
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": track.id,
                        },
                    }
                }
                await client.post(
                    "https://www.googleapis.com/youtube/v3/playlistItems?part=snippet",
                    headers=headers,
                    json=payload,
                )

    async def search_track(self, track: Track) -> Optional[Track]:
        headers = await self._auth_headers()
        query_parts = [track.title]
        if track.artists:
            query_parts.append(" ".join(track.artists))
        query = " ".join(query_parts)
        params = {
            "part": "snippet",
            "type": "video",
            "q": query,
            "maxResults": 5,
            "videoCategoryId": "10",  # Music
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://www.googleapis.com/youtube/v3/search",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            payload = response.json()
        items = payload.get("items", [])
        if not items:
            return None
        item = items[0]
        snippet = item.get("snippet") or {}
        artists = []
        if snippet.get("channelTitle"):
            artists.append(snippet["channelTitle"])
        return Track(
            id=(item.get("id") or {}).get("videoId", ""),
            title=snippet.get("title", ""),
            artists=artists,
            album=None,
            isrc=None,
            duration_ms=None,
        )
