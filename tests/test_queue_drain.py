import threading
import time

from cvoice.queue import Item, drain, enqueue, pending
from cvoice.state import Paths


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


class RecordingSpeaker:
    """Records the interval each utterance occupied, so overlap can be detected."""

    def __init__(self, delay=0.02):
        self.delay = delay
        self.spoken = []
        self.intervals = []
        self._guard = threading.Lock()

    def __call__(self, text, item):
        start = time.monotonic()
        time.sleep(self.delay)
        end = time.monotonic()
        with self._guard:
            self.spoken.append(text)
            self.intervals.append((start, end))


def test_drain_speaks_everything_in_order(tmp_path):
    paths = _paths(tmp_path)
    speaker = RecordingSpeaker(delay=0)
    enqueue(paths, Item(priority=1, label="app", session="s", text="one"))
    enqueue(paths, Item(priority=1, label="app", session="s", text="two"))

    spoken = drain(paths, speaker)

    assert spoken == 2
    assert speaker.spoken == ["one", "two"]
    assert pending(paths) == []


def test_drain_returns_zero_when_lock_is_held(tmp_path):
    from cvoice.queue import lock

    paths = _paths(tmp_path)
    enqueue(paths, Item(priority=1, label="app", session="s", text="one"))
    speaker = RecordingSpeaker(delay=0)

    with lock(paths):
        assert drain(paths, speaker) == 0

    assert len(pending(paths)) == 1


def test_pause_drops_queued_items(tmp_path):
    paths = _paths(tmp_path)
    speaker = RecordingSpeaker(delay=0)
    enqueue(paths, Item(priority=1, label="app", session="s", text="stale"))

    drain(paths, speaker, is_paused=lambda: True)

    assert speaker.spoken == []
    assert pending(paths) == []


def test_forced_item_is_spoken_even_while_paused(tmp_path):
    paths = _paths(tmp_path)
    speaker = RecordingSpeaker(delay=0)
    enqueue(paths, Item(priority=0, label="app", session="s", text="replay", flags="force"))

    drain(paths, speaker, is_paused=lambda: True)

    assert speaker.spoken == ["replay"]


def test_speaker_failure_does_not_block_the_rest(tmp_path):
    paths = _paths(tmp_path)
    calls = []

    def flaky(text, item):
        calls.append(text)
        if text == "bad":
            raise RuntimeError("engine down")

    enqueue(paths, Item(priority=1, label="app", session="s", text="bad"))
    enqueue(paths, Item(priority=1, label="app", session="s", text="good"))

    drain(paths, flaky)

    assert calls == ["bad", "good"]
    assert pending(paths) == []


def test_item_queued_during_drain_is_still_spoken(tmp_path):
    paths = _paths(tmp_path)
    spoken = []

    def speaker(text, item):
        spoken.append(text)
        if text == "first":
            enqueue(paths, Item(priority=1, label="app", session="s", text="late"))

    enqueue(paths, Item(priority=1, label="app", session="s", text="first"))

    drain(paths, speaker)

    assert spoken == ["first", "late"]


def test_only_one_utterance_at_a_time_across_threads(tmp_path):
    paths = _paths(tmp_path)
    speaker = RecordingSpeaker(delay=0.02)
    for index in range(6):
        enqueue(paths, Item(priority=1, label="app", session="s", text=f"item {index}"))

    threads = [threading.Thread(target=drain, args=(paths, speaker)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(speaker.spoken) == 6
    ordered = sorted(speaker.intervals)
    for (_, first_end), (second_start, _) in zip(ordered, ordered[1:]):
        assert first_end <= second_start + 1e-6, "two utterances overlapped"


def test_a_forced_item_is_still_silenced_by_a_hard_mute(tmp_path):
    """Someone is recording: speaking over a call is wrong even on an explicit replay."""
    paths = _paths(tmp_path)
    speaker = RecordingSpeaker(delay=0)
    enqueue(paths, Item(priority=0, label="app", session="s", text="replay", flags="force"))

    drain(paths, speaker, is_paused=lambda: False, is_hard_muted=lambda: True)

    assert speaker.spoken == []
    assert pending(paths) == []


def test_a_forced_item_still_overrides_a_snooze(tmp_path):
    paths = _paths(tmp_path)
    speaker = RecordingSpeaker(delay=0)
    enqueue(paths, Item(priority=0, label="app", session="s", text="replay", flags="force"))

    drain(paths, speaker, is_paused=lambda: True, is_hard_muted=lambda: False)

    assert speaker.spoken == ["replay"]
