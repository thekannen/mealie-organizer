import pytest

from cookdex.units_manager import UnitsCleanupManager


class FakeUnitsClient:
    def __init__(self, units=None):
        self._units = units or []
        self.created: list[str] = []
        self.merges: list[tuple[str, str]] = []

    def list_units(self, per_page=1000):
        return list(self._units)

    def create_unit(self, name, abbreviation="", **kwargs):
        self.created.append(name)
        created = {"id": f"new-{len(self.created)}", "name": name}
        self._units.append(created)
        return created

    def merge_unit(self, source_id, target_id):
        self.merges.append((source_id, target_id))
        return {}


def test_load_aliases_rejects_conflicts(tmp_path):
    alias_file = tmp_path / "aliases.json"
    alias_file.write_text(
        '[{"canonical":"Teaspoon","aliases":["t"]},{"canonical":"Tablespoon","aliases":["t"]}]',
        encoding="utf-8",
    )
    manager = UnitsCleanupManager(FakeUnitsClient(), alias_file=alias_file)
    with pytest.raises(ValueError):
        manager.load_aliases()


def test_run_dry_run_plans_alias_merge(tmp_path):
    alias_file = tmp_path / "aliases.json"
    alias_file.write_text(
        '[{"canonical":"Teaspoon","aliases":["t","t."]}]',
        encoding="utf-8",
    )
    client = FakeUnitsClient(
        units=[
            {"id": "u1", "name": "Teaspoon"},
            {"id": "u2", "name": "t"},
        ]
    )
    manager = UnitsCleanupManager(
        client,
        dry_run=True,
        apply=True,
        alias_file=alias_file,
        report_file=tmp_path / "units_report.json",
        checkpoint_dir=tmp_path / "checkpoints",
    )
    report = manager.run()
    assert client.merges == []
    assert report["summary"]["mode"] == "audit"
    assert report["summary"]["merge_candidates_total"] == 1


def test_run_apply_creates_missing_canonical_and_merges(tmp_path):
    alias_file = tmp_path / "aliases.json"
    alias_file.write_text(
        '[{"canonical":"Teaspoon","aliases":["t"]}]',
        encoding="utf-8",
    )
    client = FakeUnitsClient(
        units=[
            {"id": "u2", "name": "t"},
        ]
    )
    manager = UnitsCleanupManager(
        client,
        dry_run=False,
        apply=True,
        alias_file=alias_file,
        report_file=tmp_path / "units_report.json",
        checkpoint_dir=tmp_path / "checkpoints",
    )
    report = manager.run()
    assert client.created == ["Teaspoon"]
    assert client.merges == [("u2", "new-1")]
    assert report["summary"]["actions_applied"] == 1
