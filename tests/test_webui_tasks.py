from mealie_organizer.webui_server.tasks import TaskRegistry


def test_registry_defaults_to_dry_run_for_parser():
    registry = TaskRegistry()
    execution = registry.build_execution("ingredient-parse", {})
    assert execution.env["DRY_RUN"] == "true"
    assert execution.dangerous_requested is False


def test_registry_marks_apply_option_as_dangerous():
    registry = TaskRegistry()
    execution = registry.build_execution("foods-cleanup", {"apply": True})
    assert execution.dangerous_requested is True


def test_registry_rejects_unknown_options():
    registry = TaskRegistry()
    try:
        registry.build_execution("categorize", {"unknown": "value"})
    except ValueError as exc:
        assert "Unsupported options" in str(exc)
    else:
        assert False, "Expected ValueError for unsupported options."
