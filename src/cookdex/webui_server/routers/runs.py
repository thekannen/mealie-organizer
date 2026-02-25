from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse

from ..deps import Services, build_runtime_env, enforce_safety, require_services, require_session
from ..rate_limit import ActionRateLimiter
from ..schemas import PoliciesUpdateRequest, RunCreateRequest

router = APIRouter(tags=["runs"])
_action_limiter = ActionRateLimiter(max_per_minute=30)


@router.get("/tasks")
async def list_tasks(
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    tasks = services.registry.describe_tasks()
    policies = services.state.list_task_policies()
    runtime_env = build_runtime_env(services.state, services.cipher)
    db_configured = bool(runtime_env.get("MEALIE_DB_TYPE", "").strip())
    has_openai = bool(runtime_env.get("OPENAI_API_KEY", "").strip())
    has_ollama = bool(runtime_env.get("OLLAMA_URL", "").strip())
    for task in tasks:
        task["policy"] = policies.get(task["task_id"], {"allow_dangerous": False})
        for option in task.get("options", []):
            if db_configured and option["key"] == "use_db":
                option["default"] = True
            if task["task_id"] in {"tag-categorize", "data-maintenance"} and option["key"] == "provider":
                provider_choices = []
                if has_openai:
                    provider_choices.append({"value": "chatgpt", "label": "ChatGPT (OpenAI)"})
                if has_ollama:
                    provider_choices.append({"value": "ollama", "label": "Ollama (Local)"})
                if not provider_choices:
                    option["hidden"] = True
                else:
                    option["choices"] = [
                        {"value": "", "label": "Default"},
                        *provider_choices,
                    ]
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
    _action_limiter.check(session["username"])
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


@router.get("/runs/{run_id}/log/tail")
async def get_run_log_tail(
    run_id: str,
    offset: int = Query(default=0, ge=0),
    _session: dict[str, Any] = Depends(require_session),
    services: Services = Depends(require_services),
) -> dict[str, Any]:
    """Return log bytes from `offset` onwards, plus the current total file size."""
    record = services.state.get_run(run_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    log_path = record.get("log_path")
    if not log_path:
        return {"content": "", "size": 0}
    path = Path(str(log_path))
    if not path.exists():
        return {"content": "", "size": 0}
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            total = fh.tell()
            fh.seek(min(offset, total))
            chunk = fh.read(200_000)
        return {"content": chunk.decode("utf-8", errors="replace"), "size": total}
    except OSError:
        return {"content": "", "size": 0}


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
