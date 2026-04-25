from __future__ import annotations

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _router_paths() -> set[str]:
    paths: set[str] = set()
    for path in (ROOT / "src" / "cookdex" / "webui_server" / "routers").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "router"
                    and func.attr in {"get", "post", "put", "patch", "delete"}
                ):
                    continue
                if decorator.args and isinstance(decorator.args[0], ast.Constant):
                    value = decorator.args[0].value
                    if isinstance(value, str):
                        paths.add(value)
    return paths


def test_tasks_api_reference_lists_current_routes() -> None:
    docs = (ROOT / "docs" / "TASKS.md").read_text(encoding="utf-8")

    missing = sorted(path for path in _router_paths() if path not in docs)

    assert missing == []


def test_user_facing_docs_only_advertise_supported_schedule_kinds() -> None:
    schedule_docs = [
        ROOT / "README.md",
        ROOT / "docs" / "DATA_MAINTENANCE.md",
        ROOT / "docs" / "TASKS.md",
        ROOT / "web" / "src" / "constants.js",
    ]

    offenders = []
    for path in schedule_docs:
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bcron\b", text, flags=re.IGNORECASE):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_direct_db_docs_match_docker_first_setup() -> None:
    task_docs = (ROOT / "docs" / "TASKS.md").read_text(encoding="utf-8")

    assert "pip install 'cookdex[db]'" not in task_docs
    assert "DB credentials in `.env`" not in task_docs
