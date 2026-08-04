from cvoice.speech.base import SpeechError, speak_with_fallback


class FakeEngine:
    def __init__(self, name, available=True, fails=False):
        self.name = name
        self._available = available
        self._fails = fails
        self.spoken = []

    def available(self):
        return self._available

    def speak(self, text):
        if self._fails:
            raise SpeechError(f"{self.name} is broken")
        self.spoken.append(text)


def test_first_working_engine_is_used():
    first, second = FakeEngine("edge"), FakeEngine("say")

    used = speak_with_fallback([first, second], "hello")

    assert used == "edge"
    assert first.spoken == ["hello"]
    assert second.spoken == []


def test_unavailable_engine_is_skipped():
    first, second = FakeEngine("edge", available=False), FakeEngine("say")

    used = speak_with_fallback([first, second], "hello")

    assert used == "say"


def test_failing_engine_falls_through_to_the_next():
    first, second = FakeEngine("edge", fails=True), FakeEngine("say")

    used = speak_with_fallback([first, second], "hello")

    assert used == "say"
    assert second.spoken == ["hello"]


def test_all_engines_failing_returns_none():
    engines = [FakeEngine("edge", fails=True), FakeEngine("say", fails=True)]

    assert speak_with_fallback(engines, "hello") is None


def test_failures_are_reported_to_the_callback():
    reported = []
    engines = [FakeEngine("edge", fails=True), FakeEngine("say")]

    speak_with_fallback(engines, "hello", on_error=lambda name, err: reported.append((name, str(err))))

    assert reported[0][0] == "edge"
    assert "broken" in reported[0][1]


def test_success_reports_recovery_for_the_engine_used():
    recovered = []
    engines = [FakeEngine("edge")]

    speak_with_fallback(engines, "hello", on_success=recovered.append)

    assert recovered == ["edge"]


def test_unavailable_engine_is_reported_not_skipped_silently():
    """A neural engine that is merely missing must not degrade the voice in silence."""
    reported = []
    engines = [FakeEngine("edge", available=False), FakeEngine("say")]

    speak_with_fallback(engines, "hello", on_unavailable=reported.append)

    assert reported == ["edge"]


def test_interruption_does_not_fall_through_to_the_next_engine():
    """Pressing "silence now" kills afplay; that must not be read as a broken engine."""
    from cvoice.speech.base import SpeechInterrupted

    class Interrupted(FakeEngine):
        def speak(self, text):
            raise SpeechInterrupted("playback stopped")

    second = FakeEngine("say")

    used = speak_with_fallback([Interrupted("edge"), second], "hello")

    assert used is None
    assert second.spoken == []


def test_interruption_is_not_recorded_as_a_failure():
    from cvoice.speech.base import SpeechInterrupted

    class Interrupted(FakeEngine):
        def speak(self, text):
            raise SpeechInterrupted("playback stopped")

    reported = []

    speak_with_fallback([Interrupted("edge")], "hello", on_error=lambda n, e: reported.append(n))

    assert reported == []
