from __future__ import annotations

import asyncio
from typing import Dict

from fastapi import FastAPI

from playlist_sync.config import AppConfig, OAuthConfig
from playlist_sync.connectors import AppleMusicConnector, SpotifyConnector, YouTubeMusicConnector
from playlist_sync.connectors.base import Connector
from playlist_sync.models import ServiceType
from playlist_sync.storage import JSONStorage
from playlist_sync.sync import SyncManager
from playlist_sync.web import build_app


def create_app(config: AppConfig | None = None) -> FastAPI:
    config = config or AppConfig()
    config.ensure_dirs()
    oauth = OAuthConfig.from_env()
    storage = JSONStorage(config.data_dir / "state.json")

    connectors: Dict[ServiceType, Connector] = {
        ServiceType.SPOTIFY: SpotifyConnector(
            storage=storage,
            client_id=oauth.spotify_client_id,
            client_secret=oauth.spotify_client_secret,
            redirect_uri=oauth.spotify_redirect_uri,
        ),
        ServiceType.APPLE_MUSIC: AppleMusicConnector(
            storage=storage,
            developer_token=oauth.apple_developer_token,
        ),
        ServiceType.YOUTUBE_MUSIC: YouTubeMusicConnector(
            storage=storage,
            client_id=oauth.youtube_client_id,
            client_secret=oauth.youtube_client_secret,
        ),
    }
    sync_manager = SyncManager(storage=storage, connectors=connectors)
    app = build_app(config=config, storage=storage, connectors=connectors, sync_manager=sync_manager)
    app.state.config = config
    app.state.connectors = connectors

    @app.on_event("startup")
    async def _startup() -> None:
        app.state.sync_task = asyncio.create_task(sync_manager.run(config.poll_interval_seconds))

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await sync_manager.stop()
        task: asyncio.Task | None = getattr(app.state, "sync_task", None)
        if task:
            await task

    return app
