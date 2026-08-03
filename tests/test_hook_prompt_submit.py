import claude_voice.hooks.prompt_submit as prompt_hook
from claude_voice.queue import Item, enqueue, pending, read_item
from claude_voice.state import Paths


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def test_drops_only_this_sessions_pending_speech(tmp_path):
    paths = _paths(tmp_path)
    enqueue(paths, Item(priority=1, label="app", session="mine", text="stale"))
    enqueue(paths, Item(priority=1, label="app", session="other", text="keep"))

    prompt_hook.handle({"session_id": "mine"}, paths=paths, stopper=lambda: None)

    assert [read_item(path).text for path in pending(paths)] == ["keep"]


def test_stops_playback_when_the_current_utterance_is_ours(tmp_path):
    paths = _paths(tmp_path)
    (paths.state_dir / "current-session").write_text("mine")
    stopped = []

    prompt_hook.handle({"session_id": "mine"}, paths=paths, stopper=lambda: stopped.append(True))

    assert stopped == [True]


def test_leaves_another_sessions_playback_alone(tmp_path):
    paths = _paths(tmp_path)
    (paths.state_dir / "current-session").write_text("other")
    stopped = []

    prompt_hook.handle({"session_id": "mine"}, paths=paths, stopper=lambda: stopped.append(True))

    assert stopped == []


def test_missing_session_id_is_a_no_op(tmp_path):
    paths = _paths(tmp_path)
    enqueue(paths, Item(priority=1, label="app", session="mine", text="stale"))

    prompt_hook.handle({}, paths=paths, stopper=lambda: None)

    assert len(pending(paths)) == 1


def test_hook_prints_nothing(tmp_path, capsys):
    paths = _paths(tmp_path)

    prompt_hook.handle({"session_id": "mine"}, paths=paths, stopper=lambda: None)

    assert capsys.readouterr().out == ""
