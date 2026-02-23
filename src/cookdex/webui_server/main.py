from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import uvicorn

from .app import create_app
from .settings import load_webui_settings


def configure_logging(log_file: Path) -> None:
    """Set up rotating file + stderr-warnings logging; silence noisy third-party loggers."""
    log_file.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Rotating file: 2 MB × 5 backups = up to ~10 MB of server logs
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)

    # Console: warnings and above (startup banners use print(), not logging)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    ch.setLevel(logging.WARNING)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)

    # Silence uvicorn's per-request access log — every HTTP call at INFO is too noisy
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # Keep uvicorn startup/error messages
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    # Silence noisy third-party libraries
    for noisy in ("httpx", "urllib3", "requests", "apscheduler"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    settings = load_webui_settings()
    log_file = settings.logs_dir.parent / "server.log"
    configure_logging(log_file)

    app = create_app()

    ssl_kwargs: dict[str, str] = {}
    if settings.ssl_enabled and settings.ssl_certfile and settings.ssl_keyfile:
        ssl_kwargs["ssl_certfile"] = str(settings.ssl_certfile)
        ssl_kwargs["ssl_keyfile"] = str(settings.ssl_keyfile)

    uvicorn.run(
        app,
        host=settings.bind_host,
        port=settings.bind_port,
        # Prevent uvicorn from overwriting our logging config
        log_config=None,
        # Disable the built-in per-request access log (we silenced it above too)
        access_log=False,
        **ssl_kwargs,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
