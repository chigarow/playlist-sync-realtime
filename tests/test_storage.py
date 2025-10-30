import pytest

from playlist_sync.storage import JSONStorage


@pytest.mark.asyncio
async def test_json_storage_set_get_delete(tmp_path):
    storage = JSONStorage(tmp_path / "state.json")
    assert await storage.get("missing") is None

    await storage.set("token", {"value": 1})
    assert await storage.get("token") == {"value": 1}

    await storage.delete("token")
    assert await storage.get("token") is None
