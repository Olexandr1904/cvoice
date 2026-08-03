from claude_voice.queue import Item, enqueue, pending, read_item
from claude_voice.state import Paths


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def test_enqueue_writes_a_file(tmp_path):
    paths = _paths(tmp_path)

    enqueue(paths, Item(priority=1, label="app", session="s1", text="hello"))

    assert len(pending(paths)) == 1


def test_read_item_roundtrips(tmp_path):
    paths = _paths(tmp_path)
    enqueue(paths, Item(priority=0, label="app", session="s1", text="hi", flags="force"))

    item = read_item(pending(paths)[0])

    assert item.text == "hi"
    assert item.flags == "force"
    assert item.priority == 0


def test_questions_come_before_summaries(tmp_path):
    paths = _paths(tmp_path)
    enqueue(paths, Item(priority=1, label="app", session="s1", text="summary"))
    enqueue(paths, Item(priority=0, label="app", session="s1", text="question"))

    order = [read_item(path).text for path in pending(paths)]

    assert order == ["question", "summary"]


def test_same_priority_keeps_chronological_order(tmp_path):
    paths = _paths(tmp_path)
    for index in range(5):
        enqueue(paths, Item(priority=1, label="app", session="s1", text=f"item {index}"))

    order = [read_item(path).text for path in pending(paths)]

    assert order == [f"item {index}" for index in range(5)]


def test_empty_text_is_not_queued(tmp_path):
    paths = _paths(tmp_path)

    assert enqueue(paths, Item(priority=1, label="app", session="s1", text="   ")) is None
    assert pending(paths) == []


def test_partial_files_are_ignored(tmp_path):
    paths = _paths(tmp_path)
    (paths.queue_dir / "1-000.json.part").write_text("{}")

    assert pending(paths) == []


import os

from claude_voice.queue import lock


def test_lock_is_acquired_when_free(tmp_path):
    paths = _paths(tmp_path)

    with lock(paths) as acquired:
        assert acquired is True


def test_second_lock_is_refused_while_held(tmp_path):
    paths = _paths(tmp_path)

    with lock(paths) as first:
        assert first is True
        with lock(paths) as second:
            assert second is False


def test_lock_is_released_on_exit(tmp_path):
    paths = _paths(tmp_path)

    with lock(paths):
        pass

    with lock(paths) as acquired:
        assert acquired is True


def test_lock_is_released_even_when_body_raises(tmp_path):
    paths = _paths(tmp_path)

    try:
        with lock(paths):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    with lock(paths) as acquired:
        assert acquired is True


def test_stale_lock_from_dead_process_is_reclaimed(tmp_path):
    paths = _paths(tmp_path)
    paths.lock_dir.mkdir(parents=True, exist_ok=True)
    # PID 0 is never a live user process, so this stands in for a crashed worker.
    (paths.lock_dir / "pid").write_text("0")

    with lock(paths) as acquired:
        assert acquired is True


def test_live_owner_pid_is_respected(tmp_path):
    paths = _paths(tmp_path)
    paths.lock_dir.mkdir(parents=True, exist_ok=True)
    (paths.lock_dir / "pid").write_text(str(os.getpid()))

    with lock(paths) as acquired:
        assert acquired is False
