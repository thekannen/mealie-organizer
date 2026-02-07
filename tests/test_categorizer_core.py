from mealie_scripts.categorizer_core import parse_json_response


def test_parse_json_response_handles_json_fence():
    raw = "```json\n[{\"slug\":\"abc\",\"categories\":[\"Dinner\"],\"tags\":[\"Quick\"]}]\n```"
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["slug"] == "abc"


def test_parse_json_response_handles_unquoted_keys_and_trailing_comma():
    raw = "[{slug: 'abc', categories: ['Dinner'], tags: ['Quick'],}]"
    parsed = parse_json_response(raw)
    assert isinstance(parsed, list)
    assert parsed[0]["categories"] == ["Dinner"]


def test_parse_json_response_returns_none_for_invalid_payload():
    parsed = parse_json_response("not-json-output")
    assert parsed is None
