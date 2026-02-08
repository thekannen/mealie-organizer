import pytest

from mealie_organizer.taxonomy_manager import normalize_payload_items, MealieTaxonomyManager


def test_normalize_payload_items_from_strings():
    items = normalize_payload_items(["Breakfast", "Dinner"])
    assert items == [{"name": "Breakfast"}, {"name": "Dinner"}]


def test_normalize_payload_items_from_objects():
    items = normalize_payload_items([{"name": "Breakfast"}, {"name": "Dinner", "groupId": "g1"}])
    assert items == [{"name": "Breakfast"}, {"name": "Dinner", "groupId": "g1"}]


def test_normalize_payload_items_rejects_invalid_type():
    with pytest.raises(ValueError):
        normalize_payload_items([1, 2, 3])


def test_noisy_tag_detection():
    assert MealieTaxonomyManager.noisy_tag("How To Make Turkey Gravy") is True
    assert MealieTaxonomyManager.noisy_tag("Weeknight") is False
