import claude_voice.speech.macos_say as macos_say
from claude_voice.speech.base import SpeechError
from claude_voice.speech.macos_say import SayEngine
from claude_voice.speech.translit import Table

TABLE = Table(terms={"manager": "менеджер"}, digraphs=[], letters={"a": "а", "s": "с", "y": "й", "n": "н", "c": "к"})


class FakeRun:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)

        class Result:
            pass

        result = Result()
        result.returncode = self.returncode
        result.stderr = self.stderr
        return result


def test_available_requires_the_say_binary(monkeypatch):
    monkeypatch.setattr(macos_say.shutil, "which", lambda name: None)

    assert SayEngine(voice="Lesya", rate=180).available() is False


def test_speak_passes_voice_and_rate(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(macos_say.subprocess, "run", run)

    SayEngine(voice="Lesya", rate=190).speak("Готово")

    assert run.calls[0][:5] == ["say", "-v", "Lesya", "-r", "190"]
    assert run.calls[0][-1] == "Готово"


def test_latin_is_transliterated_before_speaking(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(macos_say.subprocess, "run", run)

    SayEngine(voice="Lesya", rate=180, table=TABLE).speak("Виправив SyncManager")

    assert "SyncManager" not in run.calls[0][-1]


def test_text_without_latin_is_untouched(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(macos_say.subprocess, "run", run)

    SayEngine(voice="Lesya", rate=180, table=TABLE).speak("Готово, тести зелені")

    assert run.calls[0][-1] == "Готово, тести зелені"


def test_non_zero_exit_raises_speech_error(monkeypatch):
    monkeypatch.setattr(macos_say.subprocess, "run", FakeRun(returncode=1, stderr="voice not found"))

    try:
        SayEngine(voice="Nope", rate=180).speak("hello")
    except SpeechError as error:
        assert "voice not found" in str(error)
    else:
        raise AssertionError("expected SpeechError")
