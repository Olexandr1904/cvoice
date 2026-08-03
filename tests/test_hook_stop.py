import cvoice.hooks.stop as stop_hook
from cvoice.config import Config, save
from cvoice.history import recent
from cvoice.state import Paths


def _prepare(tmp_path, mode="notify", language="en"):
    paths = Paths(root=tmp_path / "home")
    paths.ensure()
    save(paths, Config(language=language, mode=mode))
    return paths


def _run(paths, transcript_path, monkeypatch, summary="Summarised."):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/me/.claude")
    monkeypatch.delenv("CVOICE_CHILD", raising=False)
    monkeypatch.setattr(stop_hook.summarize, "run", lambda text, pack, **kw: summary)
    stop_hook.handle(
        {"session_id": "s1", "transcript_path": str(transcript_path)},
        paths=paths,
        notifier=lambda **kwargs: None,
        worker=lambda: None,
    )


def test_last_assistant_message_becomes_history(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, transcript("first reply", "final reply"), monkeypatch, summary="Short summary.")

    assert [entry.text for entry in recent(paths)] == ["final reply"]


def test_short_reply_in_the_target_language_is_used_verbatim(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, transcript("All tests pass, nothing else to do."), monkeypatch, summary="SHOULD NOT BE USED")

    assert [entry.text for entry in recent(paths)] == ["All tests pass, nothing else to do."]


def test_long_reply_is_summarised(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, transcript("word " * 200), monkeypatch, summary="Summarised.")

    assert [entry.text for entry in recent(paths)] == ["Summarised."]


def test_markdown_is_stripped_before_deciding(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, transcript("All tests pass, `nothing` else to do."), monkeypatch, summary="unused")

    assert "`" not in recent(paths)[0].text


def test_summariser_failure_falls_back_to_a_phrase(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, transcript("word " * 200), monkeypatch, summary=None)

    assert recent(paths)[0].text == "The turn is done, the details are in the terminal."


def test_sidechain_messages_are_ignored(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)
    path = transcript("subagent chatter", sidechain=True)

    _run(paths, path, monkeypatch)

    assert recent(paths) == []


def test_same_reply_twice_is_not_repeated(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)
    path = transcript("All tests pass, nothing else to do.")

    _run(paths, path, monkeypatch)
    _run(paths, path, monkeypatch)

    assert len(recent(paths)) == 1


def test_mode_off_does_nothing(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path, mode="off")

    _run(paths, transcript("All tests pass."), monkeypatch)

    assert recent(paths) == []


def test_missing_transcript_is_survivable(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, tmp_path / "nope.jsonl", monkeypatch)

    assert recent(paths) == []


def test_entry_point_detaches_and_returns_immediately(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(stop_hook.common, "detach", lambda name, payload: calls.append(name))
    monkeypatch.delenv("CVOICE_CHILD", raising=False)

    stop_hook.main({"session_id": "s1"}, detached=False)

    assert calls == ["stop"]


def test_entry_point_does_nothing_inside_the_summariser_child(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(stop_hook.common, "detach", lambda name, payload: calls.append(name))
    monkeypatch.setenv("CVOICE_CHILD", "1")

    stop_hook.main({"session_id": "s1"}, detached=False)

    assert calls == []
