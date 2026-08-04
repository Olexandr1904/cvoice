import json

import cvoice.langgen as langgen
from cvoice.i18n import REQUIRED_PHRASES, load


class FakeRun:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.kwargs = {}

    def __call__(self, argv, **kwargs):
        self.kwargs = kwargs

        class Result:
            pass

        result = Result()
        result.returncode = self.returncode
        result.stdout = self.stdout
        result.stderr = ""
        return result


def _answer(**overrides):
    english = load("en")
    data = {
        "code": "pl",
        "name": "Polish",
        "script": "latin",
        "phrases": {key: f"PL {english.phrases[key]}" for key in REQUIRED_PHRASES},
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _no_voices(monkeypatch):
    monkeypatch.setattr(langgen, "voices_for", lambda code: ("", ""))


def test_builds_a_pack_from_the_models_answer(monkeypatch):
    monkeypatch.setattr(langgen.subprocess, "run", FakeRun(_answer()))
    _no_voices(monkeypatch)

    pack = langgen.build("Polish")

    assert pack["language"] == "pl"
    assert pack["name"] == "Polish"
    assert all(key in pack["phrases"] for key in REQUIRED_PHRASES)
    assert "Polish" in pack["summary_system"]


def test_json_wrapped_in_prose_is_still_read(monkeypatch):
    monkeypatch.setattr(langgen.subprocess, "run", FakeRun(f"Sure!\n```json\n{_answer()}\n```"))
    _no_voices(monkeypatch)

    assert langgen.build("Polish")["language"] == "pl"


def test_an_unusable_code_gives_up(monkeypatch):
    monkeypatch.setattr(langgen.subprocess, "run", FakeRun(_answer(code="not a code")))
    _no_voices(monkeypatch)

    assert langgen.build("Nonsense") is None


def test_a_failed_call_gives_up(monkeypatch):
    monkeypatch.setattr(langgen.subprocess, "run", FakeRun("", returncode=1))
    _no_voices(monkeypatch)

    assert langgen.build("Polish") is None


def test_missing_translations_fall_back_to_english(monkeypatch):
    monkeypatch.setattr(langgen.subprocess, "run", FakeRun(_answer(phrases={"waiting": "PL"})))
    _no_voices(monkeypatch)

    pack = langgen.build("Polish")

    assert pack["phrases"]["waiting"] == load("en").phrases["waiting"]


def test_a_non_latin_script_forbids_latin_words(monkeypatch):
    monkeypatch.setattr(langgen.subprocess, "run", FakeRun(_answer(code="el", script="non-latin")))
    _no_voices(monkeypatch)

    assert langgen.build("Greek")["detect"]["forbids"] == "[A-Za-z]{3,}"


def test_stdin_is_closed_for_the_generator(monkeypatch):
    import subprocess as real_subprocess

    fake = FakeRun(_answer())
    monkeypatch.setattr(langgen.subprocess, "run", fake)
    _no_voices(monkeypatch)

    langgen.build("Polish")

    assert fake.kwargs["stdin"] is real_subprocess.DEVNULL


def test_edge_voice_is_matched_by_locale(monkeypatch):
    monkeypatch.setattr(langgen.shutil, "which", lambda name: "/usr/local/bin/edge-tts")
    monkeypatch.setattr(
        langgen.subprocess,
        "run",
        FakeRun("en-US-AriaNeural  Female  General\npl-PL-ZofiaNeural  Female  General\n"),
    )

    assert langgen.edge_voice_for("pl") == "pl-PL-ZofiaNeural"


def test_the_written_pack_can_be_loaded_back(tmp_path, monkeypatch):
    monkeypatch.setattr(langgen.subprocess, "run", FakeRun(_answer()))
    _no_voices(monkeypatch)
    monkeypatch.setenv("CVOICE_HOME", str(tmp_path))

    code = langgen.write(langgen.build("Polish"), tmp_path / "langs")

    pack = load(code)
    assert pack.language == "pl"
    assert pack.phrase("waiting")
