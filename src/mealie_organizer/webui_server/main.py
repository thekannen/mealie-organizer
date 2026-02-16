from __future__ import annotations

import uvicorn

from .app import create_app
from .settings import load_webui_settings


def main() -> int:
    settings = load_webui_settings()
    app = create_app()
    uvicorn.run(
        app,
        host=settings.bind_host,
        port=settings.bind_port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
