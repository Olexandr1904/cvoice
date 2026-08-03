from claude_voice.health import clear, failures, record
from claude_voice.state import Paths


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def test_no_failures_initially(tmp_path):
    assert failures(_paths(tmp_path)) == []


def test_record_stores_component_and_reason(tmp_path):
    paths = _paths(tmp_path)

    record(paths, "edge-tts", "no network")

    stored = failures(paths)
    assert len(stored) == 1
    assert stored[0].component == "edge-tts"
    assert stored[0].error == "no network"
    assert stored[0].ts > 0


def test_repeated_failure_updates_rather_than_duplicates(tmp_path):
    paths = _paths(tmp_path)

    record(paths, "edge-tts", "no network")
    record(paths, "edge-tts", "timeout")

    stored = failures(paths)
    assert len(stored) == 1
    assert stored[0].error == "timeout"


def test_different_components_are_kept_separately(tmp_path):
    paths = _paths(tmp_path)

    record(paths, "edge-tts", "no network")
    record(paths, "terminal-notifier", "missing")

    assert {failure.component for failure in failures(paths)} == {"edge-tts", "terminal-notifier"}


def test_clear_removes_everything(tmp_path):
    paths = _paths(tmp_path)
    record(paths, "edge-tts", "no network")

    clear(paths)

    assert failures(paths) == []


def test_clear_one_component(tmp_path):
    paths = _paths(tmp_path)
    record(paths, "edge-tts", "no network")
    record(paths, "say", "voice missing")

    clear(paths, component="edge-tts")

    assert [failure.component for failure in failures(paths)] == ["say"]


def test_corrupt_health_file_reads_as_empty(tmp_path):
    paths = _paths(tmp_path)
    paths.health_file.write_text("{not json")

    assert failures(paths) == []
