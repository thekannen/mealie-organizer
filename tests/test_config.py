import pytest

from mealie_organizer.config import to_bool


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ("true", True),
        ("FALSE", False),
        ("yes", True),
        ("off", False),
    ],
)
def test_to_bool_valid_values(value, expected):
    assert to_bool(value) is expected


def test_to_bool_invalid_value():
    with pytest.raises(ValueError):
        to_bool("maybe")
