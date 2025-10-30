import asyncio

import pytest

from playlist_sync.app import create_app
from playlist_sync.config import AppConfig


@pytest.mark.asyncio
async def test_app_factory_startup_shutdown(monkeypatch, tmp_path):
    config = AppConfig(data_dir=tmp_path, host="127.0.0.1", port=9000, poll_interval_seconds=1)
    app = create_app(config)
    future = asyncio.Future()
    future.set_result(None)
    monkeypatch.setattr(asyncio, "create_task", lambda coro: future)

    await app.router.startup()
    assert app.state.config.host == "127.0.0.1"
    assert app.state.config.port == 9000

    await app.router.shutdown()
