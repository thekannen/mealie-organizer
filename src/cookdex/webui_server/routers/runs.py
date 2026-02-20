from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse

from ..deps import Services, enforce_safety, require_services, require_session
from ..schemas import PoliciesUpdateRequest, RunCreateRequest

router = APIRouter(tags=["runs"])


@router.get("/tasks")
async def list_tasks(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    tasks = services.registry.describe_tasks()
    policies = services.state.list_task_policies()
    for task in tasks:
        task["policy"] = policies.get(task["task_id"], {"allow_dangerous": False})
    return {"items": tasks}


@router.get("/policies")
async def get_policies(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    return {"policies": services.state.list_task_policies()}


@router.put("/policies")
async def put_policies(
    payload: PoliciesUpdateRequest,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    for task_id, item in payload.policies.items():
        services.state.set_task_policy(task_id.strip(), item.allow_dangerous)
    return {"policies": services.state.list_task_policies()}


@router.post("/runs", status_code=202)
async def create_run(
    payload: RunCreateRequest,
    session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    task_id = payload.task_id.strip()
    if task_id not in services.registry.task_ids:
        raise HTTPException(status_code=404, detail=f"Unknown task '{task_id}'.")
    options = dict(payload.options)
    enforce_safety(services, task_id, options)
    return services.runner.enqueue(task_id=task_id, options=options, triggered_by=str(session["username"]))


@router.get("/runs")
async def list_runs(
    limit: int = 100,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    value = min(max(limit, 1), 500)
    return {"items": services.state.list_runs(limit=value)}


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    run = services.state.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


@router.get("/runs/{run_id}/log")
async def get_run_log(
    run_id: str,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> PlainTextResponse:
    try:
        text = services.runner.read_log(run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Run not found.")
    return PlainTextResponse(text)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    if not services.runner.cancel(run_id):
        raise HTTPException(status_code=409, detail="Run cannot be canceled.")
    run = services.state.get_run(run_id)
    return {"ok": True, "run": run}
