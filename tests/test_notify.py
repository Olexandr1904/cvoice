from urllib.parse import unquote, urlsplit

import pytest

import cvoice.notify.macos as notify_module
from cvoice.notify.macos import NotifyError, send, terminal_bundle_id


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


@pytest.fixture(autouse=True)
def no_swiftbar(monkeypatch):
    """The real machine has SwiftBar; tests opt in to it explicitly."""
    monkeypatch.setattr(notify_module, "swiftbar_plugin_installed", lambda: False, raising=False)


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


class FailingFirst(FakeRun):
    """The first channel fails the way terminal-notifier 3.x does without permission."""

    def __call__(self, argv, **kwargs):
        result = super().__call__(argv, **kwargs)
        if len(self.calls) == 1:
            result.returncode = 3
            result.stderr = "Notifications are not allowed for this application"
        return result


def _query(url):
    """Decode the query the way SwiftBar does: percent escapes only, "+" left alone."""
    pairs = [part.split("=", 1) for part in urlsplit(url).query.split("&")]
    return [(unquote(key), unquote(value)) for key, value in pairs]


def _swiftbar_params(line):
    """Python port of SwiftBar's MenuLineParameters.getParams."""
    params, pos, end = {}, 0, len(line)
    while pos < end:
        while pos < end and line[pos] in " \t":
            pos += 1
        if pos >= end:
            break
        start = pos
        while pos < end and line[pos] != "=":
            pos += 1
        if pos >= end:
            break
        key = line[start:pos].strip(" ").lower()
        pos += 1
        while pos < end and line[pos] in " \t":
            pos += 1
        value = ""
        if pos < end and line[pos] in "\"'":
            quote, escaped = line[pos], False
            pos += 1
            while pos < end:
                char = line[pos]
                if escaped:
                    value += "\\" + char
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    pos += 1
                    break
                else:
                    value += char
                pos += 1
        else:
            start = pos
            while pos < end and line[pos] not in " \t":
                pos += 1
            value = line[start:pos]
        params[key] = value
    return params


def _click_action(query):
    """What SwiftBar's notify handler would run on click, for one parameter order.

    It rebuilds the query as `key=value` pairs, quoting a value only when it contains a
    space and escaping nothing inside it, then parses that line for bash=/href=.
    """
    line = " ".join(f"{key}=" + (f"'{value}'" if " " in value else value) for key, value in query)
    return _swiftbar_params(line)


def _swiftbar_url(run):
    argv = run.calls[0]
    assert argv[:2] == ["open", "-g"]
    assert argv[2].startswith("swiftbar://notify?")
    return argv[2]


def test_prefers_swiftbar_when_its_plugin_is_installed(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(notify_module, "swiftbar_plugin_installed", lambda: True, raising=False)
    monkeypatch.setattr(notify_module.shutil, "which", lambda name: "/usr/local/bin/" + name)
    monkeypatch.setattr(notify_module.subprocess, "run", run)

    send("my-project", "Готово, усе зелене", group="g1")

    query = dict(_query(_swiftbar_url(run)))
    assert query["plugin"] == "cvoice"
    assert query["title"] == "my-project"
    assert query["body"] == "Готово, усе зелене"
    assert query["silent"] == "true"
    assert len(run.calls) == 1


def test_swiftbar_click_returns_to_the_terminal(monkeypatch):
    run = FakeRun()
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")
    monkeypatch.setattr(notify_module, "swiftbar_plugin_installed", lambda: True, raising=False)
    monkeypatch.setattr(notify_module.subprocess, "run", run)

    send("my-project", "Готово, усе зелене", group="g1")

    action = _click_action(_query(_swiftbar_url(run)))
    assert action["bash"] == "/usr/bin/open"
    assert (action["param1"], action["param2"]) == ("-b", "com.googlecode.iterm2")
    assert action["terminal"] == "false"


@pytest.mark.parametrize("term_program", ["iTerm.app", "something-else"])
def test_message_text_cannot_become_a_swiftbar_click_action(monkeypatch, term_program):
    """An apostrophe ends SwiftBar's quoting early and a tab skips it; either would let
    the rest of a summary be read as parameters, and bash= runs on click."""
    run = FakeRun()
    monkeypatch.setenv("TERM_PROGRAM", term_program)
    monkeypatch.setattr(notify_module, "swiftbar_plugin_installed", lambda: True, raising=False)
    monkeypatch.setattr(notify_module.subprocess, "run", run)
    hostile = "Я з' bash=/bin/sh param1=-c\tbash=/usr/bin/touch href=https://example.com x\\"

    send(f"проєкт' bash=/bin/rm", hostile, group="g1")

    query = _query(_swiftbar_url(run))
    for order in (query, list(reversed(query))):
        action = _click_action(order)
        assert "href" not in action
        assert action.get("bash") in (None, "/usr/bin/open")
        assert action.get("param1") in (None, "-b")


def test_plus_signs_survive_swiftbar(monkeypatch):
    """SwiftBar turns "+" in a title or body into a space."""
    run = FakeRun()
    monkeypatch.setattr(notify_module, "swiftbar_plugin_installed", lambda: True, raising=False)
    monkeypatch.setattr(notify_module.subprocess, "run", run)

    send("C++", "1+1", group="g1")

    query = dict(_query(_swiftbar_url(run)))
    assert "+" not in query["title"] + query["body"]
    assert query["body"].replace("＋", "+") == "1+1"


def test_a_failing_channel_falls_through_to_the_next(monkeypatch):
    run = FailingFirst()
    monkeypatch.setattr(notify_module.shutil, "which", lambda name: "/usr/local/bin/" + name)
    monkeypatch.setattr(notify_module.subprocess, "run", run)

    send("Title", "Body", group="g1")

    assert [argv[0] for argv in run.calls] == ["terminal-notifier", "osascript"]


def test_raises_with_every_reason_when_all_channels_fail(monkeypatch):
    monkeypatch.setattr(notify_module.shutil, "which", lambda name: "/usr/local/bin/" + name)
    monkeypatch.setattr(notify_module.subprocess, "run", FakeRun(returncode=1))

    with pytest.raises(NotifyError) as raised:
        send("Title", "Body", group="g1")

    assert "terminal-notifier" in str(raised.value) and "osascript" in str(raised.value)


def test_swiftbar_counts_only_when_the_cvoice_plugin_is_in_its_folder(monkeypatch, tmp_path):
    monkeypatch.undo()
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    prefs = tmp_path / "com.ameba.SwiftBar.plist"
    import plistlib

    prefs.write_bytes(plistlib.dumps({"PluginDirectory": str(plugins)}))
    monkeypatch.setattr(notify_module, "SWIFTBAR_PREFS", prefs, raising=False)

    assert notify_module.swiftbar_plugin_installed() is False
    (plugins / "cvoice.10s.sh").write_text("#!/bin/sh\n")
    assert notify_module.swiftbar_plugin_installed() is True


def test_no_swiftbar_preferences_means_no_swiftbar(monkeypatch, tmp_path):
    monkeypatch.undo()
    monkeypatch.setattr(notify_module, "SWIFTBAR_PREFS", tmp_path / "missing.plist", raising=False)

    assert notify_module.swiftbar_plugin_installed() is False

