import pytest

import cvoice.doctor as doctor_module
from cvoice.config import Config
from cvoice.doctor import checks, report
from cvoice.health import record
from cvoice.state import Paths


@pytest.fixture(autouse=True)
def _no_real_codex(tmp_path, monkeypatch):
    """The codex check reads CODEX_HOME; a test that does not care about it must not
    accidentally see the developer's own ~/.codex. Tests that do care override this."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "no-codex-by-default"))


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def _all_present(monkeypatch):
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: f"/usr/local/bin/{name}")


def test_missing_binary_is_reported_with_a_remedy(tmp_path, monkeypatch):
    import cvoice.speech.edge as edge_module

    monkeypatch.setattr(edge_module.sys, "executable", str(tmp_path / "nowhere" / "python"))
    monkeypatch.setattr(edge_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: None if name == "edge-tts" else "/bin/x")
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])

    results = {check.name: check for check in checks(_paths(tmp_path), Config())}

    assert results["edge-tts"].ok is False
    assert "pip install" in results["edge-tts"].remedy


def test_everything_present_passes(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])

    # Advisory checks describe the machine, not our install: Focus being on, or the
    # microphone helper not being built.
    assert all(check.ok for check in checks(_paths(tmp_path), Config()) if not check.advisory)


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


def test_focus_is_advisory_and_does_not_fail_the_run(tmp_path, monkeypatch, capsys):
    """Do Not Disturb is a state of the machine. A first run must not look broken."""
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    monkeypatch.setattr(doctor_module, "focus_active", lambda: True)

    code = report(_paths(tmp_path), Config())

    assert code == 0
    assert "WARN" in capsys.readouterr().out


def test_a_real_fault_still_fails_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    monkeypatch.setattr(doctor_module, "focus_active", lambda: False)

    assert report(_paths(tmp_path), Config()) == 1


def _codex(tmp_path, notify):
    codex_home = tmp_path / "codex"
    codex_home.mkdir(exist_ok=True)
    (codex_home / "config.toml").write_text(f"notify = {notify}\n")
    return codex_home


def test_an_installed_codex_hook_passes(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    monkeypatch.setenv("CODEX_HOME", str(_codex(tmp_path, '["/x/cv-hook", "hook", "codex"]')))

    results = {check.name: check for check in checks(_paths(tmp_path), Config())}

    assert results["codex"].ok is True


def test_a_displaced_codex_hook_is_reported(tmp_path, monkeypatch):
    """Codex rewrites its own config, so our slot can be taken back at any time."""
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    monkeypatch.setenv("CODEX_HOME", str(_codex(tmp_path, '["/opt/other"]')))

    results = {check.name: check for check in checks(_paths(tmp_path), Config())}

    assert results["codex"].ok is False
    assert "install.sh" in results["codex"].remedy


def test_an_absent_codex_is_not_reported_at_all(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nowhere"))

    assert "codex" not in {check.name for check in checks(_paths(tmp_path), Config())}


def test_a_slot_reclaimed_by_codex_still_counts_as_installed(tmp_path, monkeypatch):
    """Codex takes the slot back but keeps us in --previous-notify, so we still run."""
    import json as _json

    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    reclaimed = _json.dumps(
        ["/Applications/Codex.app/Client", "turn-ended", "--previous-notify",
         _json.dumps(["/x/cv-hook", "hook", "codex"])]
    )
    monkeypatch.setenv("CODEX_HOME", str(_codex(tmp_path, reclaimed)))

    results = {check.name: check for check in checks(_paths(tmp_path), Config())}

    assert results["codex"].ok is True
