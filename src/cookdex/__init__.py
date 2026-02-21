from .config import REPO_ROOT


def _read_version() -> str:
    version_file = REPO_ROOT / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("cookdex")
    except PackageNotFoundError:
        return "0.0.0"


__version__ = _read_version()

__all__ = ["REPO_ROOT", "__version__", "_read_version"]
