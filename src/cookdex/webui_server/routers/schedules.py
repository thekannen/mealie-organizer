from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..deps import Services, enforce_safety, require_services, require_session
from ..scheduler import SchedulePayload
from ..schemas import ScheduleCreateRequest, ScheduleUpdateRequest

router = APIRouter(tags=["schedules"])


def _schedule_payload_from_create(request: ScheduleCreateRequest) -> SchedulePayload:
    kind = request.kind
    if kind == "interval":
        seconds = int(request.seconds or 0)
        if seconds <= 0:
            raise HTTPException(status_code=422, detail="Interval schedules require positive 'seconds'.")
        data = {"seconds": seconds}
    else:
        expression = str(request.cron or "").strip()
        if not expression:
            raise HTTPException(status_code=422, detail="Cron schedules require 'cron'.")
        data = {"expression": expression}
    return SchedulePayload(
        name=request.name.strip(),
        task_id=request.task_id.strip(),
        schedule_kind=kind,
        schedule_data=data,
        options=request.options,
        enabled=bool(request.enabled),
    )


def _schedule_payload_from_update(existing: dict[str, Any], request: ScheduleUpdateRequest) -> SchedulePayload:
    kind = request.kind or str(existing["schedule_kind"])
    if kind == "interval":
        existing_seconds = int(dict(existing["schedule_data"]).get("seconds", 0))
        seconds = request.seconds if request.seconds is not None else existing_seconds
        if int(seconds) <= 0:
            raise HTTPException(status_code=422, detail="Interval schedules require positive 'seconds'.")
        data = {"seconds": int(seconds)}
    else:
        existing_cron = str(dict(existing["schedule_data"]).get("expression", ""))
        expression = str(request.cron if request.cron is not None else existing_cron).strip()
        if not expression:
            raise HTTPException(status_code=422, detail="Cron schedules require 'cron'.")
        data = {"expression": expression}
    return SchedulePayload(
        name=(request.name or str(existing["name"])).strip(),
        task_id=(request.task_id or str(existing["task_id"])).strip(),
        schedule_kind=kind,
        schedule_data=data,
        options=request.options if request.options is not None else dict(existing["options"]),
        enabled=bool(request.enabled if request.enabled is not None else existing["enabled"]),
    )


@router.get("/schedules")
async def list_schedules(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    return {"items": services.scheduler.list_schedules()}


@router.post("/schedules", status_code=201)
async def create_schedule(
    payload: ScheduleCreateRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    if payload.task_id.strip() not in services.registry.task_ids:
        raise HTTPException(status_code=404, detail=f"Unknown task '{payload.task_id}'.")
    enforce_safety(services, payload.task_id.strip(), dict(payload.options))
    schedule_payload = _schedule_payload_from_create(payload)
    return services.scheduler.create_schedule(schedule_payload)


@router.patch("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    payload: ScheduleUpdateRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    existing = services.state.get_schedule(schedule_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    schedule_payload = _schedule_payload_from_update(existing, payload)
    if schedule_payload.task_id not in services.registry.task_ids:
        raise HTTPException(status_code=404, detail=f"Unknown task '{schedule_payload.task_id}'.")
    enforce_safety(services, schedule_payload.task_id, dict(schedule_payload.options))
    updated = services.scheduler.update_schedule(schedule_id, schedule_payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Schedule not found.")
    return updated


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, bool]:
    if not services.scheduler.delete_schedule(schedule_id):
        raise HTTPException(status_code=404, detail="Schedule not found.")
    return {"ok": True}
