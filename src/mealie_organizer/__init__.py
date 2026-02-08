from importlib.metadata import PackageNotFoundError, version

from .config import REPO_ROOT


def _version_from_file() -> str:
    version_file = REPO_ROOT / "VERSION"
    if version_file.exists():
        return version_file.read_text(encoding="utf-8").strip()
    return "0.0.0"


try:
    __version__ = version("mealie-organizer")
except PackageNotFoundError:
    __version__ = _version_from_file()

__all__ = ["REPO_ROOT", "__version__"]
