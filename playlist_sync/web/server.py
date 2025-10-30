from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from playlist_sync.config import AppConfig
from playlist_sync.connectors.apple_music import AppleMusicConnector
from playlist_sync.connectors.base import Connector, OAuthError
from playlist_sync.models import ServiceType
from playlist_sync.storage import JSONStorage
from playlist_sync.sync import SyncManager


def build_app(
    *,
    config: AppConfig,
    storage: JSONStorage,
    connectors: Mapping[ServiceType, Connector],
    sync_manager: SyncManager,
) -> FastAPI:
    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        statuses = {}
        for service, connector in connectors.items():
            statuses[service.value] = {
                "configured": connector.is_configured(),
                "authenticated": await connector.token_ready(),
            }
        groups = [group.to_dict() for group in await sync_manager.load_groups()]
        playlists = {}
        for service, connector in connectors.items():
            if await connector.token_ready():
                try:
                    playlists[service.value] = [
                        {"id": playlist.id, "name": playlist.name, "track_count": playlist.track_count}
                        for playlist in await connector.list_playlists()
                    ]
                except Exception:
                    playlists[service.value] = []
            else:
                playlists[service.value] = []
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "statuses": statuses,
                "groups": groups,
                "playlists": playlists,
                "host": config.host,
                "port": config.port,
            },
        )

    @app.get("/auth/{service}/start")
    async def auth_start(service: str) -> RedirectResponse:
        try:
            service_type = ServiceType(service)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Unknown service") from exc
        connector = connectors.get(service_type)
        if connector is None or not connector.is_configured():
            raise HTTPException(status_code=400, detail="Connector not configured.")
        url = await connector.oauth_start()
        return RedirectResponse(url=url)

    @app.get("/auth/{service}/callback")
    async def auth_callback(request: Request, service: str):
        try:
            service_type = ServiceType(service)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Unknown service") from exc
        connector = connectors.get(service_type)
        if connector is None:
            raise HTTPException(status_code=400, detail="Connector not configured.")
        params = dict(request.query_params)
        try:
            await connector.oauth_complete(params)
        except OAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url="/")

    @app.post("/api/apple/developer-token")
    async def apple_developer_token(payload: Dict[str, object]):
        connector = connectors.get(ServiceType.APPLE_MUSIC)
        if not isinstance(connector, AppleMusicConnector):
            raise HTTPException(status_code=400, detail="Apple Music connector unavailable.")
        token = payload.get("developer_token")
        if not token:
            raise HTTPException(status_code=400, detail="developer_token missing")
        await connector.set_developer_token(str(token))
        return JSONResponse({"ok": True})

    @app.post("/api/apple/token")
    async def apple_token(payload: Dict[str, object]):
        connector = connectors.get(ServiceType.APPLE_MUSIC)
        if connector is None:
            raise HTTPException(status_code=400, detail="Apple Music connector unavailable.")
        developer_token = payload.get("developer_token")
        music_user_token = payload.get("music_user_token")
        try:
            await connector.oauth_complete(
                {
                    "developer_token": str(developer_token or ""),
                    "music_user_token": str(music_user_token or ""),
                }
            )
        except OAuthError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True})

    @app.get("/api/playlists")
    async def api_playlists():
        result = {}
        for service, connector in connectors.items():
            if await connector.token_ready():
                try:
                    result[service.value] = [
                        {"id": playlist.id, "name": playlist.name, "count": playlist.track_count}
                        for playlist in await connector.list_playlists()
                    ]
                except Exception:
                    result[service.value] = []
            else:
                result[service.value] = []
        return JSONResponse(result)

    @app.get("/api/groups")
    async def api_groups():
        groups = await sync_manager.load_groups()
        return JSONResponse([group.to_dict() for group in groups])

    @app.post("/api/groups")
    async def api_create_group(payload: Dict[str, object]):
        try:
            name = str(payload["name"])
            primary_service = ServiceType(str(payload["primary_service"]))
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload") from exc
        playlists_payload = payload.get("playlists") or {}
        if not isinstance(playlists_payload, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid playlists payload")
        playlists = {}
        for key, value in playlists_payload.items():
            try:
                playlists[ServiceType(str(key))] = str(value)
            except ValueError:
                continue
        group = await sync_manager.create_group(name, primary_service, playlists)
        return JSONResponse(group.to_dict())

    @app.delete("/api/groups/{group_id}")
    async def api_delete_group(group_id: str):
        await sync_manager.delete_group(group_id)
        return JSONResponse({"ok": True})

    @app.post("/api/groups/{group_id}/playlists")
    async def api_update_group(group_id: str, payload: Dict[str, object]):
        playlists_payload = payload.get("playlists") or {}
        if not isinstance(playlists_payload, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid playlists payload")
        playlists = {}
        for key, value in playlists_payload.items():
            try:
                playlists[ServiceType(str(key))] = str(value)
            except ValueError:
                continue
        updated = await sync_manager.update_group(group_id, playlists)
        if not updated:
            raise HTTPException(status_code=404, detail="Group not found")
        return JSONResponse(updated.to_dict())

    return app
