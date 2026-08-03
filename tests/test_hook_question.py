import cvoice.hooks.question as question_hook
from cvoice.config import Config, save
from cvoice.history import recent
from cvoice.state import Paths


def _paths(tmp_path, language="en", mode="both"):
    paths = Paths(root=tmp_path / "home")
    paths.ensure()
    save(paths, Config(language=language, mode=mode))
    return paths


def _run(paths, payload, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")
    monkeypatch.delenv("CVOICE_CHILD", raising=False)
    sent = []
    question_hook.handle(payload, paths=paths, notifier=lambda **kw: sent.append(kw), worker=lambda: None)
    return sent


def test_plan_mode_announces_the_plan(tmp_path, monkeypatch):
    paths = _paths(tmp_path)

    _run(paths, {"session_id": "s", "tool_name": "ExitPlanMode", "tool_input": {}}, monkeypatch)

    assert recent(paths)[0].text == "The plan is ready, take a look."


def test_question_in_the_target_language_is_spoken_in_full(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    payload = {
        "session_id": "s",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "Which cache layer should we use?"}]},
    }

    _run(paths, payload, monkeypatch)

    assert "Which cache layer" in recent(paths)[0].text


def test_question_in_another_language_falls_back_to_a_generic_phrase(tmp_path, monkeypatch):
    paths = _paths(tmp_path, language="uk")
    payload = {
        "session_id": "s",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "Which cache layer should we use?"}]},
    }

    _run(paths, payload, monkeypatch)

    assert recent(paths)[0].text == "У мене питання, глянь у термінал."


def test_banner_always_shows_the_question_verbatim(tmp_path, monkeypatch):
    paths = _paths(tmp_path, language="uk")
    payload = {
        "session_id": "s",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "Which cache layer?"}]},
    }

    sent = _run(paths, payload, monkeypatch)

    assert sent[0]["body"] == "Which cache layer?"


def test_several_questions_are_counted_in_the_banner(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    payload = {
        "session_id": "s",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "First?"}, {"question": "Second?"}]},
    }

    sent = _run(paths, payload, monkeypatch)

    assert "+1" in sent[0]["body"]


def test_questions_are_queued_at_high_priority(tmp_path, monkeypatch):
    from cvoice.queue import pending, read_item

    paths = _paths(tmp_path, mode="voice")
    payload = {"session_id": "s", "tool_name": "ExitPlanMode", "tool_input": {}}

    _run(paths, payload, monkeypatch)

    assert read_item(pending(paths)[0]).priority == 0


def test_other_tools_are_ignored(tmp_path, monkeypatch):
    paths = _paths(tmp_path)

    _run(paths, {"session_id": "s", "tool_name": "Bash", "tool_input": {}}, monkeypatch)

    assert recent(paths) == []


def test_mode_off_does_nothing(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="off")

    _run(paths, {"session_id": "s", "tool_name": "ExitPlanMode", "tool_input": {}}, monkeypatch)

    assert recent(paths) == []
