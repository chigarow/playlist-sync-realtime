from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ServiceType(str, Enum):
    SPOTIFY = "spotify"
    APPLE_MUSIC = "apple_music"
    YOUTUBE_MUSIC = "youtube_music"


@dataclass
class Track:
    id: str
    title: str
    artists: List[str] = field(default_factory=list)
    album: Optional[str] = None
    isrc: Optional[str] = None
    duration_ms: Optional[int] = None

    def normalized_signature(self) -> str:
        artists = " ".join(self.artists).lower()
        album = (self.album or "").lower()
        return f"{self.title.lower()}|{artists}|{album}"


@dataclass
class Playlist:
    id: str
    name: str
    service: ServiceType
    track_count: int = 0
