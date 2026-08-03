from claude_voice.history import add, get, recent
from claude_voice.state import Paths


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def test_add_returns_entry_with_id(tmp_path):
    paths = _paths(tmp_path)

    entry = add(paths, kind="tldr", label="app", text="Done.", directory="/work/app", namespace=".claude")

    assert entry is not None
    assert entry.id
    assert entry.text == "Done."
    assert entry.kind == "tldr"


def test_notices_are_never_stored(tmp_path):
    paths = _paths(tmp_path)

    assert add(paths, kind="notice", label="app", text="Waiting for you.") is None
    assert recent(paths) == []


def test_consecutive_duplicates_are_collapsed(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="Same thing")

    assert add(paths, kind="tldr", label="app", text="Same thing") is None
    assert len(recent(paths)) == 1


def test_recent_returns_newest_first(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="first")
    add(paths, kind="question", label="app", text="second")

    entries = recent(paths, limit=10)

    assert [entry.text for entry in entries] == ["second", "first"]


def test_get_finds_entry_by_id(tmp_path):
    paths = _paths(tmp_path)
    entry = add(paths, kind="tldr", label="app", text="findable")

    assert get(paths, entry.id).text == "findable"


def test_get_returns_none_for_unknown_id(tmp_path):
    paths = _paths(tmp_path)

    assert get(paths, "nope") is None


def test_file_is_trimmed_to_the_keep_limit(tmp_path):
    paths = _paths(tmp_path)
    for index in range(12):
        add(paths, kind="tldr", label="app", text=f"line {index}", keep=5)

    assert len(paths.history_file.read_text().strip().splitlines()) <= 5


def test_corrupt_line_does_not_break_reading(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="good")
    with paths.history_file.open("a") as handle:
        handle.write("{not json\n")

    assert [entry.text for entry in recent(paths)] == ["good"]
