import cvoice.codex as codex


def _config(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_a_missing_config_means_codex_is_not_installed(tmp_path):
    assert codex.is_installed(tmp_path / "nowhere.toml") is False


def test_an_existing_config_means_it_is(tmp_path):
    assert codex.is_installed(_config(tmp_path, "")) is True


def test_the_notify_command_is_read(tmp_path):
    path = _config(tmp_path, 'notify = ["/opt/thing", "turn-ended"]\n')

    assert codex.read_notify(path) == ["/opt/thing", "turn-ended"]


def test_no_notify_key_reads_as_empty(tmp_path):
    assert codex.read_notify(_config(tmp_path, "model = \"gpt\"\n")) == []


def test_a_string_notify_is_read_as_one_word_command(tmp_path):
    """The key is documented as a list, but a plain string must not crash us."""
    path = _config(tmp_path, 'notify = "/opt/thing"\n')

    assert codex.read_notify(path) == ["/opt/thing"]


def test_a_malformed_config_reads_as_empty(tmp_path):
    assert codex.read_notify(_config(tmp_path, "notify = [broken\n")) == []


def test_writing_notify_leaves_other_settings_alone(tmp_path):
    path = _config(
        tmp_path,
        'notify = ["/opt/thing"]\n\n[plugins."browser@bundled"]\nenabled = true\n',
    )

    codex.write_notify(path, ["/new/shim", "hook", "codex"])

    assert codex.read_notify(path) == ["/new/shim", "hook", "codex"]
    assert 'browser@bundled' in path.read_text()
    assert "enabled = true" in path.read_text()


def test_writing_into_a_config_without_notify_adds_it(tmp_path):
    path = _config(tmp_path, 'model = "gpt"\n')

    codex.write_notify(path, ["/new/shim"])

    assert codex.read_notify(path) == ["/new/shim"]
    assert 'model = "gpt"' in path.read_text()


import json


def _rollout(tmp_path, records, name="rollout-2026-08-07T12-00-00-abc.jsonl"):
    day = tmp_path / "sessions" / "2026" / "08" / "07"
    day.mkdir(parents=True, exist_ok=True)
    path = day / name
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def _tool_call():
    return {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "shell"}}


def _user():
    return {"type": "event_msg", "payload": {"type": "user_message", "message": "do it"}}


def _complete(turn_id):
    return {
        "type": "event_msg",
        "payload": {"type": "task_complete", "turn_id": turn_id, "last_agent_message": "done"},
    }


def test_a_turn_that_called_a_tool_did_work(tmp_path):
    _rollout(tmp_path, [_user(), _tool_call(), _complete("t1")])

    assert codex.turn_used_tools("t1", tmp_path / "sessions") is True


def test_a_turn_that_only_talked_did_not(tmp_path):
    _rollout(tmp_path, [_user(), _complete("t1")])

    assert codex.turn_used_tools("t1", tmp_path / "sessions") is False


def test_only_the_named_turn_counts(tmp_path):
    """An earlier turn's tools must not make this one look busy."""
    _rollout(tmp_path, [_user(), _tool_call(), _complete("t1"), _user(), _complete("t2")])

    assert codex.turn_used_tools("t2", tmp_path / "sessions") is False


def test_an_unknown_turn_is_assumed_to_have_worked(tmp_path):
    """A missed summary is worse than a needless one, so silence is not the default."""
    _rollout(tmp_path, [_user(), _complete("t1")])

    assert codex.turn_used_tools("nope", tmp_path / "sessions") is True


def test_a_missing_sessions_directory_is_assumed_to_have_worked(tmp_path):
    assert codex.turn_used_tools("t1", tmp_path / "nowhere") is True


def test_a_corrupt_line_does_not_break_the_scan(tmp_path):
    path = _rollout(tmp_path, [_user(), _tool_call(), _complete("t1")])
    with path.open("a") as handle:
        handle.write("{not json\n")

    assert codex.turn_used_tools("t1", tmp_path / "sessions") is True


def test_the_newest_rollout_is_searched_first(tmp_path):
    import os
    import time

    old = _rollout(tmp_path, [_user(), _complete("t1")], name="rollout-old.jsonl")
    new = _rollout(tmp_path, [_user(), _tool_call(), _complete("t2")], name="rollout-new.jsonl")
    os.utime(old, (time.time() - 600, time.time() - 600))

    assert codex.turn_used_tools("t2", tmp_path / "sessions") is True
