#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_PUBLIC_PORT = 9000
DEFAULT_PLUGIN_BASE_PATH = "/mo-plugin"
DEFAULT_MEALIE_UPSTREAM = "http://mealie:9000"
DEFAULT_ORGANIZER_UPSTREAM = "http://mealie-organizer:9102"

INLINE_PORT_RE = re.compile(r"""['"]?(?P<host>\d+)\s*:\s*9000(?:/\w+)?['"]?""")
TARGET_RE = re.compile(r"^\s*(?:-\s*)?target\s*:\s*9000\s*$")
PUBLISHED_RE = re.compile(r"^\s*published\s*:\s*(?P<host>\d+)\s*$")


@dataclass(frozen=True)
class DiscoveredPort:
    port: int
    source: str


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            values[key] = value
    return values


def port_from_url(value: str | None) -> int | None:
    if not value:
        return None
    try:
        split = urlsplit(value)
    except Exception:
        return None
    if split.port is not None:
        return int(split.port)
    if split.scheme in {"http", "ws"}:
        return 80
    if split.scheme in {"https", "wss"}:
        return 443
    return None


def discover_compose_files(project_root: Path) -> list[Path]:
    direct = [
        project_root / "docker-compose.yml",
        project_root / "docker-compose.yaml",
        project_root / "compose.yml",
        project_root / "compose.yaml",
    ]
    files: list[Path] = [path for path in direct if path.exists()]
    for pattern in ("docker-compose*.yml", "docker-compose*.yaml", "compose*.yml", "compose*.yaml"):
        for path in project_root.glob(pattern):
            if path not in files:
                files.append(path)
    return sorted(files)


def discover_port_from_compose(path: Path) -> DiscoveredPort | None:
    lines = path.read_text(encoding="utf-8").splitlines()
    for idx, line in enumerate(lines, start=1):
        match = INLINE_PORT_RE.search(line)
        if match:
            return DiscoveredPort(port=int(match.group("host")), source=f"{path.name}:{idx}")

    saw_target_9000 = False
    for idx, line in enumerate(lines, start=1):
        if TARGET_RE.match(line):
            saw_target_9000 = True
            continue
        if not saw_target_9000:
            continue
        match = PUBLISHED_RE.match(line)
        if match:
            return DiscoveredPort(port=int(match.group("host")), source=f"{path.name}:{idx}")
    return None


def discover_public_port(project_root: Path, explicit_port: int | None) -> DiscoveredPort:
    if explicit_port is not None:
        return DiscoveredPort(port=explicit_port, source="--public-port")

    env_value = os.environ.get("MEALIE_PLUGIN_PUBLIC_PORT", "").strip()
    if env_value.isdigit():
        return DiscoveredPort(port=int(env_value), source="env:MEALIE_PLUGIN_PUBLIC_PORT")

    for candidate in (
        os.environ.get("MEALIE_URL", "").strip(),
        parse_env_file(project_root / ".env").get("MEALIE_URL", "").strip(),
    ):
        discovered = port_from_url(candidate)
        if discovered is not None:
            return DiscoveredPort(port=discovered, source="MEALIE_URL")

    for compose_file in discover_compose_files(project_root):
        discovered = discover_port_from_compose(compose_file)
        if discovered:
            return discovered

    return DiscoveredPort(port=DEFAULT_PUBLIC_PORT, source="default")


def normalize_base_path(value: str) -> str:
    raw = value.strip() or DEFAULT_PLUGIN_BASE_PATH
    if not raw.startswith("/"):
        raw = f"/{raw}"
    return raw.rstrip("/") or DEFAULT_PLUGIN_BASE_PATH


def render_nginx_conf(
    *,
    mealie_upstream: str,
    organizer_upstream: str,
    base_path: str,
) -> str:
    script_tag = f'<script src="{base_path}/static/injector.js"></script></body>'
    return f"""server {{
    listen 80;
    server_name _;

    location {base_path}/ {{
        proxy_pass {organizer_upstream.rstrip("/")};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}

    location / {{
        proxy_pass {mealie_upstream.rstrip("/")};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Accept-Encoding "";
        sub_filter_types text/html;
        sub_filter_once off;
        sub_filter '</body>' '{script_tag}';
    }}
}}
"""


def render_gateway_compose(relative_plugin_dir: str, public_port: int) -> str:
    rel = relative_plugin_dir.replace("\\", "/")
    return f"""services:
  mealie-plugin-gateway:
    image: nginx:1.27-alpine
    container_name: mealie-plugin-gateway
    restart: unless-stopped
    ports:
      - "{public_port}:80"
    volumes:
      - ./{rel}/nginx.conf:/etc/nginx/conf.d/default.conf:ro
    extra_hosts:
      - "host.docker.internal:host-gateway"
"""


def render_readme(
    *,
    public_port: int,
    port_source: str,
    config_path: Path,
    compose_path: Path,
    nginx_path: Path,
) -> str:
    return f"""# Mealie Plugin Gateway Bundle

Generated at {datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}.

## Generated Files

- Config: `{config_path.name}`
- Nginx conf: `{nginx_path}`
- Compose override: `{compose_path}`

## Discovery Summary

- Public Mealie port: `{public_port}` (source: `{port_source}`)

## Next Steps

1. Review and edit `{config_path.name}` if upstream URLs are not correct for your host.
2. Re-run this generator after config edits.
3. Stop exposing Mealie directly on host port `{public_port}` (to avoid port conflict with gateway).
4. Start gateway with your stack:

```bash
docker compose -f docker-compose.yml -f {compose_path} up -d mealie-plugin-gateway
```

5. Ensure organizer plugin server is running and reachable from the gateway on `/mo-plugin/*`.
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate no-fork Mealie UI plugin gateway bundle.")
    parser.add_argument("--project-root", default=".", help="Root directory of Mealie deployment files.")
    parser.add_argument("--output-dir", default="mealie-plugin", help="Directory (under project root) for generated files.")
    parser.add_argument("--public-port", type=int, default=None, help="Host port to preserve for Mealie URL.")
    parser.add_argument("--mealie-upstream", default="", help="Upstream Mealie URL for the gateway.")
    parser.add_argument("--organizer-upstream", default="", help="Upstream organizer plugin URL for /mo-plugin.")
    parser.add_argument("--plugin-base-path", default=DEFAULT_PLUGIN_BASE_PATH, help="URL base path for plugin routes.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    output_dir = (project_root / args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    discovered_port = discover_public_port(project_root, args.public_port)
    base_path = normalize_base_path(str(args.plugin_base_path))
    mealie_upstream = args.mealie_upstream.strip() or os.environ.get(
        "MEALIE_PLUGIN_MEALIE_UPSTREAM", DEFAULT_MEALIE_UPSTREAM
    )
    organizer_upstream = args.organizer_upstream.strip() or os.environ.get(
        "MEALIE_PLUGIN_ORGANIZER_UPSTREAM", DEFAULT_ORGANIZER_UPSTREAM
    )

    config_path = project_root / "mealie-plugin.config.json"
    config_payload = {
        "public_port": discovered_port.port,
        "public_port_source": discovered_port.source,
        "plugin_base_path": base_path,
        "mealie_upstream": mealie_upstream,
        "organizer_upstream": organizer_upstream,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    config_path.write_text(json.dumps(config_payload, indent=2), encoding="utf-8")

    nginx_path = output_dir / "nginx.conf"
    nginx_path.write_text(
        render_nginx_conf(
            mealie_upstream=mealie_upstream,
            organizer_upstream=organizer_upstream,
            base_path=base_path,
        ),
        encoding="utf-8",
    )

    compose_path = output_dir / "compose.plugin-gateway.yml"
    try:
        relative_output = output_dir.relative_to(project_root)
    except ValueError:
        relative_output = output_dir
    compose_path.write_text(
        render_gateway_compose(str(relative_output), discovered_port.port),
        encoding="utf-8",
    )

    readme_path = output_dir / "README.generated.md"
    readme_path.write_text(
        render_readme(
            public_port=discovered_port.port,
            port_source=discovered_port.source,
            config_path=config_path,
            compose_path=compose_path,
            nginx_path=nginx_path,
        ),
        encoding="utf-8",
    )

    print(f"[done] Wrote {config_path}", flush=True)
    print(f"[done] Wrote {nginx_path}", flush=True)
    print(f"[done] Wrote {compose_path}", flush=True)
    print(f"[done] Wrote {readme_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
