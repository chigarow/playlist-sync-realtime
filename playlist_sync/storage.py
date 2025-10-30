from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional


class JSONStorage:
    """Tiny JSON-backed key-value store with async locks."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    async def _read(self) -> Dict[str, Any]:
        def _load() -> Dict[str, Any]:
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}

        return await asyncio.to_thread(_load)

    async def _write(self, payload: Dict[str, Any]) -> None:
        def _dump() -> None:
            self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

        await asyncio.to_thread(_dump)

    async def get(self, key: str, default: Optional[Any] = None) -> Any:
        async with self._lock:
            data = await self._read()
            return data.get(key, default)

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            data = await self._read()
            data[key] = value
            await self._write(data)

    async def delete(self, key: str) -> None:
        async with self._lock:
            data = await self._read()
            if key in data:
                data.pop(key)
                await self._write(data)
