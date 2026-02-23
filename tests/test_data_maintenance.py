import pytest

from cookdex import data_maintenance
from cookdex.data_maintenance import StageResult, StageRuntimeOptions


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


def test_stage_command_categorize_provider_override():
    cmd = data_maintenance.stage_command(
        "categorize",
        apply_cleanups=False,
        stage_options=StageRuntimeOptions(provider="chatgpt"),
    )
    assert "--provider" in cmd
    idx = cmd.index("--provider")
    assert cmd[idx + 1] == "chatgpt"


def test_stage_command_yield_use_db_flag():
    cmd = data_maintenance.stage_command("yield", apply_cleanups=False, use_db=True)
    assert "--use-db" in cmd


def test_run_stage_categorize_uses_provider_override(monkeypatch):
    monkeypatch.setattr(data_maintenance, "_categorizer_provider_active", lambda: False)

    class _Completed:
        returncode = 0

    def _fake_run(cmd, check):
        assert "--provider" in cmd
        idx = cmd.index("--provider")
        assert cmd[idx + 1] == "chatgpt"
        assert check is False
        return _Completed()

    monkeypatch.setattr(data_maintenance.subprocess, "run", _fake_run)
    result = data_maintenance.run_stage(
        "categorize",
        apply_cleanups=False,
        stage_options=StageRuntimeOptions(provider="chatgpt"),
    )
    assert result.exit_code == 0
    assert "--provider" in result.command


def test_run_pipeline_fail_fast(monkeypatch):
    calls: list[str] = []

    def fake_run_stage(stage, *, apply_cleanups, skip_ai=False, use_db=False, nutrition_sample=None, stage_options=None):
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

    def fake_run_stage(stage, *, apply_cleanups, skip_ai=False, use_db=False, nutrition_sample=None, stage_options=None):
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
