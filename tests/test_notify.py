import claude_voice.notify.macos as notify_module
from claude_voice.notify.macos import NotifyError, send, terminal_bundle_id


class FakeRun:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)

        class Result:
            pass

        result = Result()
        result.returncode = self.returncode
        result.stderr = "notifier failed"
        return result


def test_uses_terminal_notifier_when_present(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(notify_module.shutil, "which", lambda name: "/usr/local/bin/terminal-notifier")
    monkeypatch.setattr(notify_module.subprocess, "run", run)

    send("Title", "Body", group="g1")

    argv = run.calls[0]
    assert argv[0] == "terminal-notifier"
    assert "Title" in argv and "Body" in argv and "g1" in argv


def test_no_sound_flag_is_never_passed(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(notify_module.shutil, "which", lambda name: "/usr/local/bin/terminal-notifier")
    monkeypatch.setattr(notify_module.subprocess, "run", run)

    send("Title", "Body", group="g1")

    assert "-sound" not in run.calls[0]


def test_falls_back_to_osascript(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(notify_module.shutil, "which", lambda name: None if name == "terminal-notifier" else "/usr/bin/osascript")
    monkeypatch.setattr(notify_module.subprocess, "run", run)

    send("Title", "Body", group="g1")

    assert run.calls[0][0] == "osascript"


def test_raises_when_nothing_can_deliver(monkeypatch):
    monkeypatch.setattr(notify_module.shutil, "which", lambda name: None)

    try:
        send("Title", "Body", group="g1")
    except NotifyError:
        pass
    else:
        raise AssertionError("expected NotifyError")


def test_known_terminal_maps_to_bundle_id(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")

    assert terminal_bundle_id() == "com.googlecode.iterm2"


def test_unknown_terminal_maps_to_none(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "something-else")

    assert terminal_bundle_id() is None
