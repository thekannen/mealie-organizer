import requests

from cookdex.labels_manager import LabelsSyncManager, load_label_names
from cookdex.tools_manager import ToolsSyncManager, load_tool_names


class FakeLabelsClient:
    def __init__(self):
        self.labels = [{"id": "1", "name": "Meal Prep"}]
        self.created: list[str] = []
        self.deleted: list[str] = []

    def list_labels(self, per_page=1000):
        return list(self.labels)

    def create_label(self, name):
        self.created.append(name)
        created = {"id": f"new-{len(self.created)}", "name": name}
        self.labels.append(created)
        return created

    def delete_label(self, label_id):
        self.deleted.append(label_id)


class FakeToolsClient:
    def __init__(self):
        self.tools = [{"id": "1", "name": "Blender"}, {"id": "2", "name": " blender "}]
        self.created: list[str] = []
        self.merged: list[tuple[str, str]] = []

    def list_tools(self, per_page=1000):
        return list(self.tools)

    def create_tool(self, name):
        self.created.append(name)
        created = {"id": f"new-{len(self.created)}", "name": name}
        self.tools.append(created)
        return created

    def merge_tool(self, source_id, target_id):
        self.merged.append((source_id, target_id))
        return {}


class FakeToolsUnsupportedClient:
    def __init__(self):
        self.tools = []
        self.created: list[str] = []

    def list_tools(self, per_page=1000):
        return list(self.tools)

    def create_tool(self, name):
        self.created.append(name)
        response = requests.Response()
        response.status_code = 404
        raise requests.HTTPError("tools endpoint missing", response=response)

    def merge_tool(self, source_id, target_id):
        raise AssertionError("merge_tool should not be called when create endpoint is unavailable")


def test_load_label_names_dedups(tmp_path):
    file_path = tmp_path / "labels.json"
    file_path.write_text('["Meal Prep", "meal prep", "New Recipe"]', encoding="utf-8")
    names = load_label_names(file_path)
    assert names == ["Meal Prep", "New Recipe"]


def test_labels_sync_dry_run_no_writes(tmp_path):
    file_path = tmp_path / "labels.json"
    file_path.write_text('["Meal Prep", "Quick Win"]', encoding="utf-8")
    client = FakeLabelsClient()
    manager = LabelsSyncManager(client, dry_run=True, apply=True, file_path=file_path)
    report = manager.run()
    assert client.created == []
    assert report["summary"]["mode"] == "audit"


def test_load_tool_names_dedups(tmp_path):
    file_path = tmp_path / "tools.json"
    file_path.write_text('["Blender", " blender ", "Dutch Oven"]', encoding="utf-8")
    names = load_tool_names(file_path)
    assert names == ["Blender", "Dutch Oven"]


def test_tools_sync_apply_merges_duplicates(tmp_path):
    file_path = tmp_path / "tools.json"
    file_path.write_text('["Blender"]', encoding="utf-8")
    client = FakeToolsClient()
    manager = ToolsSyncManager(
        client,
        dry_run=False,
        apply=True,
        file_path=file_path,
        checkpoint_dir=tmp_path / "checkpoints",
    )
    report = manager.run()
    assert client.merged == [("2", "1")]
    assert report["summary"]["merged"] == 1


def test_tools_sync_apply_stops_after_endpoint_unavailable(tmp_path):
    file_path = tmp_path / "tools.json"
    file_path.write_text('["Blender", "Dutch Oven", "Slow Cooker"]', encoding="utf-8")
    client = FakeToolsUnsupportedClient()
    manager = ToolsSyncManager(
        client,
        dry_run=False,
        apply=True,
        file_path=file_path,
        checkpoint_dir=tmp_path / "checkpoints",
    )
    report = manager.run()
    assert client.created == ["Blender"]
    assert report["summary"]["failed"] == 1
    assert report["summary"]["skipped"] == 2
