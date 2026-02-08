import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"
CONFIG_FILE = REPO_ROOT / "configs" / "config.json"


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
