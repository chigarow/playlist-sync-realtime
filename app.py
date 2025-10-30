from __future__ import annotations

import uvicorn

from playlist_sync import create_app
from playlist_sync.config import AppConfig


def main() -> None:
    config = AppConfig()
    app = create_app(config)
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
