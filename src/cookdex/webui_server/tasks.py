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
    hidden_when: dict[str, Any] | None = None
    choices: list[dict[str, Any]] | None = None
    multi: bool = False


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
    group: str = ""
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
    cmd = _py_module("cookdex.recipe_categorizer")
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
        "cookdex.taxonomy_manager",
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
    return TaskExecution(_py_module("cookdex.audit_taxonomy"), env, dangerous_requested=dangerous)


def _build_cookbook_sync(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run"})
    env, dangerous = _common_env(options)
    return TaskExecution(_py_module("cookdex.cookbook_manager", "sync"), env, dangerous_requested=dangerous)


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
    cmd = _py_module("cookdex.ingredient_parser")
    confidence_pct = _int_option(options, "confidence_threshold")
    max_recipes = _int_option(options, "max_recipes")
    after_slug = _str_option(options, "after_slug", "")
    parsers = _str_option(options, "parsers", "")
    force_parser = _str_option(options, "force_parser", "")
    page_size = _int_option(options, "page_size")
    delay_seconds = _float_option(options, "delay_seconds")
    timeout_seconds = _int_option(options, "timeout_seconds")
    retries = _int_option(options, "retries")
    backoff_seconds = _float_option(options, "backoff_seconds")

    if confidence_pct is not None:
        cmd.extend(["--conf", str(confidence_pct / 100.0)])
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
    _validate_allowed(options, {"dry_run"})
    env, dangerous = _common_env(options)
    dry_run = _bool_option(options, "dry_run", True)
    cmd = _py_module("cookdex.foods_manager", "cleanup")
    if not dry_run:
        cmd.append("--apply")
    return TaskExecution(cmd, env, dangerous_requested=dangerous)


def _build_units_cleanup(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run"})
    env, dangerous = _common_env(options)
    dry_run = _bool_option(options, "dry_run", True)
    cmd = _py_module("cookdex.units_manager", "cleanup")
    if not dry_run:
        cmd.append("--apply")
    return TaskExecution(cmd, env, dangerous_requested=dangerous)


def _build_labels_sync(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run"})
    env, dangerous = _common_env(options)
    dry_run = _bool_option(options, "dry_run", True)
    cmd = _py_module("cookdex.labels_manager")
    if not dry_run:
        cmd.append("--apply")
    return TaskExecution(cmd, env, dangerous_requested=dangerous)


def _build_tools_sync(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run"})
    env, dangerous = _common_env(options)
    dry_run = _bool_option(options, "dry_run", True)
    cmd = _py_module("cookdex.tools_manager")
    if not dry_run:
        cmd.append("--apply")
    return TaskExecution(cmd, env, dangerous_requested=dangerous)


def _build_data_maintenance(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "stages", "continue_on_error", "apply_cleanups", "skip_ai"})
    env, dangerous = _common_env(options)
    cmd = _py_module("cookdex.data_maintenance")
    stages = options.get("stages")
    continue_on_error = _bool_option(options, "continue_on_error", False)
    apply_cleanups = _bool_option(options, "apply_cleanups", False)
    skip_ai = _bool_option(options, "skip_ai", False)
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
    if skip_ai:
        cmd.append("--skip-ai")
    return TaskExecution(cmd, env, dangerous_requested=(dangerous or apply_cleanups))


def _build_rule_tag(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "use_db", "config_file"})
    env, dangerous = _common_env(options)
    dry_run = _bool_option(options, "dry_run", True)
    use_db = _bool_option(options, "use_db", False)
    config_file = _str_option(options, "config_file", "")
    cmd = _py_module("cookdex.rule_tagger")
    if not dry_run:
        cmd.append("--apply")
    if use_db:
        cmd.append("--use-db")
    if config_file:
        cmd.extend(["--config", config_file])
    return TaskExecution(cmd, env, dangerous_requested=dangerous)


def _build_recipe_quality(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "nutrition_sample", "use_db"})
    env, dangerous = _common_env(options)
    nutrition_sample = _int_option(options, "nutrition_sample")
    use_db = _bool_option(options, "use_db", False)
    cmd = _py_module("cookdex.recipe_quality_audit")
    if nutrition_sample is not None:
        cmd.extend(["--nutrition-sample", str(nutrition_sample)])
    if use_db:
        cmd.append("--use-db")
    return TaskExecution(cmd, env, dangerous_requested=dangerous)


def _build_yield_normalize(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "use_db"})
    env, dangerous = _common_env(options)
    dry_run = _bool_option(options, "dry_run", True)
    use_db = _bool_option(options, "use_db", False)
    cmd = _py_module("cookdex.yield_normalizer")
    if not dry_run:
        cmd.append("--apply")
    if use_db:
        cmd.append("--use-db")
    return TaskExecution(cmd, env, dangerous_requested=dangerous)


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
                group="AI & Tagging",
                description="Use AI to classify recipes into categories, tags, and tools.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                    OptionSpec("provider", "AI Provider", "string"),
                ],
                build=_build_categorize,
            )
        )
        self._register(
            TaskDefinition(
                task_id="taxonomy-refresh",
                title="Refresh Taxonomy",
                group="Taxonomy",
                description="Sync categories and tags from taxonomy source files.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                    OptionSpec(
                        "mode",
                        "Refresh Mode",
                        "string",
                        default="merge",
                        help_text="Merge keeps existing entries and adds new ones. Replace overwrites to match source files exactly.",
                        choices=[
                            {"value": "merge", "label": "Merge (keep existing)"},
                            {"value": "replace", "label": "Replace (match source exactly)"},
                        ],
                    ),
                    OptionSpec(
                        "cleanup_apply",
                        "Delete Unused Entries",
                        "boolean",
                        default=False,
                        dangerous=True,
                        help_text="Permanently delete categories/tags not referenced by any recipe.",
                        hidden_when={"key": "dry_run", "value": True},
                    ),
                ],
                build=_build_taxonomy_refresh,
            )
        )
        self._register(
            TaskDefinition(
                task_id="taxonomy-audit",
                title="Taxonomy Audit",
                group="Analysis",
                description="Scan taxonomy for unused entries, duplicate names, and recipes missing categories or tags.",
                options=[],
                build=_build_taxonomy_audit,
            )
        )
        self._register(
            TaskDefinition(
                task_id="cookbook-sync",
                title="Cookbook Sync",
                group="Content Sync",
                description="Create and update cookbooks to match your cookbook configuration.",
                options=[OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything.")],
                build=_build_cookbook_sync,
            )
        )
        self._register(
            TaskDefinition(
                task_id="ingredient-parse",
                title="Ingredient Parser",
                group="Parsing",
                description="Run NLP parsing on recipe ingredients to extract food, unit, and quantity from raw text. When confidence is below the threshold, parsing falls back to an AI processor.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                    OptionSpec(
                        "confidence_threshold",
                        "Confidence Threshold",
                        "integer",
                        default=75,
                        help_text="Minimum confidence % (0–100) to accept an NLP parse result. Results below this threshold fall back to AI parsing.",
                    ),
                ],
                build=_build_ingredient_parse,
            )
        )
        self._register(
            TaskDefinition(
                task_id="foods-cleanup",
                title="Foods Cleanup",
                group="Cleanup",
                description="Find and merge duplicate food entries — e.g. 'garlic' and 'Garlic Clove' pointing to the same ingredient.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                ],
                build=_build_foods_cleanup,
            )
        )
        self._register(
            TaskDefinition(
                task_id="units-cleanup",
                title="Units Cleanup",
                group="Cleanup",
                description="Find and merge duplicate units — e.g. 'tsp', 'teaspoon', and 'Teaspoon' collapsed into one canonical entry.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                ],
                build=_build_units_cleanup,
            )
        )
        self._register(
            TaskDefinition(
                task_id="labels-sync",
                title="Labels Sync",
                group="Content Sync",
                description="Sync labels from your taxonomy config — creates missing labels and removes unlisted ones.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                ],
                build=_build_labels_sync,
            )
        )
        self._register(
            TaskDefinition(
                task_id="tools-sync",
                title="Tools Sync",
                group="Content Sync",
                description="Sync cooking tools from your taxonomy config — creates new tools and merges duplicates.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                ],
                build=_build_tools_sync,
            )
        )
        self._register(
            TaskDefinition(
                task_id="data-maintenance",
                title="Data Maintenance Pipeline",
                group="Pipeline",
                description="Run all maintenance stages in order: Ingredient Parse → Foods Cleanup → Units Cleanup → Labels Sync → Tools Sync → Taxonomy Refresh → Categorize → Cookbook Sync → Yield Normalize → Quality Audit → Taxonomy Audit. Select specific stages to run a subset.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                    OptionSpec(
                        "stages",
                        "Stages",
                        "string",
                        help_text="Select stages to run. Leave all unselected to run the full pipeline.",
                        multi=True,
                        choices=[
                            {"value": "parse", "label": "Ingredient Parse"},
                            {"value": "foods", "label": "Foods Cleanup"},
                            {"value": "units", "label": "Units Cleanup"},
                            {"value": "labels", "label": "Labels Sync"},
                            {"value": "tools", "label": "Tools Sync"},
                            {"value": "taxonomy", "label": "Taxonomy Refresh"},
                            {"value": "categorize", "label": "Categorize"},
                            {"value": "cookbooks", "label": "Cookbook Sync"},
                            {"value": "yield", "label": "Yield Normalize"},
                            {"value": "quality", "label": "Quality Audit"},
                            {"value": "audit", "label": "Taxonomy Audit"},
                        ],
                    ),
                    OptionSpec(
                        "skip_ai",
                        "Skip AI Stage",
                        "boolean",
                        default=False,
                        help_text="Skip AI categorization even if a provider is configured.",
                    ),
                    OptionSpec(
                        "continue_on_error",
                        "Continue on Error",
                        "boolean",
                        default=False,
                        help_text="Keep running remaining stages if one fails.",
                    ),
                    OptionSpec(
                        "apply_cleanups",
                        "Apply Cleanup Writes",
                        "boolean",
                        default=False,
                        dangerous=True,
                        help_text="Write deduplication and cleanup results. Only takes effect for cleanup stages.",
                        hidden_when={"key": "dry_run", "value": True},
                    ),
                ],
                build=_build_data_maintenance,
            )
        )
        self._register(
            TaskDefinition(
                task_id="rule-tag",
                title="Rule-Based Tagger",
                group="AI & Tagging",
                description="Apply tag and tool rules to recipes using regex patterns — no AI required.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                    OptionSpec(
                        "use_db",
                        "Use Direct DB",
                        "boolean",
                        default=False,
                        help_text="Match ingredients and tools via direct DB queries.",
                    ),
                ],
                build=_build_rule_tag,
            )
        )
        self._register(
            TaskDefinition(
                task_id="recipe-quality",
                title="Recipe Quality Audit",
                group="Analysis",
                description="Score all recipes on completeness — categories, tags, tools, description, cook time, yield, and nutrition coverage.",
                options=[
                    OptionSpec(
                        "use_db",
                        "Use Direct DB",
                        "boolean",
                        default=False,
                        help_text="Fetch all recipe data in one query — faster and gives exact nutrition coverage.",
                    ),
                    OptionSpec(
                        "nutrition_sample",
                        "Nutrition Sample Size",
                        "integer",
                        default=200,
                        help_text="Number of recipes to sample for nutrition coverage estimate.",
                        hidden_when={"key": "use_db", "value": True},
                    ),
                ],
                build=_build_recipe_quality,
            )
        )
        self._register(
            TaskDefinition(
                task_id="yield-normalize",
                title="Yield Normalizer",
                group="Cleanup",
                description="Fill missing yield text from servings count, or parse yield text to set numeric servings.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                    OptionSpec(
                        "use_db",
                        "Use Direct DB",
                        "boolean",
                        default=False,
                        help_text="Write changes in a single DB transaction instead of per-recipe API calls — faster.",
                    ),
                ],
                build=_build_yield_normalize,
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
                    "group": task.group,
                    "options": [
                        {
                            "key": option.key,
                            "label": option.label,
                            "type": option.value_type,
                            "default": option.default,
                            "required": option.required,
                            "dangerous": option.dangerous,
                            "help_text": option.help_text,
                            "hidden_when": option.hidden_when,
                            "choices": option.choices,
                            "multi": option.multi,
                        }
                        for option in task.options
                    ],
                }
            )
        return payload
