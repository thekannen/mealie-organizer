import json
import os
from pathlib import Path


def _looks_like_repo_root(path: Path) -> bool:
    return (path / "configs" / "config.json").exists() or (path / "configs" / "taxonomy").exists()


def _discover_repo_root() -> Path:
    env_root = os.environ.get("MEALIE_ORGANIZER_ROOT", "").strip()
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if candidate.exists():
            return candidate

    source_root = Path(__file__).resolve().parents[2]
    for candidate in (Path.cwd(), Path("/app"), source_root):
        if _looks_like_repo_root(candidate):
            return candidate
    return source_root


REPO_ROOT = _discover_repo_root()
ENV_FILE = REPO_ROOT / ".env"
CONFIG_FILE = REPO_ROOT / "configs" / "config.json"
MEALIE_URL_PLACEHOLDER = "http://your.server.ip.address:9000/api"


def load_env_file(path):
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        if line.startswith("export "):
            line = line[len("export ") :].strip()

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue

        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        os.environ.setdefault(key, value)


load_env_file(ENV_FILE)


def _load_config():
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


_CONFIG = _load_config()


def config_value(path, default=None):
    current = _CONFIG
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off", ""}:
            return False
    raise ValueError(f"Invalid boolean value: {value}")


def require_mealie_url(value):
    if not isinstance(value, str):
        raise RuntimeError(f"MEALIE_URL must be a string, got {type(value).__name__}.")

    url = value.strip()
    if not url or url.lower() == MEALIE_URL_PLACEHOLDER.lower() or "your.server.ip.address" in url.lower():
        raise RuntimeError(
            "MEALIE_URL is not configured. Set MEALIE_URL in .env or the environment."
        )

    return url.rstrip("/")


def env_or_config(env_key, config_path, default=None, cast=None):
    raw_env = os.environ.get(env_key)
    if raw_env is not None and raw_env != "":
        raw = raw_env
        source = f"env '{env_key}'"
    else:
        raw = config_value(config_path, default)
        source = f"config '{config_path}'"

    if raw is None:
        return None

    if cast is None:
        return raw

    try:
        return cast(raw)
    except Exception as exc:
        raise ValueError(f"Invalid value from {source}: {raw}") from exc


def secret(env_key, required=False, default=""):
    value = os.environ.get(env_key, default)
    if required and not value:
        raise RuntimeError(f"{env_key} is empty. Set it in .env or the environment.")
    return value


def resolve_repo_path(path_value):
    path = Path(path_value)
    if path.is_absolute():
        return path
    return REPO_ROOT / path


def resolve_mealie_url():
    primary = os.environ.get("MEALIE_URL")
    legacy = os.environ.get("MEALIE_BASE_URL")
    if primary and primary.strip():
        return require_mealie_url(primary)
    if legacy and legacy.strip():
        print("[warn] MEALIE_BASE_URL is deprecated; prefer MEALIE_URL.", flush=True)
        return require_mealie_url(legacy)
    fallback = config_value("mealie.url", MEALIE_URL_PLACEHOLDER)
    return require_mealie_url(fallback)


def resolve_mealie_api_key(required=True):
    primary = os.environ.get("MEALIE_API_KEY", "").strip()
    if primary:
        return primary
    legacy = os.environ.get("MEALIE_API_TOKEN", "").strip()
    if legacy:
        print("[warn] MEALIE_API_TOKEN is deprecated; prefer MEALIE_API_KEY.", flush=True)
        return legacy
    if required:
        raise RuntimeError("MEALIE_API_KEY is empty. Set MEALIE_API_KEY (or legacy MEALIE_API_TOKEN).")
    return ""
