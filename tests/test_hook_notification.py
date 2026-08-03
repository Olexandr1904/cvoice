import time

import cvoice.hooks.notification as notification_hook
from cvoice.config import Config, save
from cvoice.history import recent
from cvoice.queue import pending, read_item
from cvoice.state import Paths


def _paths(tmp_path, mode="both"):
    paths = Paths(root=tmp_path / "home")
    paths.ensure()
    save(paths, Config(language="en", mode=mode))
    return paths


def _run(paths, message, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")
    monkeypatch.delenv("CVOICE_CHILD", raising=False)
    sent = []
    notification_hook.handle(
        {"session_id": "s", "message": message},
        paths=paths,
        notifier=lambda **kw: sent.append(kw),
        worker=lambda: None,
    )
    return sent


def test_permission_request_names_the_tool(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="voice")

    _run(paths, "Claude needs your permission to use Bash", monkeypatch)

    assert read_item(pending(paths)[0]).text == "I need permission to use Bash."


def test_permission_request_without_a_tool_name(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="voice")

    _run(paths, "Claude needs your permission", monkeypatch)

    assert read_item(pending(paths)[0]).text == "I need your permission, check the terminal."


def test_idle_nudge_is_announced(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="voice")

    _run(paths, "Claude is waiting for your input", monkeypatch)

    assert read_item(pending(paths)[0]).text == "Waiting for your answer."


def test_idle_nudge_is_not_repeated_within_the_quiet_window(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="voice")

    _run(paths, "Claude is waiting for your input", monkeypatch)
    _run(paths, "Claude is waiting for your input", monkeypatch)

    assert len(pending(paths)) == 1


def test_idle_nudge_returns_after_the_quiet_window(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="voice")
    _run(paths, "Claude is waiting for your input", monkeypatch)
    stamp = paths.state_dir / "notified-s"
    stamp.write_text(str(time.time() - notification_hook.QUIET_SECONDS - 1))

    _run(paths, "Claude is waiting for your input", monkeypatch)

    assert len(pending(paths)) == 2


def test_notices_are_never_written_to_history(tmp_path, monkeypatch):
    paths = _paths(tmp_path)

    _run(paths, "Claude needs your permission to use Bash", monkeypatch)

    assert recent(paths) == []


def test_banner_shows_the_original_message(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="notify")

    sent = _run(paths, "Claude needs your permission to use Bash", monkeypatch)

    assert sent[0]["body"] == "Claude needs your permission to use Bash"


def test_unrecognised_message_is_ignored(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="voice")

    _run(paths, "Something entirely different", monkeypatch)

    assert pending(paths) == []
