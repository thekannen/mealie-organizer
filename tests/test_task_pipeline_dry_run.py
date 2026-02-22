"""Task testing pipeline.

Iterates over every registered task in dry-run mode and verifies each one:
- builds a valid TaskExecution (no import or logic errors)
- sets DRY_RUN=true in the subprocess environment
- does not flag dangerous_requested
- produces a well-formed Python subprocess command
- wires option values correctly into command flags

No live Mealie connection is needed; these are all build-time assertions.
"""
from __future__ import annotations

import sys

import pytest

from cookdex.webui_server.tasks import TaskRegistry

REGISTRY = TaskRegistry()

ALL_TASK_IDS = [
    "categorize",
    "cookbook-sync",
    "data-maintenance",
    "foods-cleanup",
    "ingredient-parse",
    "labels-sync",
    "recipe-quality",
    "taxonomy-audit",
    "taxonomy-refresh",
    "tools-sync",
    "units-cleanup",
    "yield-normalize",
]

# Tasks that expose an `apply` flag that marks the execution as dangerous
APPLY_TASKS = ["foods-cleanup", "labels-sync", "tools-sync", "units-cleanup", "yield-normalize"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build(task_id: str, options: dict | None = None):
    return REGISTRY.build_execution(task_id, options or {})


def _assert_dry_run_safe(execution) -> None:
    assert execution.env.get("DRY_RUN") == "true", "DRY_RUN must be 'true'"
    assert execution.dangerous_requested is False, "dry-run must not be dangerous"


def _assert_valid_command(execution) -> None:
    cmd = execution.command
    assert isinstance(cmd, list) and len(cmd) >= 3, "command must be a non-empty list"
    assert cmd[0] == sys.executable, "command must use current Python interpreter"
    assert cmd[1] == "-m", "command must use -m module invocation"
    assert cmd[2], "module name must be non-empty"


# ---------------------------------------------------------------------------
# Core pipeline: every task, default (dry-run) options
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
def test_all_tasks_registered(task_id: str) -> None:
    assert task_id in REGISTRY.task_ids


@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
def test_dry_run_defaults_are_safe(task_id: str) -> None:
    """Building each task with no explicit options must default to dry-run / safe."""
    execution = _build(task_id)
    _assert_dry_run_safe(execution)
    _assert_valid_command(execution)


@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
def test_explicit_dry_run_true_is_safe(task_id: str) -> None:
    execution = _build(task_id, {"dry_run": True})
    _assert_dry_run_safe(execution)
    _assert_valid_command(execution)


@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
def test_explicit_dry_run_false_is_dangerous(task_id: str) -> None:
    execution = _build(task_id, {"dry_run": False})
    assert execution.env.get("DRY_RUN") == "false"
    assert execution.dangerous_requested is True


@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
def test_unknown_options_are_rejected(task_id: str) -> None:
    with pytest.raises(ValueError, match="Unsupported options"):
        _build(task_id, {"__unknown_key__": "value"})


# ---------------------------------------------------------------------------
# Dangerous flag behaviour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("task_id", APPLY_TASKS)
def test_apply_flag_marks_dangerous(task_id: str) -> None:
    execution = _build(task_id, {"apply": True})
    assert execution.dangerous_requested is True
    assert "--apply" in execution.command


@pytest.mark.parametrize("task_id", APPLY_TASKS)
def test_apply_false_does_not_mark_dangerous_when_dry_run(task_id: str) -> None:
    execution = _build(task_id, {"dry_run": True, "apply": False})
    assert execution.dangerous_requested is False
    assert "--apply" not in execution.command


def test_taxonomy_refresh_cleanup_apply_marks_dangerous() -> None:
    execution = _build("taxonomy-refresh", {"cleanup_apply": True})
    assert execution.dangerous_requested is True
    assert "--cleanup-apply" in execution.command


def test_data_maintenance_apply_cleanups_marks_dangerous() -> None:
    execution = _build("data-maintenance", {"apply_cleanups": True})
    assert execution.dangerous_requested is True
    assert "--apply-cleanups" in execution.command


# ---------------------------------------------------------------------------
# Command construction: categorize
# ---------------------------------------------------------------------------


def test_categorize_module() -> None:
    execution = _build("categorize")
    assert "cookdex.recipe_categorizer" in execution.command


def test_categorize_provider_flag() -> None:
    execution = _build("categorize", {"provider": "openai"})
    assert "--provider" in execution.command
    idx = execution.command.index("--provider")
    assert execution.command[idx + 1] == "openai"


def test_categorize_empty_provider_omits_flag() -> None:
    execution = _build("categorize", {"provider": ""})
    assert "--provider" not in execution.command


# ---------------------------------------------------------------------------
# Command construction: taxonomy-refresh
# ---------------------------------------------------------------------------


def test_taxonomy_refresh_module() -> None:
    execution = _build("taxonomy-refresh")
    assert "cookdex.taxonomy_manager" in execution.command
    assert "refresh" in execution.command


def test_taxonomy_refresh_mode_default_is_merge() -> None:
    execution = _build("taxonomy-refresh")
    idx = execution.command.index("--mode")
    assert execution.command[idx + 1] == "merge"


def test_taxonomy_refresh_custom_mode() -> None:
    execution = _build("taxonomy-refresh", {"mode": "overwrite"})
    idx = execution.command.index("--mode")
    assert execution.command[idx + 1] == "overwrite"


def test_taxonomy_refresh_includes_config_file_flags() -> None:
    execution = _build("taxonomy-refresh")
    assert "--categories-file" in execution.command
    assert "--tags-file" in execution.command


def test_taxonomy_refresh_cleanup_flags_default() -> None:
    execution = _build("taxonomy-refresh")
    # cleanup, cleanup-only-unused, cleanup-delete-noisy all default True
    assert "--cleanup" in execution.command
    assert "--cleanup-only-unused" in execution.command
    assert "--cleanup-delete-noisy" in execution.command
    # cleanup-apply defaults False
    assert "--cleanup-apply" not in execution.command


# ---------------------------------------------------------------------------
# Command construction: taxonomy-audit
# ---------------------------------------------------------------------------


def test_taxonomy_audit_module() -> None:
    execution = _build("taxonomy-audit")
    assert "cookdex.audit_taxonomy" in execution.command


# ---------------------------------------------------------------------------
# Command construction: cookbook-sync
# ---------------------------------------------------------------------------


def test_cookbook_sync_module_and_subcommand() -> None:
    execution = _build("cookbook-sync")
    assert "cookdex.cookbook_manager" in execution.command
    assert "sync" in execution.command


# ---------------------------------------------------------------------------
# Command construction: ingredient-parse
# ---------------------------------------------------------------------------


def test_ingredient_parse_module() -> None:
    execution = _build("ingredient-parse")
    assert "cookdex.ingredient_parser" in execution.command


def test_ingredient_parse_confidence_flag() -> None:
    execution = _build("ingredient-parse", {"confidence_threshold": 0.75})
    assert "--conf" in execution.command
    idx = execution.command.index("--conf")
    assert execution.command[idx + 1] == "0.75"


def test_ingredient_parse_max_recipes_flag() -> None:
    execution = _build("ingredient-parse", {"max_recipes": 50})
    assert "--max" in execution.command
    idx = execution.command.index("--max")
    assert execution.command[idx + 1] == "50"


def test_ingredient_parse_after_slug_flag() -> None:
    execution = _build("ingredient-parse", {"after_slug": "my-recipe"})
    assert "--after-slug" in execution.command
    idx = execution.command.index("--after-slug")
    assert execution.command[idx + 1] == "my-recipe"


def test_ingredient_parse_parsers_flag() -> None:
    execution = _build("ingredient-parse", {"parsers": "wink,nlp"})
    assert "--parsers" in execution.command
    idx = execution.command.index("--parsers")
    assert execution.command[idx + 1] == "wink,nlp"


def test_ingredient_parse_optional_flags_absent_by_default() -> None:
    execution = _build("ingredient-parse")
    for flag in ("--conf", "--max", "--after-slug", "--parsers", "--force-parser"):
        assert flag not in execution.command


# ---------------------------------------------------------------------------
# Command construction: cleanup tasks
# ---------------------------------------------------------------------------


def test_foods_cleanup_module_and_subcommand() -> None:
    execution = _build("foods-cleanup")
    assert "cookdex.foods_manager" in execution.command
    assert "cleanup" in execution.command


def test_units_cleanup_module_and_subcommand() -> None:
    execution = _build("units-cleanup")
    assert "cookdex.units_manager" in execution.command
    assert "cleanup" in execution.command


def test_labels_sync_module() -> None:
    execution = _build("labels-sync")
    assert "cookdex.labels_manager" in execution.command


def test_tools_sync_module() -> None:
    execution = _build("tools-sync")
    assert "cookdex.tools_manager" in execution.command


# ---------------------------------------------------------------------------
# Command construction: data-maintenance
# ---------------------------------------------------------------------------


def test_data_maintenance_module() -> None:
    execution = _build("data-maintenance")
    assert "cookdex.data_maintenance" in execution.command


def test_data_maintenance_stages_flag() -> None:
    execution = _build("data-maintenance", {"stages": "parse,foods"})
    assert "--stages" in execution.command
    idx = execution.command.index("--stages")
    assert execution.command[idx + 1] == "parse,foods"


def test_data_maintenance_stages_list_joined() -> None:
    execution = _build("data-maintenance", {"stages": ["parse", "foods", "units"]})
    idx = execution.command.index("--stages")
    assert execution.command[idx + 1] == "parse,foods,units"


def test_data_maintenance_continue_on_error_flag() -> None:
    execution = _build("data-maintenance", {"continue_on_error": True})
    assert "--continue-on-error" in execution.command


def test_data_maintenance_continue_on_error_default_absent() -> None:
    execution = _build("data-maintenance")
    assert "--continue-on-error" not in execution.command


def test_data_maintenance_skip_ai_flag() -> None:
    execution = _build("data-maintenance", {"skip_ai": True})
    assert "--skip-ai" in execution.command


def test_data_maintenance_skip_ai_default_absent() -> None:
    execution = _build("data-maintenance")
    assert "--skip-ai" not in execution.command


# ---------------------------------------------------------------------------
# Command construction: recipe-quality
# ---------------------------------------------------------------------------


def test_recipe_quality_module() -> None:
    execution = _build("recipe-quality")
    assert "cookdex.recipe_quality_audit" in execution.command


def test_recipe_quality_is_never_dangerous_by_default() -> None:
    execution = _build("recipe-quality")
    assert execution.dangerous_requested is False


def test_recipe_quality_nutrition_sample_flag() -> None:
    execution = _build("recipe-quality", {"nutrition_sample": 50})
    assert "--nutrition-sample" in execution.command
    idx = execution.command.index("--nutrition-sample")
    assert execution.command[idx + 1] == "50"


def test_recipe_quality_nutrition_sample_absent_by_default() -> None:
    execution = _build("recipe-quality")
    assert "--nutrition-sample" not in execution.command


def test_recipe_quality_use_db_flag() -> None:
    execution = _build("recipe-quality", {"use_db": True})
    assert "--use-db" in execution.command


def test_recipe_quality_use_db_absent_by_default() -> None:
    execution = _build("recipe-quality")
    assert "--use-db" not in execution.command


# ---------------------------------------------------------------------------
# Command construction: yield-normalize
# ---------------------------------------------------------------------------


def test_yield_normalize_module() -> None:
    execution = _build("yield-normalize")
    assert "cookdex.yield_normalizer" in execution.command


def test_yield_normalize_apply_marks_dangerous() -> None:
    execution = _build("yield-normalize", {"apply": True})
    assert execution.dangerous_requested is True
    assert "--apply" in execution.command


def test_yield_normalize_default_no_apply() -> None:
    execution = _build("yield-normalize")
    assert "--apply" not in execution.command
    assert execution.dangerous_requested is False


def test_yield_normalize_use_db_flag() -> None:
    execution = _build("yield-normalize", {"use_db": True})
    assert "--use-db" in execution.command


def test_yield_normalize_use_db_absent_by_default() -> None:
    execution = _build("yield-normalize")
    assert "--use-db" not in execution.command


# ---------------------------------------------------------------------------
# Describe tasks: metadata completeness
# ---------------------------------------------------------------------------


def test_describe_tasks_returns_all_tasks() -> None:
    descriptions = REGISTRY.describe_tasks()
    returned_ids = {d["task_id"] for d in descriptions}
    assert returned_ids == set(ALL_TASK_IDS)


@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
def test_task_description_has_required_fields(task_id: str) -> None:
    descriptions = {d["task_id"]: d for d in REGISTRY.describe_tasks()}
    desc = descriptions[task_id]
    assert desc["title"]
    assert desc["description"]
    for opt in desc["options"]:
        assert opt["key"]
        assert opt["label"]
        assert opt["type"] in {"boolean", "string", "integer", "number"}


@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
def test_every_task_has_dry_run_option(task_id: str) -> None:
    descriptions = {d["task_id"]: d for d in REGISTRY.describe_tasks()}
    option_keys = {o["key"] for o in descriptions[task_id]["options"]}
    assert "dry_run" in option_keys


@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
def test_dry_run_option_defaults_true(task_id: str) -> None:
    descriptions = {d["task_id"]: d for d in REGISTRY.describe_tasks()}
    dry_run_opt = next(o for o in descriptions[task_id]["options"] if o["key"] == "dry_run")
    assert dry_run_opt["default"] is True
