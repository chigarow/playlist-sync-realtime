from __future__ import annotations

import abc
from typing import Dict, Iterable, List, Optional

from playlist_sync.models import Playlist, ServiceType, Track


class OAuthError(Exception):
    """Raised when OAuth authentication cannot be completed."""


class Connector(abc.ABC):
    """Shared contract for music service connectors."""

    service: ServiceType

    @abc.abstractmethod
    def is_configured(self) -> bool:
        """Return whether the connector has the required credentials."""

    @abc.abstractmethod
    async def oauth_start(self) -> str:
        """Return a URL the user should visit to begin authentication."""

    @abc.abstractmethod
    async def oauth_complete(self, query_params: Dict[str, str]) -> None:
        """Handle OAuth callback and persist tokens."""

    @abc.abstractmethod
    async def token_ready(self) -> bool:
        """Return whether the connector already holds valid tokens."""

    @abc.abstractmethod
    async def list_playlists(self) -> List[Playlist]:
        """Return available playlists for the authenticated user."""

    @abc.abstractmethod
    async def list_tracks(self, playlist_id: str) -> List[Track]:
        """Return tracks for a playlist."""

    @abc.abstractmethod
    async def ensure_playlist(self, name: str) -> Playlist:
        """Get or create a playlist with the given name."""

    @abc.abstractmethod
    async def replace_tracks(self, playlist_id: str, tracks: Iterable[Track]) -> None:
        """Replace playlist tracks with the provided ones."""

    @abc.abstractmethod
    async def search_track(self, track: Track) -> Optional[Track]:
        """Search for an equivalent track on this service."""
