import cvoice.speech.edge as edge_module
from cvoice.speech.base import SpeechError
from cvoice.speech.edge import EdgeEngine


class FakeRunner:
    """Stands in for both edge-tts and afplay. No network is ever touched in tests."""

    def __init__(self, synth_ok=True, play_ok=True, synth_stderr="network unreachable"):
        self.synth_ok = synth_ok
        self.play_ok = play_ok
        self.synth_stderr = synth_stderr
        self.synth_calls = 0
        self.played = []

    def __call__(self, argv, **kwargs):
        class Result:
            pass

        result = Result()
        result.stderr = ""
        if "edge-tts" in argv[0]:
            self.synth_calls += 1
            result.returncode = 0 if self.synth_ok else 1
            if self.synth_ok:
                target = argv[argv.index("--write-media") + 1]
                with open(target, "wb") as handle:
                    handle.write(b"fake mp3")
            else:
                result.stderr = self.synth_stderr
        else:
            self.played.append(argv[-1])
            result.returncode = 0 if self.play_ok else 1
        return result


def _engine(tmp_path, voice="uk-UA-PolinaNeural"):
    return EdgeEngine(voice=voice, rate="+0%", cache_dir=tmp_path / "cache")


def test_available_requires_the_edge_tts_binary(monkeypatch, tmp_path):
    # Both lookups must miss: beside the interpreter and on PATH.
    monkeypatch.setattr(edge_module.sys, "executable", str(tmp_path / "nowhere" / "python"))
    monkeypatch.setattr(edge_module.shutil, "which", lambda name: None)

    assert _engine(tmp_path).available() is False


def test_speak_synthesises_then_plays(monkeypatch, tmp_path):
    runner = FakeRunner()
    monkeypatch.setattr(edge_module.subprocess, "run", runner)

    _engine(tmp_path).speak("Готово")

    assert runner.synth_calls == 1
    assert runner.played and runner.played[0].endswith(".mp3")


def test_second_identical_utterance_reuses_the_cache(monkeypatch, tmp_path):
    runner = FakeRunner()
    monkeypatch.setattr(edge_module.subprocess, "run", runner)
    engine = _engine(tmp_path)

    engine.speak("Готово")
    engine.speak("Готово")

    assert runner.synth_calls == 1
    assert len(runner.played) == 2


def test_different_voice_is_cached_separately(monkeypatch, tmp_path):
    runner = FakeRunner()
    monkeypatch.setattr(edge_module.subprocess, "run", runner)

    _engine(tmp_path, voice="a").speak("Готово")
    _engine(tmp_path, voice="b").speak("Готово")

    assert runner.synth_calls == 2


def test_synthesis_failure_raises_and_leaves_no_partial_file(monkeypatch, tmp_path):
    monkeypatch.setattr(edge_module.subprocess, "run", FakeRunner(synth_ok=False))
    engine = _engine(tmp_path)

    try:
        engine.speak("Готово")
    except SpeechError as error:
        assert "network unreachable" in str(error)
    else:
        raise AssertionError("expected SpeechError")

    assert list((tmp_path / "cache").glob("*")) == []


def test_synthesis_failure_reports_the_exception_not_the_traceback_head(monkeypatch, tmp_path):
    """health.json keeps 200 characters, and the head of a traceback names no cause."""
    traceback = (
        "Traceback (most recent call last):\n"
        '  File "/venv/lib/python3.10/site-packages/edge_tts/communicate.py", line 588, in stream\n'
        "    async for message in self.__stream():\n"
        "aiohttp.client_exceptions.WSServerHandshakeError: 403, message='Invalid response status'\n"
    )
    monkeypatch.setattr(
        edge_module.subprocess, "run", FakeRunner(synth_ok=False, synth_stderr=traceback)
    )

    try:
        _engine(tmp_path).speak("Готово")
    except SpeechError as error:
        assert str(error) == (
            "aiohttp.client_exceptions.WSServerHandshakeError: 403, message='Invalid response status'"
        )
    else:
        raise AssertionError("expected SpeechError")


def test_binary_is_found_next_to_the_interpreter_when_path_is_empty(monkeypatch, tmp_path):
    """Hooks and the menu bar run us with a thin PATH; the venv is never on it."""
    fake_venv_bin = tmp_path / "venv" / "bin"
    fake_venv_bin.mkdir(parents=True)
    (fake_venv_bin / "edge-tts").write_text("#!/bin/sh\n")
    monkeypatch.setattr(edge_module.sys, "executable", str(fake_venv_bin / "python"))
    monkeypatch.setattr(edge_module.shutil, "which", lambda name: None)

    assert _engine(tmp_path).available() is True
    assert edge_module.edge_binary() == str(fake_venv_bin / "edge-tts")


def test_falls_back_to_path_when_not_beside_the_interpreter(monkeypatch, tmp_path):
    monkeypatch.setattr(edge_module.sys, "executable", str(tmp_path / "nowhere" / "python"))
    monkeypatch.setattr(edge_module.shutil, "which", lambda name: "/usr/local/bin/edge-tts")

    assert edge_module.edge_binary() == "/usr/local/bin/edge-tts"


def test_unavailable_when_it_exists_nowhere(monkeypatch, tmp_path):
    monkeypatch.setattr(edge_module.sys, "executable", str(tmp_path / "nowhere" / "python"))
    monkeypatch.setattr(edge_module.shutil, "which", lambda name: None)

    assert _engine(tmp_path).available() is False


def test_killed_playback_raises_interrupted_not_failure(monkeypatch, tmp_path):
    from cvoice.speech.base import SpeechInterrupted

    class KilledPlayer(FakeRunner):
        def __call__(self, argv, **kwargs):
            result = super().__call__(argv, **kwargs)
            if "afplay" in argv[0]:
                result.returncode = -15  # SIGTERM, as pkill sends
            return result

    monkeypatch.setattr(edge_module.subprocess, "run", KilledPlayer())

    try:
        _engine(tmp_path).speak("Готово")
    except SpeechInterrupted:
        pass
    else:
        raise AssertionError("expected SpeechInterrupted")
