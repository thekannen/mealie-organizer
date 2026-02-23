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
    hidden_when: dict[str, Any] | list[dict[str, Any]] | None = None
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


# ---------------------------------------------------------------------------
# Build functions
# ---------------------------------------------------------------------------

def _build_tag_categorize(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "method", "provider", "use_db", "config_file"})
    env, dangerous = _common_env(options)
    method = _str_option(options, "method", "ai") or "ai"

    if method == "rules":
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
    else:
        provider = _str_option(options, "provider", "")
        cmd = _py_module("cookdex.recipe_categorizer")
        if provider:
            cmd.extend(["--provider", provider])

    return TaskExecution(cmd, env, dangerous_requested=dangerous)


def _build_taxonomy_refresh(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(
        options,
        {
            "dry_run",
            "mode",
            "cleanup",
            "cleanup_apply",
            "cleanup_only_unused",
            "cleanup_delete_noisy",
            "sync_labels",
            "sync_tools",
        },
    )
    env, dangerous = _common_env(options)
    sync_labels = _bool_option(options, "sync_labels", True)
    sync_tools = _bool_option(options, "sync_tools", True)
    cleanup_apply = _bool_option(options, "cleanup_apply", False)

    if sync_labels or sync_tools:
        # Route through data_maintenance so all selected stages run in sequence
        stages = ["taxonomy"]
        if sync_labels:
            stages.append("labels")
        if sync_tools:
            stages.append("tools")
        cmd = _py_module("cookdex.data_maintenance", "--stages", ",".join(stages))
        if cleanup_apply:
            cmd.append("--apply-cleanups")
        return TaskExecution(cmd, env, dangerous_requested=(dangerous or cleanup_apply))

    # Direct taxonomy_manager call (categories + tags only) with full cleanup control
    mode = _str_option(options, "mode", "merge") or "merge"
    cleanup = _bool_option(options, "cleanup", True)
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


def _build_health_check(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"scope_quality", "scope_taxonomy", "use_db", "nutrition_sample"})
    env = {"DRY_RUN": "true"}
    dangerous = False
    scope_quality = _bool_option(options, "scope_quality", True)
    scope_taxonomy = _bool_option(options, "scope_taxonomy", True)
    use_db = _bool_option(options, "use_db", False)
    nutrition_sample = _int_option(options, "nutrition_sample")

    if scope_quality and scope_taxonomy:
        cmd = _py_module("cookdex.data_maintenance", "--stages", "quality,audit")
        if use_db:
            cmd.append("--use-db")
        if nutrition_sample is not None:
            cmd.extend(["--nutrition-sample", str(nutrition_sample)])
        return TaskExecution(cmd, env, dangerous_requested=dangerous)

    if scope_quality:
        cmd = _py_module("cookdex.recipe_quality_audit")
        if nutrition_sample is not None:
            cmd.extend(["--nutrition-sample", str(nutrition_sample)])
        if use_db:
            cmd.append("--use-db")
        return TaskExecution(cmd, env, dangerous_requested=dangerous)

    if scope_taxonomy:
        return TaskExecution(_py_module("cookdex.audit_taxonomy"), env, dangerous_requested=dangerous)

    raise ValueError("At least one audit scope must be selected.")


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


def _build_cleanup_duplicates(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "target"})
    env, dangerous = _common_env(options)
    dry_run = _bool_option(options, "dry_run", True)
    target = _str_option(options, "target", "both") or "both"

    if target == "both":
        cmd = _py_module("cookdex.data_maintenance", "--stages", "foods,units")
        if not dry_run:
            cmd.append("--apply-cleanups")
        return TaskExecution(cmd, env, dangerous_requested=dangerous)

    if target == "foods":
        cmd = _py_module("cookdex.foods_manager", "cleanup")
        if not dry_run:
            cmd.append("--apply")
    else:
        cmd = _py_module("cookdex.units_manager", "cleanup")
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


def _build_clean_recipes(options: dict[str, Any]) -> TaskExecution:
    _validate_allowed(options, {"dry_run", "run_dedup", "run_junk", "run_names", "reason", "force_all"})
    env, dangerous = _common_env(options)
    dry_run = _bool_option(options, "dry_run", True)
    run_dedup = _bool_option(options, "run_dedup", True)
    run_junk = _bool_option(options, "run_junk", True)
    run_names = _bool_option(options, "run_names", True)

    if not any([run_dedup, run_junk, run_names]):
        raise ValueError("At least one operation must be selected.")

    # Single operation: call the module directly to preserve per-task options
    if run_dedup and not run_junk and not run_names:
        cmd = _py_module("cookdex.recipe_deduplicator")
        if not dry_run:
            cmd.append("--apply")
        return TaskExecution(cmd, env, dangerous_requested=dangerous)

    if run_junk and not run_dedup and not run_names:
        reason = _str_option(options, "reason", "")
        cmd = _py_module("cookdex.recipe_junk_filter")
        if not dry_run:
            cmd.append("--apply")
        if reason:
            cmd.extend(["--reason", reason])
        return TaskExecution(cmd, env, dangerous_requested=dangerous)

    if run_names and not run_dedup and not run_junk:
        force_all = _bool_option(options, "force_all", False)
        cmd = _py_module("cookdex.recipe_name_normalizer")
        if not dry_run:
            cmd.append("--apply")
        if force_all:
            cmd.append("--all")
        return TaskExecution(cmd, env, dangerous_requested=dangerous)

    # Multiple operations: route through data_maintenance
    stage_map = [
        (run_dedup, "dedup"),
        (run_junk, "junk"),
        (run_names, "names"),
    ]
    stages = ",".join(s for flag, s in stage_map if flag)
    cmd = _py_module("cookdex.data_maintenance", "--stages", stages)
    if not dry_run:
        cmd.append("--apply-cleanups")
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


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

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
        # ── Data Pipeline ────────────────────────────────────────────────
        self._register(
            TaskDefinition(
                task_id="data-maintenance",
                title="Data Maintenance Pipeline",
                group="Data Pipeline",
                description="Run all maintenance stages in order: Dedup → Junk Filter → Name Normalize → Ingredient Parse → Foods Cleanup → Units Cleanup → Labels Sync → Tools Sync → Taxonomy Refresh → Categorize → Cookbook Sync → Yield Normalize → Quality Audit → Taxonomy Audit. Select specific stages to run a subset.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                    OptionSpec(
                        "stages",
                        "Stages",
                        "string",
                        help_text="Select stages to run. Leave all unselected to run the full pipeline.",
                        multi=True,
                        choices=[
                            {"value": "dedup", "label": "Recipe Dedup"},
                            {"value": "junk", "label": "Junk Filter"},
                            {"value": "names", "label": "Name Normalize"},
                            {"value": "parse", "label": "Ingredient Parse"},
                            {"value": "foods", "label": "Foods Cleanup"},
                            {"value": "units", "label": "Units Cleanup"},
                            {"value": "labels", "label": "Labels Sync"},
                            {"value": "tools", "label": "Tools Sync"},
                            {"value": "taxonomy", "label": "Taxonomy Refresh"},
                            {"value": "categorize", "label": "Categorize (AI)"},
                            {"value": "rule-tag", "label": "Rule-Based Tag"},
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

        # ── Actions ──────────────────────────────────────────────────────
        self._register(
            TaskDefinition(
                task_id="clean-recipes",
                title="Clean Recipe Library",
                group="Actions",
                description="Remove duplicates, filter out junk content, and normalize messy import names — select which operations to run.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                    OptionSpec(
                        "run_dedup",
                        "Remove Duplicates",
                        "boolean",
                        default=True,
                        help_text="Find recipes with the same source URL and delete the copies, keeping the best version.",
                    ),
                    OptionSpec(
                        "run_junk",
                        "Filter Junk",
                        "boolean",
                        default=True,
                        help_text="Detect and remove non-recipe content: listicles, how-to articles, digest posts, and placeholder instructions.",
                    ),
                    OptionSpec(
                        "run_names",
                        "Normalize Names",
                        "boolean",
                        default=True,
                        help_text="Clean up recipe names derived from URL slugs — turns 'how-to-make-chicken-pasta-recipe' into 'Chicken Pasta'.",
                    ),
                    OptionSpec(
                        "reason",
                        "Junk Filter Category",
                        "string",
                        help_text="Only scan for a specific junk category. Leave blank to check all.",
                        hidden_when={"key": "run_junk", "value": False},
                        choices=[
                            {"value": "", "label": "All categories"},
                            {"value": "how_to", "label": "How-to articles"},
                            {"value": "listicle", "label": "Listicles / roundups"},
                            {"value": "digest", "label": "Digest / weekly posts"},
                            {"value": "keyword", "label": "High-risk keywords"},
                            {"value": "utility", "label": "Utility pages"},
                            {"value": "bad_instructions", "label": "Placeholder instructions"},
                        ],
                    ),
                    OptionSpec(
                        "force_all",
                        "Normalize All Names",
                        "boolean",
                        default=False,
                        help_text="Apply name normalization to all recipes, not just lowercase/unformatted names.",
                        hidden_when={"key": "run_names", "value": False},
                    ),
                ],
                build=_build_clean_recipes,
            )
        )
        self._register(
            TaskDefinition(
                task_id="ingredient-parse",
                title="Ingredient Parser",
                group="Actions",
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
                task_id="yield-normalize",
                title="Yield Normalizer",
                group="Actions",
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
        self._register(
            TaskDefinition(
                task_id="cleanup-duplicates",
                title="Clean Up Duplicates",
                group="Actions",
                description="Find and merge duplicate food or unit entries — e.g. 'garlic' and 'Garlic Clove', or 'tsp' / 'teaspoon' / 'Teaspoon'.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                    OptionSpec(
                        "target",
                        "Target",
                        "string",
                        default="both",
                        help_text="Which lookup table to deduplicate.",
                        choices=[
                            {"value": "both", "label": "Foods & Units"},
                            {"value": "foods", "label": "Foods only"},
                            {"value": "units", "label": "Units only"},
                        ],
                    ),
                ],
                build=_build_cleanup_duplicates,
            )
        )

        # ── Organizers ───────────────────────────────────────────────────
        self._register(
            TaskDefinition(
                task_id="tag-categorize",
                title="Tag & Categorize Recipes",
                group="Organizers",
                description="Assign categories, tags, and tools to recipes. Use AI for rich semantic classification, or rule-based for fast, deterministic results with no API cost.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                    OptionSpec(
                        "method",
                        "Method",
                        "string",
                        default="ai",
                        help_text="AI uses your configured provider to classify recipes. Rule-Based applies regex patterns from your tag_rules.json config.",
                        choices=[
                            {"value": "ai", "label": "AI"},
                            {"value": "rules", "label": "Rule-Based"},
                        ],
                    ),
                    OptionSpec(
                        "provider",
                        "AI Provider",
                        "string",
                        help_text="Override the AI provider. Leave blank to use the configured default.",
                        hidden_when={"key": "method", "value": "rules"},
                    ),
                    OptionSpec(
                        "use_db",
                        "Use Direct DB",
                        "boolean",
                        default=False,
                        help_text="Match ingredients via direct DB queries instead of the API — faster and works offline.",
                        hidden_when={"key": "method", "value": "ai"},
                    ),
                ],
                build=_build_tag_categorize,
            )
        )
        self._register(
            TaskDefinition(
                task_id="taxonomy-refresh",
                title="Refresh Taxonomy",
                group="Organizers",
                description="Sync categories, tags, labels, and tools from your taxonomy config files into Mealie.",
                options=[
                    OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything."),
                    OptionSpec(
                        "sync_labels",
                        "Sync Labels",
                        "boolean",
                        default=True,
                        help_text="Create missing labels and remove unlisted ones.",
                    ),
                    OptionSpec(
                        "sync_tools",
                        "Sync Tools",
                        "boolean",
                        default=True,
                        help_text="Create new tools and merge duplicates from your taxonomy config.",
                    ),
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
                task_id="cookbook-sync",
                title="Cookbook Sync",
                group="Organizers",
                description="Create and update cookbooks to match your cookbook configuration.",
                options=[OptionSpec("dry_run", "Dry Run", "boolean", default=True, help_text="Preview changes without writing anything.")],
                build=_build_cookbook_sync,
            )
        )

        # ── Audits ───────────────────────────────────────────────────────
        self._register(
            TaskDefinition(
                task_id="health-check",
                title="Health Check",
                group="Audits",
                description="Run diagnostic audits on your recipe library and taxonomy — surface missing metadata, unused entries, and duplicates.",
                options=[
                    OptionSpec(
                        "scope_quality",
                        "Recipe Quality",
                        "boolean",
                        default=True,
                        help_text="Score all recipes on completeness: categories, tags, tools, description, cook time, yield, and nutrition.",
                    ),
                    OptionSpec(
                        "scope_taxonomy",
                        "Taxonomy",
                        "boolean",
                        default=True,
                        help_text="Scan taxonomy for unused entries, duplicate names, and recipes missing categories or tags.",
                    ),
                    OptionSpec(
                        "use_db",
                        "Use Direct DB",
                        "boolean",
                        default=False,
                        help_text="Fetch all recipe data in one query — faster and gives exact nutrition coverage.",
                        hidden_when={"key": "scope_quality", "value": False},
                    ),
                    OptionSpec(
                        "nutrition_sample",
                        "Nutrition Sample Size",
                        "integer",
                        default=200,
                        help_text="Number of recipes to sample for nutrition coverage estimate (API mode only).",
                        hidden_when=[
                            {"key": "scope_quality", "value": False},
                            {"key": "use_db", "value": True},
                        ],
                    ),
                ],
                build=_build_health_check,
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
