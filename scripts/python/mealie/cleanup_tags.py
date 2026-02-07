import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MANAGER = SCRIPT_DIR / "taxonomy_manager.py"


def main():
    print("[info] cleanup_tags.py is a compatibility wrapper.")
    print("[info] Use taxonomy_manager.py cleanup for new workflows.")
    cmd = [sys.executable, str(MANAGER), "cleanup", *sys.argv[1:]]
    raise SystemExit(subprocess.call(cmd, env=os.environ.copy()))


if __name__ == "__main__":
    main()
