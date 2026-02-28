from __future__ import annotations

import asyncio
import platform
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import requests

from fastapi import APIRouter, Depends, Query

from ... import _read_version
from ..deps import Services, build_runtime_env, require_services, require_session

router = APIRouter(tags=["meta"])

_HELP_DOCS: tuple[dict[str, str], ...] = (
    {"id": "tasks-api", "title": "Tasks and API Reference", "group": "Reference", "file": "TASKS.md"},
    {"id": "data-pipeline", "title": "Data Maintenance Pipeline", "group": "Reference", "file": "DATA_MAINTENANCE.md"},
    {"id": "parser-migration", "title": "Parser Configuration", "group": "Reference", "file": "PARSER_MIGRATION.md"},
)


_GITHUB_URL = "https://github.com/thekannen/cookdex"
_FUNDING_PATH = Path(__file__).resolve().parent.parent.parent.parent.parent / ".github" / "FUNDING.yml"


def _read_project_links() -> dict[str, str]:
    links: dict[str, str] = {"github": _GITHUB_URL}
    try:
        text = _FUNDING_PATH.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition(":")
            value = value.strip()
            if key.strip() == "github" and value:
                links["sponsor"] = f"https://github.com/sponsors/{value}"
                break
            if key.strip() in {"ko_fi", "buy_me_a_coffee", "custom"} and value:
                links["sponsor"] = value if value.startswith("http") else f"https://{value}"
                break
    except FileNotFoundError:
        pass
    return links


def _percent(part: int, total: int) -> int:
    if total <= 0:
        return 0
    return int(round((part / total) * 100))


def _top_counter_rows(counter: Counter[str], denominator: int, limit: int = 6) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, count in counter.most_common(limit):
        rows.append({"name": name, "count": int(count), "percent": _percent(int(count), denominator)})
    return rows


def _build_help_docs_payload(services: Services) -> list[dict[str, str]]:
    docs_root = (services.settings.config_root / "docs").resolve()
    payload: list[dict[str, str]] = []

    for item in _HELP_DOCS:
        path = (docs_root / item["file"]).resolve()
        try:
            path.relative_to(docs_root)
        except ValueError:
            continue
        if not path.exists() or not path.is_file():
            continue

        payload.append(
            {
                "id": item["id"],
                "title": item["title"],
                "group": item["group"],
                "content": path.read_text(encoding="utf-8"),
            }
        )

    return payload


def _build_overview_metrics_sync(services: Services) -> dict[str, Any]:
    """Synchronous overview metrics builder; called via asyncio.to_thread."""
    from ...api_client import MealieApiClient

    runtime_env = build_runtime_env(services.state, services.cipher)
    mealie_url = str(runtime_env.get("MEALIE_URL", "")).strip().rstrip("/")
    mealie_api_key = str(runtime_env.get("MEALIE_API_KEY", "")).strip()

    payload: dict[str, Any] = {
        "ok": False,
        "reason": "",
        "totals": {
            "recipes": 0,
            "ingredients": 0,
            "tools": 0,
            "categories": 0,
            "tags": 0,
            "labels": 0,
            "units": 0,
        },
        "coverage": {"categories": 0, "tags": 0, "tools": 0},
        "top": {"categories": [], "tags": [], "tools": []},
    }

    if not mealie_url or not mealie_api_key:
        payload["reason"] = "Set Mealie URL and API key in Settings to load live overview metrics."
        return payload

    try:
        client = MealieApiClient(base_url=mealie_url, api_key=mealie_api_key)
        recipes = client.get_recipes()
        categories = client.get_organizer_items("categories")
        tags = client.get_organizer_items("tags")
        tools = client.list_tools()
        foods = client.list_foods()
        units = client.list_units()
        labels = client.list_labels()
    except requests.RequestException as exc:
        payload["reason"] = f"Unable to fetch Mealie metrics: {type(exc).__name__}."
        return payload

    recipe_total = len(recipes)

    recipes_with_categories = 0
    recipes_with_tags = 0
    recipes_with_tools = 0

    category_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    tool_counter: Counter[str] = Counter()

    for recipe in recipes:
        category_rows = recipe.get("recipeCategory") or []
        tag_rows = recipe.get("tags") or []
        tool_rows = recipe.get("tools") or recipe.get("recipeTool") or []

        if isinstance(category_rows, list) and len(category_rows) > 0:
            recipes_with_categories += 1
            for row in category_rows:
                if isinstance(row, dict):
                    name = str(row.get("name") or "").strip()
                    if name:
                        category_counter[name] += 1

        if isinstance(tag_rows, list) and len(tag_rows) > 0:
            recipes_with_tags += 1
            for row in tag_rows:
                if isinstance(row, dict):
                    name = str(row.get("name") or "").strip()
                    if name:
                        tag_counter[name] += 1

        if isinstance(tool_rows, list) and len(tool_rows) > 0:
            recipes_with_tools += 1
            for row in tool_rows:
                if isinstance(row, dict):
                    name = str(row.get("name") or "").strip()
                    if name:
                        tool_counter[name] += 1

    payload["ok"] = True
    payload["totals"] = {
        "recipes": recipe_total,
        "ingredients": len(foods),
        "tools": len(tools),
        "categories": len(categories),
        "tags": len(tags),
        "labels": len(labels),
        "units": len(units),
    }
    payload["coverage"] = {
        "categories": _percent(recipes_with_categories, recipe_total),
        "tags": _percent(recipes_with_tags, recipe_total),
        "tools": _percent(recipes_with_tools, recipe_total),
    }
    payload["top"] = {
        "categories": _top_counter_rows(category_counter, recipe_total),
        "tags": _top_counter_rows(tag_counter, recipe_total),
        "tools": _top_counter_rows(tool_counter, recipe_total),
    }
    return payload


@router.get("/health")
async def health(services: Services = Depends(require_services)) -> dict[str, Any]:
    return {"ok": True, "base_path": services.settings.base_path, "version": _read_version()}


@router.get("/metrics/overview")
async def get_overview_metrics(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    return await asyncio.to_thread(_build_overview_metrics_sync, services)


@router.get("/about/meta")
async def get_about_meta(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    return {
        "app_version": _read_version(),
        "webui_version": _read_version(),
        "counts": {
            "tasks": len(services.registry.task_ids),
            "users": len(services.state.list_users()),
            "runs": len(services.state.list_runs(limit=500)),
            "schedules": len(services.scheduler.list_schedules()),
            "config_files": len(services.config_files.list_files()),
        },
        "links": _read_project_links(),
    }


@router.get("/metrics/quality")
async def get_quality_metrics(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    report_path = services.settings.config_root / "reports" / "quality_audit_report.json"
    if not report_path.exists():
        return {"available": False}
    try:
        import json as _json
        data = _json.loads(report_path.read_text(encoding="utf-8"))
        summary = data.get("summary", {})
        total = int(summary.get("total") or 0)
        gold = int(summary.get("gold") or 0)
        silver = int(summary.get("silver") or 0)
        bronze = int(summary.get("bronze") or 0)
        gold_pct = float(summary.get("gold_pct") or 0)
        dim_coverage = data.get("dimension_coverage", {})
        return {
            "available": True,
            "total": total,
            "gold": gold,
            "silver": silver,
            "bronze": bronze,
            "gold_pct": gold_pct,
            "dimension_coverage": dim_coverage,
        }
    except Exception:
        return {"available": False}


@router.get("/help/docs")
async def get_help_docs(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    return {"items": _build_help_docs_payload(services)}


def _build_health_report(services: Services) -> dict[str, Any]:
    """Collect instance health metrics + live connection tests for debug reports."""
    from .settings_api import (
        _test_anthropic_connection,
        _test_db_connection,
        _test_mealie_connection,
        _test_ollama_connection,
        _test_openai_connection,
    )

    users = services.state.list_users()
    all_runs = services.state.list_runs(limit=500)
    schedules = services.scheduler.list_schedules()

    # Run status tallies
    status_counts: dict[str, int] = {}
    for run in all_runs:
        s = str(run.get("status", "unknown"))
        status_counts[s] = status_counts.get(s, 0) + 1

    # Most recent 10 runs for the snapshot
    recent_runs = [
        {
            "run_id": str(r.get("run_id", ""))[:8],
            "task_id": r.get("task_id", ""),
            "status": r.get("status", ""),
            "triggered_by": r.get("triggered_by", ""),
            "started_at": r.get("started_at") or r.get("created_at"),
            "exit_code": r.get("exit_code"),
        }
        for r in all_runs[:10]
    ]

    runtime_env = build_runtime_env(services.state, services.cipher)
    mealie_url = str(runtime_env.get("MEALIE_URL", "")).strip().rstrip("/")
    mealie_api_key = str(runtime_env.get("MEALIE_API_KEY", "")).strip()
    openai_api_key = str(runtime_env.get("OPENAI_API_KEY", "")).strip()
    openai_model = str(runtime_env.get("OPENAI_MODEL", "")).strip()
    anthropic_api_key = str(runtime_env.get("ANTHROPIC_API_KEY", "")).strip()
    anthropic_model = str(runtime_env.get("ANTHROPIC_MODEL", "")).strip()
    ollama_url = str(runtime_env.get("OLLAMA_URL", "")).strip()
    ollama_model = str(runtime_env.get("OLLAMA_MODEL", "")).strip()

    enabled_schedules = sum(1 for s in schedules if s.get("enabled"))

    # Live connection tests — only attempt if credentials are present
    def _conn(ok: bool, detail: str) -> dict[str, Any]:
        return {"ok": ok, "detail": detail}

    if mealie_url and mealie_api_key:
        mealie_conn = _conn(*_test_mealie_connection(mealie_url, mealie_api_key))
    else:
        mealie_conn = _conn(False, "Not configured")

    if openai_api_key:
        openai_conn = _conn(*_test_openai_connection(openai_api_key, openai_model or "gpt-4o-mini"))
    else:
        openai_conn = _conn(False, "Not configured")

    if anthropic_api_key:
        anthropic_conn = _conn(*_test_anthropic_connection(anthropic_api_key, anthropic_model or "claude-sonnet-4-6"))
    else:
        anthropic_conn = _conn(False, "Not configured")

    if ollama_url:
        ollama_conn = _conn(*_test_ollama_connection(ollama_url, ollama_model))
    else:
        ollama_conn = _conn(False, "Not configured")

    db_conn = _conn(*_test_db_connection(runtime_env))

    return {
        "db": {
            "user_count": len(users),
            "run_count": len(all_runs),
            "schedule_count": len(schedules),
            "enabled_schedules": enabled_schedules,
        },
        "config": {
            "mealie_url": mealie_url or None,
            "mealie_key_set": bool(mealie_api_key),
            "openai_key_set": bool(openai_api_key),
            "openai_model": openai_model or None,
            "anthropic_key_set": bool(anthropic_api_key),
            "anthropic_model": anthropic_model or None,
            "ollama_url": ollama_url or None,
            "ollama_model": ollama_model or None,
        },
        "connections": {
            "mealie": mealie_conn,
            "openai": openai_conn,
            "anthropic": anthropic_conn,
            "ollama": ollama_conn,
            "direct_db": db_conn,
        },
        "runs": {
            "status_counts": status_counts,
            "recent": recent_runs,
        },
        "scheduler": {
            "running": services.scheduler.scheduler.running,
        },
    }


@router.get("/debug-log")
async def get_debug_log(
    lines: int = Query(default=300, ge=10, le=2000),
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    """Return recent server log lines, live connection tests, and system context for bug reports."""
    def _build() -> dict[str, Any]:
        log_file = services.settings.logs_dir.parent / "server.log"
        log_content = ""
        log_available = log_file.exists()
        if log_available:
            try:
                text = log_file.read_text(encoding="utf-8", errors="replace")
                all_lines = [
                    ln for ln in text.splitlines()
                    if "Invalid HTTP request received" not in ln
                ]
                log_content = "\n".join(all_lines[-lines:])
            except OSError:
                log_content = "(unable to read log file)"

        return {
            "app_version": _read_version(),
            "python_version": sys.version,
            "platform": platform.platform(),
            "log_file": str(log_file),
            "log_available": log_available,
            "health": _build_health_report(services),
            "log": log_content,
        }

    return await asyncio.to_thread(_build)
