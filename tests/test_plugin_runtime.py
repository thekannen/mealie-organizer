from mealie_organizer.plugin_runtime import ParserRunController


def test_parser_run_controller_single_active_run():
    controller = ParserRunController()

    first = controller.start_dry_run()
    assert first is not None
    assert first["status"] == "running"
    assert first["dry_run"] is True
    assert first["run_id"]

    second = controller.start_dry_run()
    assert second is None


def test_parser_run_controller_success_then_new_run():
    controller = ParserRunController()
    first = controller.start_dry_run()
    assert first is not None
    first_id = first["run_id"]

    finished = controller.complete_success({"parsed_successfully": 3, "requires_review": 1, "total_candidates": 4})
    assert finished["status"] == "succeeded"
    assert finished["summary"]["parsed_successfully"] == 3
    assert finished["finished_at"]

    second = controller.start_dry_run()
    assert second is not None
    assert second["run_id"] != first_id
    assert second["status"] == "running"


def test_parser_run_controller_failure_snapshot():
    controller = ParserRunController()
    started = controller.start_dry_run()
    assert started is not None

    failed = controller.complete_failure("boom")
    assert failed["status"] == "failed"
    assert failed["error"] == "boom"
    assert failed["summary"] is None

    snap = controller.snapshot()
    assert snap["status"] == "failed"
    assert snap["error"] == "boom"

