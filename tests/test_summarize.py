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


def test_reply_is_embedded_in_the_prompt_not_piped(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("REPLY-MARKER", PACK)

    prompt = fake.calls[0][-1]
    assert "REPLY-MARKER" in prompt
    assert "BEGIN REPLY" in prompt


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


def test_haiku_model_is_requested(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("a reply", PACK)

    argv = fake.calls[0]
    assert argv[argv.index("--model") + 1] == "haiku"


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
