from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

DEFAULT_DATA_DIR = Path(
    os.getenv("PLAYLIST_SYNC_DATA", Path.home() / ".local" / "share" / "playlist-sync")
).expanduser()


@dataclass
class AppConfig:
    """Static configuration for the service."""

    host: str = field(default_factory=lambda: os.getenv("PLAYLIST_SYNC_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.getenv("PLAYLIST_SYNC_PORT", "8080")))
    poll_interval_seconds: int = field(
        default_factory=lambda: int(os.getenv("PLAYLIST_SYNC_POLL_INTERVAL", "60"))
    )
    data_dir: Path = field(default_factory=lambda: DEFAULT_DATA_DIR)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


@dataclass
class OAuthConfig:
    """Configuration for OAuth credentials provided by the user."""

    spotify_client_id: str | None = None
    spotify_client_secret: str | None = None
    spotify_redirect_uri: str | None = None
    youtube_client_id: str | None = None
    youtube_client_secret: str | None = None
    apple_developer_token: str | None = None

    @classmethod
    def from_env(cls) -> "OAuthConfig":
        return cls(
            spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID"),
            spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET"),
            spotify_redirect_uri=os.getenv("SPOTIFY_REDIRECT_URI"),
            youtube_client_id=os.getenv("YOUTUBE_CLIENT_ID"),
            youtube_client_secret=os.getenv("YOUTUBE_CLIENT_SECRET"),
            apple_developer_token=os.getenv("APPLE_DEVELOPER_TOKEN"),
        )

    def as_dict(self) -> Dict[str, Any]:
        return {
            "spotify_client_id": self.spotify_client_id,
            "spotify_client_secret": self.spotify_client_secret,
            "spotify_redirect_uri": self.spotify_redirect_uri,
            "youtube_client_id": self.youtube_client_id,
            "youtube_client_secret": self.youtube_client_secret,
            "apple_developer_token": self.apple_developer_token,
        }
