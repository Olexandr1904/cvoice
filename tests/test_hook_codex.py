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


import cvoice.hooks.codex as codex_hook


class FakePopen:
    def __init__(self):
        self.calls = []
        self.kwargs = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        self.kwargs.append(kwargs)

        class Handle:
            pass

        return Handle()


def test_the_original_command_is_called_with_its_own_arguments(monkeypatch):
    popen = FakePopen()
    monkeypatch.setattr(codex_hook.subprocess, "Popen", popen)

    codex_hook.chain(["/opt/thing", "turn-ended"], ["turn-ended", "{}"])

    assert popen.calls == [["/opt/thing", "turn-ended", "turn-ended", "{}"]]


def test_the_chain_is_detached(monkeypatch):
    popen = FakePopen()
    monkeypatch.setattr(codex_hook.subprocess, "Popen", popen)

    codex_hook.chain(["/opt/thing"], [])

    assert popen.kwargs[0]["start_new_session"] is True


def test_no_stored_command_means_no_chain(monkeypatch):
    popen = FakePopen()
    monkeypatch.setattr(codex_hook.subprocess, "Popen", popen)

    codex_hook.chain([], ["anything"])

    assert popen.calls == []


def test_a_chain_that_cannot_start_is_survivable(monkeypatch):
    def explode(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(codex_hook.subprocess, "Popen", explode)

    codex_hook.chain(["/gone"], [])  # must not raise


def test_a_chain_that_cannot_start_is_recorded(tmp_path, monkeypatch):
    """The stored command can go missing - Computer Use may simply be uninstalled."""
    from cvoice.health import failures
    from cvoice.state import Paths

    paths = Paths(root=tmp_path)
    paths.ensure()

    def explode(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(codex_hook.subprocess, "Popen", explode)

    codex_hook.chain(["/gone"], [], paths=paths)

    assert [failure.component for failure in failures(paths)] == ["codex-notify-chain"]


from cvoice.config import Config, save
from cvoice.history import recent
from cvoice.state import Paths


def _prepare(tmp_path, mode="both", original=None):
    paths = Paths(root=tmp_path / "home")
    paths.ensure()
    save(paths, Config(language="en", mode=mode, codex_original_notify=original or []))
    return paths


def _run(paths, args, monkeypatch, summary="Summarised.", used_tools=True):
    import cvoice.codex as codex_module

    monkeypatch.delenv("CVOICE_CHILD", raising=False)
    monkeypatch.setattr(codex_hook.summarize, "run", lambda text, pack, **kw: summary)
    monkeypatch.setattr(codex_module, "turn_used_tools", lambda turn_id, sessions=None: used_tools)
    sent = []
    codex_hook.handle(
        args,
        paths=paths,
        notifier=lambda **kw: sent.append(kw),
        worker=lambda: None,
    )
    return sent


def test_a_finished_turn_is_reported(tmp_path, monkeypatch):
    """The default payload's message is short and already in English, so it is reported
    verbatim rather than through the (stubbed) summarizer - the same threshold behaviour
    already covered for the Claude stop hook."""
    paths = _prepare(tmp_path)

    _run(paths, ["turn-ended", _payload()], monkeypatch, summary="Short summary.")

    assert [entry.text for entry in recent(paths)] == ["Done, all tests pass."]


def test_a_long_turn_is_summarised(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)
    long_reply = _payload(**{"last-assistant-message": "word " * 200})

    _run(paths, [long_reply], monkeypatch, summary="Short summary.")

    assert [entry.text for entry in recent(paths)] == ["Short summary."]


def test_the_entry_is_marked_as_codex(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, [_payload()], monkeypatch)

    entry = recent(paths)[0]
    assert entry.agent == "codex"
    assert entry.label.startswith("Codex")


def test_the_same_turn_is_not_reported_twice(tmp_path, monkeypatch):
    """Codex may call notify more than once for one turn."""
    paths = _prepare(tmp_path)

    _run(paths, [_payload()], monkeypatch)
    _run(paths, [_payload()], monkeypatch)

    assert len(recent(paths)) == 1


def test_a_different_turn_is_reported(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, [_payload()], monkeypatch)
    _run(paths, [_payload(**{"turn-id": "t2", "last-assistant-message": "Second."})], monkeypatch)

    assert len(recent(paths)) == 2


def test_a_turn_that_did_nothing_is_not_reported(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)

    _run(
        paths,
        [_payload(**{"last-assistant-message": "Hi! What shall we work on?"})],
        monkeypatch,
        used_tools=False,
    )

    assert recent(paths) == []


def test_the_project_comes_from_the_payload(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, [_payload(cwd="/work/billing-api")], monkeypatch)

    assert recent(paths)[0].label == "Codex, billing-api"


def test_mode_off_reports_nothing(tmp_path, monkeypatch):
    paths = _prepare(tmp_path, mode="off")

    _run(paths, [_payload()], monkeypatch)

    assert recent(paths) == []


def test_the_chain_runs_even_when_the_mode_is_off(tmp_path, monkeypatch):
    """Being silent is our business; the displaced command still has its own."""
    popen = FakePopen()
    monkeypatch.setattr(codex_hook.subprocess, "Popen", popen)
    paths = _prepare(tmp_path, mode="off", original=["/opt/thing"])

    codex_hook.main(["turn-ended"], paths=paths)

    assert popen.calls == [["/opt/thing", "turn-ended"]]


def test_the_chain_runs_even_when_our_work_raises(tmp_path, monkeypatch):
    popen = FakePopen()
    monkeypatch.setattr(codex_hook.subprocess, "Popen", popen)
    monkeypatch.setattr(codex_hook, "handle", lambda *a, **kw: 1 / 0)
    paths = _prepare(tmp_path, original=["/opt/thing"])

    codex_hook.main(["turn-ended", _payload()], paths=paths)

    assert popen.calls == [["/opt/thing", "turn-ended", _payload()]]


def test_nothing_happens_inside_our_own_summariser(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)
    monkeypatch.setenv("CVOICE_CHILD", "1")
    popen = FakePopen()
    monkeypatch.setattr(codex_hook.subprocess, "Popen", popen)

    codex_hook.main([_payload()], paths=paths)

    assert recent(paths) == []
    assert popen.calls == []
