from __future__ import annotations

import json
from typing import Any

import requests
from fastapi import APIRouter, Depends, HTTPException

from ...api_client import MealieApiClient
from ..deps import Services, build_runtime_env, require_services, require_session, resolve_runtime_value
from ..schemas import (
    ConfigWriteRequest,
    StarterPackImportRequest,
    TaxonomySyncRequest,
    TaxonomyWorkspaceDraftUpdateRequest,
    TaxonomyWorkspaceVersionRequest,
)
from ..taxonomy_workspace import TaxonomyWorkspaceDraftService, TaxonomyWorkspaceService, WorkspaceVersionConflictError

router = APIRouter(tags=["config"])


def _lookup_rows(items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip()
        if not item_id or not name or item_id in seen:
            continue
        seen.add(item_id)
        out.append({"id": item_id, "name": name})
    return out


@router.get("/config/files")
async def list_config_files(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    return {"items": services.config_files.list_files()}


@router.get("/config/files/{name}")
async def get_config_file(
    name: str,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    try:
        return services.config_files.read_file(name)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown config file.")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Config file not found.")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Invalid JSON in config file.")


@router.put("/config/files/{name}")
async def put_config_file(
    name: str,
    payload: ConfigWriteRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    try:
        result = services.config_files.write_file(name, payload.content)
        if name in {"categories", "tags", "tools"}:
            workspace = TaxonomyWorkspaceService(
                repo_root=services.settings.config_root,
                config_files=services.config_files,
            )
            result["rule_sync"] = workspace.sync_tag_rules_targets()
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown config file.")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/config/taxonomy/starter-pack")
async def get_starter_pack_info(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    workspace = TaxonomyWorkspaceService(repo_root=services.settings.config_root, config_files=services.config_files)
    return workspace.starter_pack_info()


@router.post("/config/taxonomy/initialize-from-mealie")
async def initialize_taxonomy_from_mealie(
    payload: TaxonomySyncRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    runtime_env = build_runtime_env(services.state, services.cipher)
    mealie_url = resolve_runtime_value(runtime_env, "MEALIE_URL")
    mealie_api_key = resolve_runtime_value(runtime_env, "MEALIE_API_KEY")
    if not mealie_url or not mealie_api_key:
        raise HTTPException(status_code=422, detail="Set Mealie URL and API key in Settings before initializing.")

    workspace = TaxonomyWorkspaceService(repo_root=services.settings.config_root, config_files=services.config_files)
    try:
        return workspace.initialize_from_mealie(
            mealie_url=mealie_url,
            mealie_api_key=mealie_api_key,
            mode=payload.mode,
            include_files=payload.files,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except requests.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to read taxonomy from Mealie: {exc}")


@router.post("/config/taxonomy/import-starter-pack")
async def import_starter_pack(
    payload: StarterPackImportRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    workspace = TaxonomyWorkspaceService(repo_root=services.settings.config_root, config_files=services.config_files)
    try:
        return workspace.import_starter_pack(
            mode=payload.mode,
            include_files=payload.files,
            base_url=payload.base_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except requests.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to download starter pack: {exc}")


@router.get("/config/workspace/lookups")
async def get_workspace_lookups(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    runtime_env = build_runtime_env(services.state, services.cipher)
    mealie_url = resolve_runtime_value(runtime_env, "MEALIE_URL")
    mealie_api_key = resolve_runtime_value(runtime_env, "MEALIE_API_KEY")
    if not mealie_url or not mealie_api_key:
        return {
            "ok": False,
            "reason": "Set Mealie URL and API key in Settings to resolve organizer names.",
            "categories": [],
            "tags": [],
            "tools": [],
        }

    try:
        client = MealieApiClient(base_url=mealie_url, api_key=mealie_api_key)
        categories = _lookup_rows(client.get_organizer_items("categories"))
        tags = _lookup_rows(client.get_organizer_items("tags"))
        tools = _lookup_rows(client.list_tools())
    except requests.RequestException as exc:
        return {
            "ok": False,
            "reason": f"Unable to fetch organizer lookups: {type(exc).__name__}",
            "categories": [],
            "tags": [],
            "tools": [],
        }

    return {
        "ok": True,
        "categories": categories,
        "tags": tags,
        "tools": tools,
    }


@router.get("/config/workspace/draft")
async def get_workspace_draft(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    workspace = TaxonomyWorkspaceDraftService(repo_root=services.settings.config_root, config_files=services.config_files)
    return workspace.get_draft()


@router.put("/config/workspace/draft")
async def put_workspace_draft(
    payload: TaxonomyWorkspaceDraftUpdateRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    workspace = TaxonomyWorkspaceDraftService(repo_root=services.settings.config_root, config_files=services.config_files)
    try:
        return workspace.update_draft(
            expected_version=payload.version,
            draft_patch=payload.draft.model_dump(exclude_none=True),
            replace=payload.replace,
        )
    except WorkspaceVersionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Workspace draft version conflict. expected={exc.expected} actual={exc.actual}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/config/workspace/validate")
async def validate_workspace_draft(
    payload: TaxonomyWorkspaceVersionRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    workspace = TaxonomyWorkspaceDraftService(repo_root=services.settings.config_root, config_files=services.config_files)
    try:
        return workspace.validate_draft(expected_version=payload.version)
    except WorkspaceVersionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Workspace draft version conflict. expected={exc.expected} actual={exc.actual}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/config/workspace/publish")
async def publish_workspace_draft(
    payload: TaxonomyWorkspaceVersionRequest,
    session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    workspace = TaxonomyWorkspaceDraftService(repo_root=services.settings.config_root, config_files=services.config_files)
    try:
        return workspace.publish_draft(
            expected_version=payload.version,
            published_by=str(session.get("username") or ""),
        )
    except WorkspaceVersionConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Workspace draft version conflict. expected={exc.expected} actual={exc.actual}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
