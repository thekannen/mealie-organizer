from cookdex.foods_manager import FoodMergeAction, FoodsCleanupManager


class FakeFoodsClient:
    def __init__(self, foods=None, recipes=None):
        self._foods = foods or []
        self._recipes = recipes or []
        self.merges: list[tuple[str, str]] = []

    def list_foods(self, per_page=1000):
        return list(self._foods)

    def get_recipes(self, per_page=1000):
        return list(self._recipes)

    def merge_food(self, source_id, target_id):
        self.merges.append((source_id, target_id))
        return {}


def test_normalize_name_deterministic():
    assert FoodsCleanupManager.normalize_name("  TEAspoon  ") == "teaspoon"
    assert FoodsCleanupManager.normalize_name("Teaspoon") == "teaspoon"


def test_choose_canonical_prefers_usage_then_id():
    candidates = [
        {"id": "10", "name": "Onion"},
        {"id": "05", "name": "Onion"},
    ]
    usage = {"10": 7, "05": 7}
    selected = FoodsCleanupManager.choose_canonical(candidates, usage)
    assert selected["id"] == "05"


def test_build_merge_plan_for_exact_duplicates():
    client = FakeFoodsClient()
    manager = FoodsCleanupManager(client, dry_run=True)
    foods = [
        {"id": "1", "name": "Onion", "groupId": "g1"},
        {"id": "2", "name": " onion ", "groupId": "g1"},
        {"id": "3", "name": "Garlic", "groupId": "g1"},
    ]
    usage = {"1": 5, "2": 1}
    actions = manager.build_merge_plan(foods, usage)
    assert len(actions) == 1
    assert actions[0] == FoodMergeAction(
        source_id="2",
        source_name=" onion ",
        target_id="1",
        target_name="Onion",
        group_id="g1",
        normalized_name="onion",
        source_usage=1,
        target_usage=5,
    )


def test_run_dry_run_does_not_merge(tmp_path):
    foods = [
        {"id": "1", "name": "Onion", "groupId": "g1"},
        {"id": "2", "name": "onion", "groupId": "g1"},
    ]
    recipes = [{"recipeIngredient": [{"food": {"id": "1"}}]}]
    client = FakeFoodsClient(foods=foods, recipes=recipes)
    manager = FoodsCleanupManager(
        client,
        dry_run=True,
        apply=True,
        report_file=tmp_path / "foods_report.json",
        checkpoint_dir=tmp_path / "checkpoints",
    )
    report = manager.run()
    assert client.merges == []
    assert report["summary"]["mode"] == "audit"
    assert report["summary"]["merge_candidates_total"] == 1


def test_run_apply_respects_max_actions_and_checkpoint(tmp_path):
    foods = [
        {"id": "1", "name": "Onion", "groupId": "g1"},
        {"id": "2", "name": "onion", "groupId": "g1"},
        {"id": "3", "name": "Garlic", "groupId": "g1"},
        {"id": "4", "name": "garlic", "groupId": "g1"},
    ]
    recipes = [{"recipeIngredient": [{"food": {"id": "1"}}, {"food": {"id": "3"}}]}]
    client = FakeFoodsClient(foods=foods, recipes=recipes)
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    (checkpoint_dir / "foods_cleanup_checkpoint.json").write_text(
        '{"merged_source_ids":["2"]}',
        encoding="utf-8",
    )

    manager = FoodsCleanupManager(
        client,
        dry_run=False,
        apply=True,
        max_actions=1,
        report_file=tmp_path / "foods_report.json",
        checkpoint_dir=checkpoint_dir,
    )
    report = manager.run()
    assert client.merges == [("4", "3")]
    assert report["summary"]["actions_applied"] == 1
    assert report["summary"]["checkpoint_skipped"] == 1
