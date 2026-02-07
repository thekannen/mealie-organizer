import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from mealie_scripts.categorizer_core import *  # noqa: F401,F403
