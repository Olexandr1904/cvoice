import json

import cvoice.hooks.common as common
from cvoice.config import Config
from cvoice.i18n import load as load_pack
from cvoice.queue import Item, pending, read_item
from cvoice.state import Paths


def _context(tmp_path, mode="both", monkeypatch=None):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return common.Context(
        paths=paths,
        config=Config(language="en", mode=mode),
        pack=load_pack("en"),
        mode=mode,
        project_dir="/work/app",
        namespace=".claude",
        session="s1",
    )


def test_is_child_reads_the_env_var(monkeypatch):
    monkeypatch.setenv("CVOICE_CHILD", "1")

    assert common.is_child() is True


def test_is_child_false_without_the_env_var(monkeypatch):
    monkeypatch.delenv("CVOICE_CHILD", raising=False)

    assert common.is_child() is False


def test_read_payload_from_stdin(monkeypatch):
    import io

    monkeypatch.setattr(common.sys, "stdin", io.StringIO('{"session_id": "abc"}'))

    assert common.read_payload(None) == {"session_id": "abc"}


def test_read_payload_from_file(tmp_path):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text('{"session_id": "abc"}')

    assert common.read_payload(payload_file) == {"session_id": "abc"}


def test_read_payload_tolerates_garbage(tmp_path):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text("not json")

    assert common.read_payload(payload_file) == {}


def test_label_is_the_project_folder_name():
    assert common.label("/work/my-app", ".claude") == "my-app"


def test_emit_records_history(tmp_path):
    context = _context(tmp_path)

    common.emit(context, kind="tldr", text="All done.", notifier=lambda *a, **k: None, worker=lambda: None)

    from cvoice.history import recent

    assert [entry.text for entry in recent(context.paths)] == ["All done."]


def test_emit_queues_speech_in_voice_mode(tmp_path):
    context = _context(tmp_path, mode="voice")

    common.emit(context, kind="tldr", text="All done.", notifier=lambda *a, **k: None, worker=lambda: None)

    assert [read_item(path).text for path in pending(context.paths)] == ["All done."]


def test_emit_does_not_queue_speech_in_notify_mode(tmp_path):
    context = _context(tmp_path, mode="notify")
    sent = []

    common.emit(context, kind="tldr", text="All done.", notifier=lambda **kw: sent.append(kw), worker=lambda: None)

    assert pending(context.paths) == []
    assert sent and sent[0]["body"] == "All done."


def test_emit_prefers_the_banner_text_when_given(tmp_path):
    context = _context(tmp_path, mode="notify")
    sent = []

    common.emit(
        context,
        kind="question",
        text="I have a question.",
        banner="Which cache layer?",
        notifier=lambda **kw: sent.append(kw),
        worker=lambda: None,
    )

    assert sent[0]["body"] == "Which cache layer?"


def test_emit_records_a_notifier_failure_in_health(tmp_path):
    from cvoice.health import failures

    context = _context(tmp_path, mode="notify")

    def broken(**kwargs):
        raise RuntimeError("no notifier")

    common.emit(context, kind="tldr", text="All done.", notifier=broken, worker=lambda: None)

    assert [failure.component for failure in failures(context.paths)] == ["notify"]


def test_speaker_announces_the_project_only_when_it_changes(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    said = []
    speaker = common.make_speaker(paths, engines=[], sink=said.append)

    speaker("first", Item(priority=1, label="app", session="s", text="first"))
    speaker("second", Item(priority=1, label="app", session="s", text="second"))
    speaker("third", Item(priority=1, label="other", session="s", text="third"))

    assert said == ["app. first", "second", "other. third"]


def test_detach_spawns_a_background_process(tmp_path, monkeypatch):
    spawned = {}

    def fake_popen(argv, **kwargs):
        spawned["argv"] = argv
        spawned["kwargs"] = kwargs

        class Handle:
            pass

        return Handle()

    monkeypatch.setattr(common.subprocess, "Popen", fake_popen)

    common.detach("stop", {"session_id": "abc"})

    assert "hook" in spawned["argv"] and "stop" in spawned["argv"]
    assert spawned["kwargs"]["start_new_session"] is True
    payload_path = spawned["argv"][spawned["argv"].index("--payload") + 1]
    assert json.loads(open(payload_path).read())["session_id"] == "abc"


def test_interrupted_playback_is_not_journalled_as_a_failure(tmp_path):
    """Pressing "silence now" is a user action, not a broken speech stack."""
    from cvoice.health import failures
    from cvoice.speech.base import SpeechInterrupted

    paths = Paths(root=tmp_path)
    paths.ensure()

    class Interrupted:
        name = "edge-tts"

        def available(self):
            return True

        def speak(self, text):
            raise SpeechInterrupted("playback stopped")

    speaker = common.make_speaker(paths, engines=[Interrupted()])
    speaker("hello", Item(priority=1, label="app", session="s", text="hello"))

    assert failures(paths) == []


def test_the_context_defaults_to_claude(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")

    context = common.build_context({"session_id": "s"}, paths=Paths(root=tmp_path))

    assert context.agent == "claude"
    assert context.label == "app"


def test_a_codex_context_is_labelled_with_the_agent(tmp_path):
    context = common.build_context(
        {"session_id": "s"}, paths=Paths(root=tmp_path), agent="codex", project_dir="/work/app"
    )

    assert context.label == "Codex, app"


def test_an_explicit_project_overrides_the_environment(tmp_path, monkeypatch):
    """Codex tells us its working directory; there is no CLAUDE_PROJECT_DIR to read."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/wrong")

    context = common.build_context(
        {"session_id": "s"}, paths=Paths(root=tmp_path), agent="codex", project_dir="/work/right"
    )

    assert context.project_dir == "/work/right"


def test_the_agent_reaches_history(tmp_path):
    from cvoice.history import recent

    context = common.build_context(
        {"session_id": "s"},
        paths=Paths(root=tmp_path),
        agent="codex",
        project_dir="/work/app",
    )
    context.mode = "notify"

    common.emit(context, kind="tldr", text="Done.", notifier=lambda **kw: None, worker=lambda: None)

    assert recent(context.paths)[0].agent == "codex"
