from cvoice.state import Paths


def test_paths_derive_from_root(tmp_path):
    paths = Paths(root=tmp_path)

    assert paths.config_file == tmp_path / "config.toml"
    assert paths.queue_dir == tmp_path / "queue"
    assert paths.history_file == tmp_path / "history.jsonl"


def test_ensure_creates_directories(tmp_path):
    paths = Paths(root=tmp_path / "home")
    paths.ensure()

    assert paths.queue_dir.is_dir()
    assert paths.cache_dir.is_dir()
    assert paths.scopes_dir.is_dir()
    assert paths.state_dir.is_dir()


def test_default_root_is_dot_cvoice(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CVOICE_HOME", raising=False)

    assert Paths.default().root == tmp_path / ".cvoice"


def test_env_var_overrides_default_root(monkeypatch, tmp_path):
    monkeypatch.setenv("CVOICE_HOME", str(tmp_path / "custom"))

    assert Paths.default().root == tmp_path / "custom"


import time

from cvoice.state import clear_snooze, set_snooze, snoozed_until


def test_no_snooze_by_default(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()

    assert snoozed_until(paths) is None


def test_set_snooze_returns_future_timestamp(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()

    until = set_snooze(paths, minutes=30)

    assert until > time.time() + 29 * 60
    assert snoozed_until(paths) == until


def test_expired_snooze_reads_as_none_and_removes_file(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    paths.snooze_file.write_text(str(time.time() - 1))

    assert snoozed_until(paths) is None
    assert not paths.snooze_file.exists()


def test_clear_snooze(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    set_snooze(paths, minutes=5)

    clear_snooze(paths)

    assert snoozed_until(paths) is None
