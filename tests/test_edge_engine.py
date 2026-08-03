import cvoice.speech.edge as edge_module
from cvoice.speech.base import SpeechError
from cvoice.speech.edge import EdgeEngine


class FakeRunner:
    """Stands in for both edge-tts and afplay. No network is ever touched in tests."""

    def __init__(self, synth_ok=True, play_ok=True):
        self.synth_ok = synth_ok
        self.play_ok = play_ok
        self.synth_calls = 0
        self.played = []

    def __call__(self, argv, **kwargs):
        class Result:
            pass

        result = Result()
        result.stderr = ""
        if argv[0] == "edge-tts":
            self.synth_calls += 1
            result.returncode = 0 if self.synth_ok else 1
            if self.synth_ok:
                target = argv[argv.index("--write-media") + 1]
                with open(target, "wb") as handle:
                    handle.write(b"fake mp3")
            else:
                result.stderr = "network unreachable"
        else:
            self.played.append(argv[-1])
            result.returncode = 0 if self.play_ok else 1
        return result


def _engine(tmp_path, voice="uk-UA-PolinaNeural"):
    return EdgeEngine(voice=voice, rate="+0%", cache_dir=tmp_path / "cache")


def test_available_requires_the_edge_tts_binary(monkeypatch, tmp_path):
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
