import cvoice.summarize as summarize_module
from cvoice.i18n import load
from cvoice.summarize import run

PACK = load("en")


class FakeRun:
    def __init__(self, stdout="Fixed the parser and added tests.", returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.calls = []
        self.env = None

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        self.env = kwargs.get("env")
        self.kwargs = kwargs

        class Result:
            pass

        result = Result()
        result.returncode = self.returncode
        result.stdout = self.stdout
        result.stderr = ""
        return result


def test_returns_the_model_output(monkeypatch):
    monkeypatch.setattr(summarize_module.subprocess, "run", FakeRun())

    assert run("a long reply", PACK) == "Fixed the parser and added tests."


def test_the_reply_is_the_whole_user_message(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("REPLY-MARKER", PACK)

    assert fake.calls[0][-1] == "REPLY-MARKER"


def test_the_task_lives_in_the_system_prompt(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("a reply", PACK)

    argv = fake.calls[0]
    assert argv[argv.index("--append-system-prompt") + 1] == PACK.summary_system


def test_hooks_are_disabled_in_the_child(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("a reply", PACK)

    argv = fake.calls[0]
    assert "--settings" in argv
    assert '"disableAllHooks":true' in argv[argv.index("--settings") + 1].replace(" ", "")


def test_child_marker_env_var_is_set(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("a reply", PACK)

    assert fake.env["CVOICE_CHILD"] == "1"


def test_the_default_model_is_requested(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("a reply", PACK)

    argv = fake.calls[0]
    assert argv[argv.index("--model") + 1] == "sonnet"


def test_long_reply_is_truncated_before_sending(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("x" * 20000, PACK)

    assert len(fake.calls[0][-1]) < 12000


def test_non_zero_exit_returns_none(monkeypatch):
    monkeypatch.setattr(summarize_module.subprocess, "run", FakeRun(returncode=1))

    assert run("a reply", PACK) is None


def test_empty_output_returns_none(monkeypatch):
    monkeypatch.setattr(summarize_module.subprocess, "run", FakeRun(stdout="   \n"))

    assert run("a reply", PACK) is None


def test_markdown_is_stripped_from_the_answer(monkeypatch):
    monkeypatch.setattr(summarize_module.subprocess, "run", FakeRun(stdout="**Done**: fixed `parser.py`"))

    assert run("a reply", PACK) == "Done: fixed parser.py"


def test_timeout_returns_none(monkeypatch):
    def explode(argv, **kwargs):
        raise summarize_module.subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(summarize_module.subprocess, "run", explode)

    assert run("a reply", PACK) is None


def test_stdin_is_closed(monkeypatch):
    """A child inherits stdin, and a hook's stdin is Claude Code's JSON payload - the
    model would summarize that instead of the reply."""
    import subprocess as real_subprocess

    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("a reply", PACK)

    assert fake.kwargs["stdin"] is real_subprocess.DEVNULL


def test_it_runs_in_an_empty_directory(monkeypatch):
    """Otherwise the child answers from the project's CLAUDE.md and memory.

    The directory is checked while the call is in flight: it is a temporary one and is
    gone by the time run() returns.
    """
    from pathlib import Path as _Path

    seen = {}

    class CheckingRun(FakeRun):
        def __call__(self, argv, **kwargs):
            cwd = kwargs["cwd"]
            seen["exists"] = _Path(cwd).is_dir()
            seen["empty"] = not list(_Path(cwd).iterdir())
            return super().__call__(argv, **kwargs)

    monkeypatch.setattr(summarize_module.subprocess, "run", CheckingRun())

    run("a reply", PACK)

    assert seen == {"exists": True, "empty": True}


def test_memory_and_project_instructions_are_disabled(monkeypatch):
    import json as _json

    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("a reply", PACK)

    argv = fake.calls[0]
    settings = _json.loads(argv[argv.index("--settings") + 1])
    assert settings["disableAllHooks"] is True
    assert settings["autoMemoryEnabled"] is False
    assert settings["claudeMdExcludes"]


def test_the_model_is_configurable(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("a reply", PACK, model="haiku")

    argv = fake.calls[0]
    assert argv[argv.index("--model") + 1] == "haiku"


def test_condense_keeps_at_most_three_sentences():
    from cvoice.summarize import condense

    text = "One. Two. Three. Four. Five."

    assert condense(text) == "One. Two. Three."


def test_condense_truncates_a_single_runaway_sentence():
    from cvoice.summarize import condense

    out = condense("word " * 200)

    assert len(out) <= 321
    assert out.endswith("…")


def test_condense_collapses_whitespace():
    from cvoice.summarize import condense

    assert condense("  Done.\n\n  Tests pass.  ") == "Done. Tests pass."


def test_condense_leaves_a_short_summary_alone():
    from cvoice.summarize import condense

    assert condense("Done, all tests pass.") == "Done, all tests pass."


def test_a_runaway_answer_is_cut_before_it_is_spoken(monkeypatch):
    """One real answer came back at 1248 characters - ninety seconds of speech."""
    monkeypatch.setattr(summarize_module.subprocess, "run", FakeRun(stdout="Sentence. " * 200))

    answer = run("a reply", PACK)

    assert len(answer) <= 321


def test_condense_does_not_break_file_names():
    from cvoice.summarize import condense

    assert condense("Done: fixed parser.py and bumped to 1.2.3.") == "Done: fixed parser.py and bumped to 1.2.3."


def test_the_no_summary_sentinel_is_rejected(monkeypatch):
    """The model is told to say this instead of starting a conversation."""
    monkeypatch.setattr(summarize_module.subprocess, "run", FakeRun(stdout="NO_SUMMARY"))

    assert run("a reply", PACK) is None


def test_a_summary_may_relay_a_pending_question(monkeypatch):
    """A reply waiting for approval must be voiced as waiting for approval."""
    monkeypatch.setattr(
        summarize_module.subprocess,
        "run",
        FakeRun(stdout="Spec is updated and waiting for your review - shall we start the plan?"),
    )

    assert run("a reply", PACK).endswith("plan?")


def test_a_plain_summary_is_kept(monkeypatch):
    monkeypatch.setattr(summarize_module.subprocess, "run", FakeRun(stdout="Done, tests pass."))

    assert run("a reply", PACK) == "Done, tests pass."


def test_the_sentinel_survives_markdown_stripping(monkeypatch):
    """strip_markdown eats the underscore, so both spellings must be recognised."""
    monkeypatch.setattr(summarize_module.subprocess, "run", FakeRun(stdout="NOSUMMARY"))

    assert run("a reply", PACK) is None


def test_a_summary_merely_starting_with_no_is_kept(monkeypatch):
    monkeypatch.setattr(
        summarize_module.subprocess, "run", FakeRun(stdout="No tests were run, only docs changed.")
    )

    assert run("a reply", PACK) == "No tests were run, only docs changed."


def test_the_binary_is_found_beside_the_home_directory_when_path_is_empty(monkeypatch, tmp_path):
    """A hook can be run by a desktop app launched from the Dock, with a system-only PATH."""
    local = tmp_path / ".local" / "bin"
    local.mkdir(parents=True)
    (local / "claude").write_text("#!/bin/sh\n")
    monkeypatch.setattr(summarize_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(summarize_module, "CLAUDE_LOCATIONS", (str(local / "claude"),))

    assert summarize_module.claude_binary() == str(local / "claude")


def test_path_wins_when_the_binary_is_on_it(monkeypatch):
    monkeypatch.setattr(summarize_module.shutil, "which", lambda name: "/usr/local/bin/claude")

    assert summarize_module.claude_binary() == "/usr/local/bin/claude"


def test_no_binary_anywhere_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(summarize_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(summarize_module, "CLAUDE_LOCATIONS", (str(tmp_path / "nowhere"),))

    assert summarize_module.claude_binary() is None


def test_a_missing_binary_does_not_reach_subprocess(monkeypatch, tmp_path):
    def explode(*args, **kwargs):
        raise AssertionError("subprocess must not be called without a binary")

    monkeypatch.setattr(summarize_module, "claude_binary", lambda: None)
    monkeypatch.setattr(summarize_module.subprocess, "run", explode)

    assert run("a reply", PACK) is None


def test_the_located_binary_is_the_one_invoked(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module, "claude_binary", lambda: "/found/claude")
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("a reply", PACK)

    assert fake.calls[0][0] == "/found/claude"
