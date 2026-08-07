import json

from cvoice.hooks.codex import parse_payload


def _payload(**overrides):
    data = {
        "type": "agent-turn-complete",
        "turn-id": "t1",
        "last-assistant-message": "Done, all tests pass.",
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def test_json_in_the_last_argument_is_found():
    parsed = parse_payload(["turn-ended", _payload()])

    assert parsed["message"] == "Done, all tests pass."
    assert parsed["turn_id"] == "t1"


def test_json_in_the_first_argument_is_found():
    """The argv layout was never observed directly, so position is not assumed."""
    parsed = parse_payload([_payload(), "turn-ended"])

    assert parsed["message"] == "Done, all tests pass."


def test_json_in_the_middle_is_found():
    parsed = parse_payload(["a", _payload(), "b"])

    assert parsed["message"] == "Done, all tests pass."


def test_the_snake_case_message_key_is_accepted():
    raw = json.dumps({"turn_id": "t2", "last_agent_message": "Done."})

    parsed = parse_payload([raw])

    assert parsed == {"message": "Done.", "turn_id": "t2"}


def test_the_plain_message_key_is_accepted():
    raw = json.dumps({"turn_id": "t3", "message": "Done."})

    assert parse_payload([raw])["message"] == "Done."


def test_no_arguments_parse_to_nothing():
    assert parse_payload([]) is None


def test_arguments_without_json_parse_to_nothing():
    assert parse_payload(["turn-ended", "--verbose"]) is None


def test_malformed_json_parses_to_nothing():
    assert parse_payload(["{not json"]) is None


def test_json_without_a_message_parses_to_nothing():
    assert parse_payload([json.dumps({"turn-id": "t1"})]) is None


def test_an_empty_message_parses_to_nothing():
    assert parse_payload([_payload(**{"last-assistant-message": "   "})]) is None


def test_a_missing_turn_id_is_survivable():
    raw = json.dumps({"last-assistant-message": "Done."})

    assert parse_payload([raw]) == {"message": "Done.", "turn_id": ""}


def test_a_json_array_is_not_mistaken_for_a_payload():
    assert parse_payload([json.dumps(["a", "b"])]) is None


def test_the_working_directory_is_read_when_present():
    raw = json.dumps({"turn_id": "t1", "message": "Done.", "cwd": "/work/app"})

    assert parse_payload([raw])["cwd"] == "/work/app"
