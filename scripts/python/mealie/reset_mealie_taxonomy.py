import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
MANAGER = SCRIPT_DIR / "taxonomy_manager.py"


def main():
    cmd = [
        sys.executable,
        str(MANAGER),
        "reset",
        "--categories-file",
        "scripts/python/mealie/categories.json",
    ]

    tags_file = SCRIPT_DIR / "tags.json"
    if tags_file.exists():
        cmd.extend(["--tags-file", "scripts/python/mealie/tags.json"])
    else:
        cmd.append("--skip-tags")

    print("[info] reset_mealie_taxonomy.py is a compatibility wrapper.")
    print("[info] Use taxonomy_manager.py reset for new workflows.")
    raise SystemExit(subprocess.call(cmd, env=os.environ.copy()))


if __name__ == "__main__":
    main()
