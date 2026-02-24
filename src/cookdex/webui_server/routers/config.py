from __future__ import annotations

import json
from typing import Any

import requests
from fastapi import APIRouter, Depends, HTTPException

from ..deps import Services, build_runtime_env, require_services, require_session, resolve_runtime_value
from ..schemas import ConfigWriteRequest, StarterPackImportRequest, TaxonomySyncRequest
from ..taxonomy_workspace import TaxonomyWorkspaceService

router = APIRouter(tags=["config"])


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
