import json

from claude_voice.history import recent
from claude_voice.migrate import migrate
from claude_voice.state import Paths


def _old(tmp_path):
    old = tmp_path / ".claude-tts"
    (old / "state").mkdir(parents=True)
    return old


def test_history_is_imported(tmp_path):
    old = _old(tmp_path)
    (old / "history.jsonl").write_text(
        json.dumps({"id": "1", "ts": 1, "kind": "tldr", "label": "app", "text": "old entry"}) + "\n"
    )
    paths = Paths(root=tmp_path / "new")
    paths.ensure()

    migrate(old, paths)

    assert [entry.text for entry in recent(paths)] == ["old entry"]


def test_unknown_fields_in_old_entries_are_dropped(tmp_path):
    old = _old(tmp_path)
    (old / "history.jsonl").write_text(
        json.dumps({"id": "1", "ts": 1, "kind": "tldr", "label": "app", "text": "x", "sid": "s", "dir": "/d"}) + "\n"
    )
    paths = Paths(root=tmp_path / "new")
    paths.ensure()

    migrate(old, paths)

    assert recent(paths)[0].text == "x"


def test_old_directory_is_left_untouched(tmp_path):
    old = _old(tmp_path)
    (old / "history.jsonl").write_text(
        json.dumps({"id": "1", "ts": 1, "kind": "tldr", "label": "app", "text": "old"}) + "\n"
    )
    paths = Paths(root=tmp_path / "new")
    paths.ensure()

    migrate(old, paths)

    assert (old / "history.jsonl").exists()


def test_missing_old_installation_is_not_an_error(tmp_path):
    paths = Paths(root=tmp_path / "new")
    paths.ensure()

    assert migrate(tmp_path / "nothing-here", paths) == 0


def test_existing_history_is_not_overwritten(tmp_path):
    old = _old(tmp_path)
    (old / "history.jsonl").write_text(
        json.dumps({"id": "1", "ts": 1, "kind": "tldr", "label": "app", "text": "old"}) + "\n"
    )
    paths = Paths(root=tmp_path / "new")
    paths.ensure()
    paths.history_file.write_text(
        json.dumps({"id": "2", "ts": 2, "kind": "tldr", "label": "app", "text": "already here"}) + "\n"
    )

    migrate(old, paths)

    texts = {entry.text for entry in recent(paths)}
    assert texts == {"old", "already here"}
