import pytest

from cookdex import data_maintenance
from cookdex.data_maintenance import StageResult


def test_parse_stage_list_valid():
    assert data_maintenance.parse_stage_list("parse,foods,units") == ["parse", "foods", "units"]


def test_parse_stage_list_rejects_unknown_stage():
    with pytest.raises(ValueError):
        data_maintenance.parse_stage_list("parse,unknown")


def test_stage_command_adds_apply_flag_for_cleanups():
    foods_cmd = data_maintenance.stage_command("foods", apply_cleanups=True)
    units_cmd = data_maintenance.stage_command("units", apply_cleanups=True)
    assert "--apply" in foods_cmd
    assert "--apply" in units_cmd


def test_run_pipeline_fail_fast(monkeypatch):
    calls: list[str] = []

    def fake_run_stage(stage, *, apply_cleanups, skip_ai=False, use_db=False, nutrition_sample=None):
        calls.append(stage)
        if stage == "foods":
            return StageResult(stage=stage, command=["x"], exit_code=1)
        return StageResult(stage=stage, command=["x"], exit_code=0)

    monkeypatch.setattr(data_maintenance, "run_stage", fake_run_stage)
    results = data_maintenance.run_pipeline(
        ["parse", "foods", "units"],
        continue_on_error=False,
        apply_cleanups=False,
    )
    assert [item.stage for item in results] == ["parse", "foods"]
    assert calls == ["parse", "foods"]


def test_run_pipeline_continue_on_error(monkeypatch):
    calls: list[str] = []

    def fake_run_stage(stage, *, apply_cleanups, skip_ai=False, use_db=False, nutrition_sample=None):
        calls.append(stage)
        code = 1 if stage == "foods" else 0
        return StageResult(stage=stage, command=["x"], exit_code=code)

    monkeypatch.setattr(data_maintenance, "run_stage", fake_run_stage)
    results = data_maintenance.run_pipeline(
        ["parse", "foods", "units"],
        continue_on_error=True,
        apply_cleanups=False,
    )
    assert [item.stage for item in results] == ["parse", "foods", "units"]
    assert calls == ["parse", "foods", "units"]


def test_fmt_elapsed_rolls_over_rounded_seconds():
    assert data_maintenance._fmt_elapsed(119.6) == "2m 0s"
    assert data_maintenance._fmt_elapsed(179.6) == "3m 0s"
