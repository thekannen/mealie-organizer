from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class OptionSpec:
    key: str
    label: str
    value_type: str
    default: Any = None
    required: bool = False
    dangerous: bool = False
    help_text: str = ""


@dataclass(frozen=True)
class TaskExecution:
    command: list[str]
    env: dict[str, str]
    dangerous_requested: bool


BuildFn = Callable[[dict[str, Any]], TaskExecution]


@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    title: str
    description: str
    options: list[OptionSpec] = field(default_factory=list)
    build: BuildFn | None = None


def _py_module(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


def _bool_option(options: dict[str, Any], key: str, default: bool) -> bool:
    raw = options.get(key, default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        text = raw.strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"Option '{key}' must be boolean.")


def _str_option(options: dict[str, Any], key: str, default: str = "") -> str:
    raw = options.get(key, default)
    if raw is None:
        return default
    text = str(raw).strip()
    return text


def _int_option(options: dict[str, Any], key: str, default: int | None = None) -> int | None:
    if key not in options:
        return default
    raw = options.get(key)
    if raw is None or raw == "":
        return default
    return int(raw)


def _float_option(options: dict[str, Any], key: str, default: float | None = None) -> float | None:
    if key not in options:
        return default
    raw = options.get(key)
    if raw is None or raw == "":
        return default
    return float(raw)


def _common_env(options: dict[str, Any]) -> tuple[dict[str, str], bool]:
    dry_run = _bool_option(options, "dry_run", True)
    return {"DRY_RUN": "true" if dry_run else "false"}, (not dry_run)


def _validate_allowed(options: dict[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(options) - allowed)
    if unknown:
        raise ValueError(f"Unsupported options: {', '.join(unknown)}")


def _build_categorize(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "provider"})
    env, dangerous = _common_env(options)
    provider = _str_option(options, "provider", "")
    cmd = _py_module("mealie_organizer.recipe_categorizer")
    if provider:
        cmd.extend(["--provider", provider])
    return TaskExecution(cmd, env, dangerous_requested=dangerous)


def _build_taxonomy_refresh(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(
        options,
        {"dry_run", "mode", "cleanup", "cleanup_apply", "cleanup_only_unused", "cleanup_delete_noisy"},
    )
    env, dangerous = _common_env(options)
    mode = _str_option(options, "mode", "merge") or "merge"
    cleanup = _bool_option(options, "cleanup", True)
    cleanup_apply = _bool_option(options, "cleanup_apply", False)
    cleanup_only_unused = _bool_option(options, "cleanup_only_unused", True)
    cleanup_delete_noisy = _bool_option(options, "cleanup_delete_noisy", True)

    cmd = _py_module(
        "mealie_organizer.taxonomy_manager",
        "refresh",
        "--mode",
        mode,
        "--categories-file",
        "configs/taxonomy/categories.json",
        "--tags-file",
        "configs/taxonomy/tags.json",
    )
    if cleanup:
        cmd.append("--cleanup")
    if cleanup_only_unused:
        cmd.append("--cleanup-only-unused")
    if cleanup_delete_noisy:
        cmd.append("--cleanup-delete-noisy")
    if cleanup_apply:
        cmd.append("--cleanup-apply")
    return TaskExecution(cmd, env, dangerous_requested=(dangerous or cleanup_apply))


def _build_taxonomy_audit(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run"})
    env, dangerous = _common_env(options)
    return TaskExecution(_py_module("mealie_organizer.audit_taxonomy"), env, dangerous_requested=dangerous)


def _build_cookbook_sync(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run"})
    env, dangerous = _common_env(options)
    return TaskExecution(_py_module("mealie_organizer.cookbook_manager", "sync"), env, dangerous_requested=dangerous)


def _build_ingredient_parse(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(
        options,
        {
            "dry_run",
            "confidence_threshold",
            "max_recipes",
            "after_slug",
            "parsers",
            "force_parser",
            "page_size",
            "delay_seconds",
            "timeout_seconds",
            "retries",
            "backoff_seconds",
        },
    )
    env, dangerous = _common_env(options)
    cmd = _py_module("mealie_organizer.ingredient_parser")
    confidence = _float_option(options, "confidence_threshold")
    max_recipes = _int_option(options, "max_recipes")
    after_slug = _str_option(options, "after_slug", "")
    parsers = _str_option(options, "parsers", "")
    force_parser = _str_option(options, "force_parser", "")
    page_size = _int_option(options, "page_size")
    delay_seconds = _float_option(options, "delay_seconds")
    timeout_seconds = _int_option(options, "timeout_seconds")
    retries = _int_option(options, "retries")
    backoff_seconds = _float_option(options, "backoff_seconds")

    if confidence is not None:
        cmd.extend(["--conf", str(confidence)])
    if max_recipes is not None:
        cmd.extend(["--max", str(max_recipes)])
    if after_slug:
        cmd.extend(["--after-slug", after_slug])
    if parsers:
        cmd.extend(["--parsers", parsers])
    if force_parser:
        cmd.extend(["--force-parser", force_parser])
    if page_size is not None:
        cmd.extend(["--page-size", str(page_size)])
    if delay_seconds is not None:
        cmd.extend(["--delay", str(delay_seconds)])
    if timeout_seconds is not None:
        cmd.extend(["--timeout", str(timeout_seconds)])
    if retries is not None:
        cmd.extend(["--retries", str(retries)])
    if backoff_seconds is not None:
        cmd.extend(["--backoff", str(backoff_seconds)])

    return TaskExecution(cmd, env, dangerous_requested=dangerous)


def _build_foods_cleanup(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "apply"})
    env, dangerous = _common_env(options)
    apply = _bool_option(options, "apply", False)
    cmd = _py_module("mealie_organizer.foods_manager", "cleanup")
    if apply:
        cmd.append("--apply")
    return TaskExecution(cmd, env, dangerous_requested=(dangerous or apply))


def _build_units_cleanup(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "apply"})
    env, dangerous = _common_env(options)
    apply = _bool_option(options, "apply", False)
    cmd = _py_module("mealie_organizer.units_manager", "cleanup")
    if apply:
        cmd.append("--apply")
    return TaskExecution(cmd, env, dangerous_requested=(dangerous or apply))


def _build_labels_sync(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "apply"})
    env, dangerous = _common_env(options)
    apply = _bool_option(options, "apply", False)
    cmd = _py_module("mealie_organizer.labels_manager")
    if apply:
        cmd.append("--apply")
    return TaskExecution(cmd, env, dangerous_requested=(dangerous or apply))


def _build_tools_sync(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "apply"})
    env, dangerous = _common_env(options)
    apply = _bool_option(options, "apply", False)
    cmd = _py_module("mealie_organizer.tools_manager")
    if apply:
        cmd.append("--apply")
    return TaskExecution(cmd, env, dangerous_requested=(dangerous or apply))


def _build_data_maintenance(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "stages", "continue_on_error", "apply_cleanups"})
    env, dangerous = _common_env(options)
    cmd = _py_module("mealie_organizer.data_maintenance")
    stages = options.get("stages")
    continue_on_error = _bool_option(options, "continue_on_error", False)
    apply_cleanups = _bool_option(options, "apply_cleanups", False)
    if stages:
        if isinstance(stages, list):
            stage_value = ",".join(str(item).strip() for item in stages if str(item).strip())
        else:
            stage_value = str(stages).strip()
        if stage_value:
            cmd.extend(["--stages", stage_value])
    if continue_on_error:
        cmd.append("--continue-on-error")
    if apply_cleanups:
        cmd.append("--apply-cleanups")
    return TaskExecution(cmd, env, dangerous_requested=(dangerous or apply_cleanups))


class TaskRegistry:
    def __init__(self) -> None:
        self._tasks: dict[str, TaskDefinition] = {}
        self._register_defaults()

    @property
    def task_ids(self) -> list[str]:
        return sorted(self._tasks.keys())

    def _register(self, definition: TaskDefinition) -> None:
        self._tasks[definition.task_id] = definition

    def _register_defaults(self) -> None:
        self._register(
            TaskDefinition(
                task_id="categorize",
                title="Categorize Recipes",
                description="Classify recipes into categories/tags/tools using the configured provider.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True),
                    OptionSpec("provider", "Provider Override", "string"),
                ],
                build=_build_categorize,
            )
        )
        self._register(
            TaskDefinition(
                task_id="taxonomy-refresh",
                title="Refresh Taxonomy",
                description="Sync categories and tags from taxonomy source files.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True),
                    OptionSpec("mode", "Refresh Mode", "string", default="merge"),
                    OptionSpec("cleanup_apply", "Apply Cleanup Deletes", "boolean", default=False, dangerous=True),
                ],
                build=_build_taxonomy_refresh,
            )
        )
        self._register(
            TaskDefinition(
                task_id="taxonomy-audit",
                title="Taxonomy Audit",
                description="Generate taxonomy diagnostics report.",
                options=[OptionSpec("dry_run", "Dry Run", "boolean", default=True)],
                build=_build_taxonomy_audit,
            )
        )
        self._register(
            TaskDefinition(
                task_id="cookbook-sync",
                title="Cookbook Sync",
                description="Create/update cookbooks based on config rules.",
                options=[OptionSpec("dry_run", "Dry Run", "boolean", default=True)],
                build=_build_cookbook_sync,
            )
        )
        self._register(
            TaskDefinition(
                task_id="ingredient-parse",
                title="Ingredient Parser",
                description="Parse ingredients with configured parser fallback.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True),
                    OptionSpec("confidence_threshold", "Confidence", "number"),
                    OptionSpec("max_recipes", "Max Recipes", "integer"),
                    OptionSpec("after_slug", "After Slug", "string"),
                    OptionSpec("parsers", "Parsers", "string"),
                    OptionSpec("force_parser", "Force Parser", "string"),
                ],
                build=_build_ingredient_parse,
            )
        )
        self._register(
            TaskDefinition(
                task_id="foods-cleanup",
                title="Foods Cleanup",
                description="Merge duplicate food entries and cleanup noise.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True),
                    OptionSpec("apply", "Apply Merge Actions", "boolean", default=False, dangerous=True),
                ],
                build=_build_foods_cleanup,
            )
        )
        self._register(
            TaskDefinition(
                task_id="units-cleanup",
                title="Units Cleanup",
                description="Normalize unit aliases and merge duplicate units.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True),
                    OptionSpec("apply", "Apply Merge Actions", "boolean", default=False, dangerous=True),
                ],
                build=_build_units_cleanup,
            )
        )
        self._register(
            TaskDefinition(
                task_id="labels-sync",
                title="Labels Sync",
                description="Create/delete labels from taxonomy config.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True),
                    OptionSpec("apply", "Apply Changes", "boolean", default=False, dangerous=True),
                ],
                build=_build_labels_sync,
            )
        )
        self._register(
            TaskDefinition(
                task_id="tools-sync",
                title="Tools Sync",
                description="Create/merge tools from taxonomy config.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True),
                    OptionSpec("apply", "Apply Changes", "boolean", default=False, dangerous=True),
                ],
                build=_build_tools_sync,
            )
        )
        self._register(
            TaskDefinition(
                task_id="data-maintenance",
                title="Data Maintenance Pipeline",
                description="Run staged maintenance pipeline with optional write cleanups.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True),
                    OptionSpec("stages", "Stages", "string"),
                    OptionSpec("continue_on_error", "Continue on Error", "boolean", default=False),
                    OptionSpec("apply_cleanups", "Apply Cleanup Writes", "boolean", default=False, dangerous=True),
                ],
                build=_build_data_maintenance,
            )
        )

    def build_execution(self, task_id: str, options: dict[str, Any] | None = None) -> TaskExecution:
        definition = self._tasks.get(task_id)
        if definition is None or definition.build is None:
            raise KeyError(f"Unknown task '{task_id}'.")
        payload = options or {}
        if not isinstance(payload, dict):
            raise ValueError("Task options must be a JSON object.")
        return definition.build(payload)

    def describe_tasks(self) -> list[dict[str, Any]]:
        payload: list[dict[str, Any]] = []
        for task_id in sorted(self._tasks):
            task = self._tasks[task_id]
            payload.append(
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "description": task.description,
                    "options": [
                        {
                            "key": option.key,
                            "label": option.label,
                            "type": option.value_type,
                            "default": option.default,
                            "required": option.required,
                            "dangerous": option.dangerous,
                            "help_text": option.help_text,
                        }
                        for option in task.options
                    ],
                }
            )
        return payload
