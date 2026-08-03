import claude_voice.cli as cli
from claude_voice.config import Config, load, save
from claude_voice.history import add
from claude_voice.queue import Item, enqueue, pending, read_item
from claude_voice.state import Paths, snoozed_until


def _home(tmp_path, monkeypatch, **config_kwargs):
    monkeypatch.setenv("CLAUDE_VOICE_HOME", str(tmp_path / "home"))
    paths = Paths.default()
    paths.ensure()
    save(paths, Config(**config_kwargs) if config_kwargs else Config())
    return paths


def test_status_reports_the_current_mode(tmp_path, monkeypatch, capsys):
    _home(tmp_path, monkeypatch, mode="voice", language="en")

    assert cli.main(["status"]) == 0
    assert "voice" in capsys.readouterr().out


def test_mode_sets_the_global_default(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)

    cli.main(["mode", "off"])

    assert load(paths).mode == "off"


def test_mode_with_project_scope_writes_a_scope_file(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)

    cli.main(["mode", "voice", "--scope", "project", "--project", "/work/app"])

    from claude_voice.config import resolve_mode

    assert resolve_mode(paths, "/work/app", ".claude", default_mode="off") == "voice"


def test_auto_clears_a_scope(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    cli.main(["mode", "voice", "--scope", "project", "--project", "/work/app"])

    cli.main(["auto", "--scope", "project", "--project", "/work/app"])

    from claude_voice.config import resolve_mode

    assert resolve_mode(paths, "/work/app", ".claude", default_mode="off") == "off"


def test_snooze_then_resume(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)

    cli.main(["snooze", "30"])
    assert snoozed_until(paths) is not None

    cli.main(["resume"])
    assert snoozed_until(paths) is None


def test_snooze_clears_the_queue(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    enqueue(paths, Item(priority=1, label="app", session="s", text="stale"))
    monkeypatch.setattr(cli, "stop_playback", lambda: None)

    cli.main(["snooze", "30"])

    assert pending(paths) == []


def test_history_lists_entries_with_ids(tmp_path, monkeypatch, capsys):
    paths = _home(tmp_path, monkeypatch)
    entry = add(paths, kind="tldr", label="app", text="All done.")

    cli.main(["history"])

    output = capsys.readouterr().out
    assert "All done." in output and entry.id in output


def test_play_queues_the_entry_with_the_force_flag(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    entry = add(paths, kind="tldr", label="app", text="Replay me.")
    monkeypatch.setattr(cli.common, "spawn_worker", lambda: None)
    monkeypatch.setattr(cli, "stop_playback", lambda: None)

    cli.main(["play", entry.id])

    item = read_item(pending(paths)[0])
    assert item.text == "Replay me."
    assert item.flags == "force"


def test_play_with_an_unknown_id_fails(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)

    assert cli.main(["play", "nope"]) == 1


def test_replay_speaks_the_newest_entry(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    add(paths, kind="tldr", label="app", text="older")
    add(paths, kind="tldr", label="app", text="newest")
    monkeypatch.setattr(cli.common, "spawn_worker", lambda: None)
    monkeypatch.setattr(cli, "stop_playback", lambda: None)

    cli.main(["replay"])

    assert read_item(pending(paths)[0]).text == "newest"


def test_replay_marks_history_as_seen(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    entry = add(paths, kind="tldr", label="app", text="newest")
    monkeypatch.setattr(cli.common, "spawn_worker", lambda: None)
    monkeypatch.setattr(cli, "stop_playback", lambda: None)

    cli.main(["replay"])

    assert paths.seen_file.read_text().strip() == entry.id


def test_shut_clears_the_queue_and_stops_playback(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    enqueue(paths, Item(priority=1, label="app", session="s", text="stale"))
    stopped = []
    monkeypatch.setattr(cli, "stop_playback", lambda: stopped.append(True))

    cli.main(["shut"])

    assert pending(paths) == [] and stopped == [True]


def test_worker_drains_the_queue(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    enqueue(paths, Item(priority=1, label="app", session="s", text="hello"))
    spoken = []
    monkeypatch.setattr(cli.common, "make_speaker", lambda *a, **k: lambda text, item: spoken.append(text))

    cli.main(["worker"])

    assert spoken == ["app. hello"] or spoken == ["hello"]
    assert pending(paths) == []


def test_hook_subcommand_dispatches_to_the_module(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    called = []
    monkeypatch.setattr(cli.stop_hook, "main", lambda payload, detached: called.append(detached))
    monkeypatch.setattr(cli.common, "read_payload", lambda source: {"session_id": "s"})

    cli.main(["hook", "stop"])

    assert called == [False]


def test_unknown_subcommand_returns_non_zero(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)

    assert cli.main(["nonsense"]) != 0
