from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

import requests

from fastapi import APIRouter, Depends

from ... import __version__
from ..deps import Services, build_runtime_env, require_services, require_session

router = APIRouter(tags=["meta"])

_HELP_DOCS: tuple[dict[str, str], ...] = (
    {"id": "quick-start", "title": "Quick Start Checklist", "group": "Setup", "file": "GETTING_STARTED.md"},
    {"id": "install-update", "title": "Install and Update", "group": "Setup", "file": "INSTALL.md"},
    {"id": "tasks-api", "title": "Tasks and API Reference", "group": "Troubleshooting", "file": "TASKS.md"},
    {"id": "data-pipeline", "title": "Data Maintenance Pipeline", "group": "Troubleshooting", "file": "DATA_MAINTENANCE.md"},
)


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
    except requests.RequestException as exc:
        payload["reason"] = f"Unable to fetch Mealie metrics: {exc}"
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
        "labels": 0,
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
    return {"ok": True, "base_path": services.settings.base_path, "version": __version__}


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
        "app_version": __version__,
        "webui_version": "1.0",
        "counts": {
            "tasks": len(services.registry.task_ids),
            "users": len(services.state.list_users()),
            "runs": len(services.state.list_runs(limit=500)),
            "schedules": len(services.scheduler.list_schedules()),
            "config_files": len(services.config_files.list_files()),
        },
        "links": {
            "github": "https://github.com/thekannen/cookdex",
            "sponsor": "https://github.com/sponsors/thekannen",
        },
    }


@router.get("/help/docs")
async def get_help_docs(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    return {"items": _build_help_docs_payload(services)}
