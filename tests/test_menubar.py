from cvoice.config import Config
from cvoice.health import record
from cvoice.history import add
from cvoice.menubar.render import render
from cvoice.state import Paths, set_snooze


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def _title(text):
    return text.splitlines()[0]


def test_title_shows_the_mode_icon(tmp_path):
    output = render(_paths(tmp_path), Config(mode="voice"))

    assert _title(output).startswith("🔊")


def test_silent_mode_has_its_own_icon(tmp_path):
    assert _title(render(_paths(tmp_path), Config(mode="off"))).startswith("🔇")


def test_paused_title_shows_remaining_minutes(tmp_path):
    paths = _paths(tmp_path)
    set_snooze(paths, minutes=20)

    assert "⏸" in _title(render(paths, Config(mode="voice")))


def test_unread_counter_is_shown(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="All done.")

    assert "1" in _title(render(paths, Config()))


def test_counter_disappears_once_marked_seen(tmp_path):
    paths = _paths(tmp_path)
    entry = add(paths, kind="tldr", label="app", text="All done.")
    paths.seen_file.write_text(entry.id)

    assert _title(render(paths, Config())).strip() in ("🔔", "🔊", "🔇")


def test_warning_icon_when_something_failed(tmp_path):
    paths = _paths(tmp_path)
    record(paths, "edge-tts", "no network")

    output = render(paths, Config())

    assert _title(output).startswith("⚠️")
    assert "edge-tts: no network" in output


def test_last_message_is_shown_in_the_menu(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="Refactored the sync layer.")

    assert "Refactored the sync layer." in render(paths, Config())


def test_history_entries_are_clickable(tmp_path):
    paths = _paths(tmp_path)
    entry = add(paths, kind="tldr", label="app", text="All done.")

    output = render(paths, Config())

    assert f'param2="play" param3="{entry.id}"' in output


def test_pipe_characters_are_escaped(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="a | b")

    body = "\n".join(render(paths, Config()).splitlines()[1:])

    assert "a / b" in body


def test_long_history_text_is_truncated(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="x" * 200)

    assert "…" in render(paths, Config())
