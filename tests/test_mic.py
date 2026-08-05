import subprocess

import cvoice.mic as mic


class FakeRun:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.kwargs = {}

    def __call__(self, argv, **kwargs):
        self.kwargs = kwargs

        class Result:
            pass

        result = Result()
        result.returncode = self.returncode
        result.stdout = "busy" if self.returncode == 0 else "idle"
        return result


def _helper(tmp_path):
    path = tmp_path / "micbusy"
    path.write_text("#!/bin/sh\n")
    return path


def test_recording_is_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(mic.subprocess, "run", FakeRun(returncode=0))

    assert mic.in_use(_helper(tmp_path)) is True


def test_an_idle_microphone_is_not_muted(tmp_path, monkeypatch):
    monkeypatch.setattr(mic.subprocess, "run", FakeRun(returncode=1))

    assert mic.in_use(_helper(tmp_path)) is False


def test_a_missing_helper_never_mutes(tmp_path):
    """swiftc may be absent on the machine; that must not silence the tool."""
    assert mic.in_use(tmp_path / "not-built") is False
    assert mic.in_use(None) is False


def test_a_hanging_helper_never_mutes(tmp_path, monkeypatch):
    def explode(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd="micbusy", timeout=5)

    monkeypatch.setattr(mic.subprocess, "run", explode)

    assert mic.in_use(_helper(tmp_path)) is False
