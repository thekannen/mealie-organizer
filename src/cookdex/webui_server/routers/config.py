from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..deps import Services, require_services, require_session
from ..schemas import ConfigWriteRequest

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
        return services.config_files.write_file(name, payload.content)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown config file.")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
