from __future__ import annotations

from .webui_server.main import main as webui_main


def main() -> int:
    print("[warn] 'plugin-server' is deprecated; starting 'webui-server' instead.", flush=True)
    return webui_main()


if __name__ == "__main__":
    raise SystemExit(main())