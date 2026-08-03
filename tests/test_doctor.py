import claude_voice.doctor as doctor_module
from claude_voice.config import Config
from claude_voice.doctor import checks, report
from claude_voice.health import record
from claude_voice.state import Paths


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def _all_present(monkeypatch):
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: f"/usr/local/bin/{name}")


def test_missing_binary_is_reported_with_a_remedy(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: None if name == "edge-tts" else "/bin/x")
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])

    results = {check.name: check for check in checks(_paths(tmp_path), Config())}

    assert results["edge-tts"].ok is False
    assert "pip install" in results["edge-tts"].remedy


def test_everything_present_passes(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])

    assert all(check.ok for check in checks(_paths(tmp_path), Config()) if check.name != "focus")


def test_recorded_failures_surface_as_a_failed_check(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    paths = _paths(tmp_path)
    record(paths, "edge-tts", "no network")

    results = {check.name: check for check in checks(paths, Config())}

    assert results["recent failures"].ok is False
    assert "no network" in results["recent failures"].detail


def test_stale_lock_is_reported(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    paths = _paths(tmp_path)
    paths.lock_dir.mkdir()
    (paths.lock_dir / "pid").write_text("0")

    results = {check.name: check for check in checks(paths, Config())}

    assert results["speech lock"].ok is False


def test_focus_suppression_is_reported_not_treated_as_broken(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    monkeypatch.setattr(doctor_module, "focus_active", lambda: True)

    results = {check.name: check for check in checks(_paths(tmp_path), Config())}

    assert results["focus"].ok is False
    assert "Do Not Disturb" in results["focus"].detail


def test_report_returns_zero_when_everything_passes(tmp_path, monkeypatch, capsys):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    monkeypatch.setattr(doctor_module, "focus_active", lambda: False)

    assert report(_paths(tmp_path), Config()) == 0
    assert "OK" in capsys.readouterr().out


def test_report_returns_one_when_a_check_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])

    assert report(_paths(tmp_path), Config()) == 1
