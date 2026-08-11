import json

from cvoice.install import EVENTS, install_hooks, remove_hooks


def _settings(tmp_path, payload):
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps(payload))
    return config_dir


def test_hooks_are_added_for_every_event(tmp_path):
    config_dir = _settings(tmp_path, {})

    install_hooks(config_dir, shim="/home/me/.cvoice/bin/cv-hook")

    data = json.loads((config_dir / "settings.json").read_text())
    assert set(EVENTS) <= set(data["hooks"])


def test_existing_hooks_are_preserved(tmp_path):
    config_dir = _settings(
        tmp_path,
        {"hooks": {"Notification": [{"hooks": [{"type": "command", "command": "afplay ping.aiff"}]}]}},
    )

    install_hooks(config_dir, shim="/shim/cv-hook")

    commands = [
        hook["command"]
        for group in json.loads((config_dir / "settings.json").read_text())["hooks"]["Notification"]
        for hook in group["hooks"]
    ]
    assert "afplay ping.aiff" in commands
    assert any("cv-hook" in command for command in commands)


def test_other_settings_are_untouched(tmp_path):
    config_dir = _settings(tmp_path, {"model": "opus", "permissions": {"allow": ["Read"]}})

    install_hooks(config_dir, shim="/shim/cv-hook")

    data = json.loads((config_dir / "settings.json").read_text())
    assert data["model"] == "opus"
    assert data["permissions"] == {"allow": ["Read"]}


def test_installation_is_idempotent(tmp_path):
    config_dir = _settings(tmp_path, {})

    install_hooks(config_dir, shim="/shim/cv-hook")
    install_hooks(config_dir, shim="/shim/cv-hook")

    stop_hooks = json.loads((config_dir / "settings.json").read_text())["hooks"]["Stop"]
    assert sum(len(group["hooks"]) for group in stop_hooks) == 1


def test_a_backup_is_written(tmp_path):
    config_dir = _settings(tmp_path, {"model": "opus"})

    install_hooks(config_dir, shim="/shim/cv-hook")

    backups = list(config_dir.glob("settings.json.backup-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == {"model": "opus"}


def test_no_marker_keys_are_added_to_hook_entries(tmp_path):
    """settings.json is schema-validated, so ownership is recognised by command path."""
    config_dir = _settings(tmp_path, {})

    install_hooks(config_dir, shim="/shim/cv-hook")

    for groups in json.loads((config_dir / "settings.json").read_text())["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                assert set(hook) <= {"type", "command", "timeout", "async"}


def test_question_hook_uses_the_tool_matcher(tmp_path):
    config_dir = _settings(tmp_path, {})

    install_hooks(config_dir, shim="/shim/cv-hook")

    matchers = [
        group.get("matcher")
        for group in json.loads((config_dir / "settings.json").read_text())["hooks"]["PreToolUse"]
    ]
    assert "AskUserQuestion|ExitPlanMode" in matchers


def test_stop_hook_is_async(tmp_path):
    config_dir = _settings(tmp_path, {})

    install_hooks(config_dir, shim="/shim/cv-hook")

    hook = json.loads((config_dir / "settings.json").read_text())["hooks"]["Stop"][0]["hooks"][0]
    assert hook["async"] is True


def test_remove_hooks_removes_only_ours(tmp_path):
    config_dir = _settings(
        tmp_path,
        {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}},
    )
    install_hooks(config_dir, shim="/shim/cv-hook")

    remove_hooks(config_dir)

    commands = [
        hook["command"]
        for group in json.loads((config_dir / "settings.json").read_text())["hooks"].get("Stop", [])
        for hook in group["hooks"]
    ]
    assert commands == ["echo mine"]


def test_missing_settings_file_is_created(tmp_path):
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()

    install_hooks(config_dir, shim="/shim/cv-hook")

    assert (config_dir / "settings.json").exists()


def test_remove_hooks_never_creates_a_missing_settings_file(tmp_path):
    """Uninstalling walks every ~/.claude* directory; most contain nothing of ours."""
    config_dir = tmp_path / ".claude-something-else"
    config_dir.mkdir()

    remove_hooks(config_dir)

    assert not (config_dir / "settings.json").exists()


def test_remove_hooks_leaves_an_unowned_file_byte_identical(tmp_path):
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()
    settings = config_dir / "settings.json"
    original = '{"model":"opus","hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo hi"}]}]}}'
    settings.write_text(original)

    remove_hooks(config_dir)

    assert settings.read_text() == original


def test_a_second_run_leaves_no_extra_backup(tmp_path):
    """Installing twice is normal; a copy of settings.json each time is litter."""
    config_dir = _settings(tmp_path, {"model": "opus"})

    install_hooks(config_dir, shim="/shim/cv-hook")
    install_hooks(config_dir, shim="/shim/cv-hook")

    assert len(list(config_dir.glob("settings.json.backup-*"))) == 1


def test_a_second_run_leaves_the_file_byte_identical(tmp_path):
    config_dir = _settings(tmp_path, {"model": "opus"})
    install_hooks(config_dir, shim="/shim/cv-hook")
    after_first = (config_dir / "settings.json").read_text()

    install_hooks(config_dir, shim="/shim/cv-hook")

    assert (config_dir / "settings.json").read_text() == after_first


from cvoice.codex import read_notify
from cvoice.config import Config, load, save
from cvoice.install import install_codex, remove_codex
from cvoice.state import Paths


def _home(tmp_path):
    paths = Paths(root=tmp_path / "home")
    paths.ensure()
    save(paths, Config())
    return paths


def _codex_config(tmp_path, text='notify = ["/opt/thing", "turn-ended"]\n'):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_the_shim_takes_the_slot(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)

    install_codex(config, paths, shim="/home/me/.cvoice/bin/cv-hook")

    assert read_notify(config) == ["/home/me/.cvoice/bin/cv-hook", "hook", "codex"]


def test_the_displaced_command_is_stored(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)

    install_codex(config, paths, shim="/shim/cv-hook")

    assert load(paths).codex_original_notify == ["/opt/thing", "turn-ended"]


def test_installing_twice_does_not_chain_to_itself(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)

    install_codex(config, paths, shim="/shim/cv-hook")
    install_codex(config, paths, shim="/shim/cv-hook")

    assert load(paths).codex_original_notify == ["/opt/thing", "turn-ended"]
    assert read_notify(config) == ["/shim/cv-hook", "hook", "codex"]


def test_an_empty_slot_is_taken_with_nothing_stored(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path, 'model = "gpt"\n')

    install_codex(config, paths, shim="/shim/cv-hook")

    assert read_notify(config) == ["/shim/cv-hook", "hook", "codex"]
    assert load(paths).codex_original_notify == []


def test_other_codex_settings_survive(tmp_path):
    paths = _home(tmp_path)
    config = _codex_config(
        tmp_path, 'notify = ["/opt/thing"]\n\n[plugins."browser@bundled"]\nenabled = true\n'
    )

    install_codex(config, paths, shim="/shim/cv-hook")

    assert "browser@bundled" in config.read_text()


def test_a_codex_backup_is_written(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)

    install_codex(config, paths, shim="/shim/cv-hook")

    assert len(list(tmp_path.glob("config.toml.backup-*"))) == 1


def test_a_second_run_writes_no_second_backup(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)

    install_codex(config, paths, shim="/shim/cv-hook")
    install_codex(config, paths, shim="/shim/cv-hook")

    assert len(list(tmp_path.glob("config.toml.backup-*"))) == 1


def test_a_missing_codex_is_not_an_error(tmp_path):
    paths = _home(tmp_path)

    assert install_codex(tmp_path / "nowhere.toml", paths, shim="/shim/cv-hook") is False


def test_removal_restores_the_displaced_command(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)
    install_codex(config, paths, shim="/shim/cv-hook")

    remove_codex(config, paths)

    assert read_notify(config) == ["/opt/thing", "turn-ended"]
    assert load(paths).codex_original_notify == []


def test_removal_of_an_empty_original_clears_the_slot(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path, 'model = "gpt"\n')
    install_codex(config, paths, shim="/shim/cv-hook")

    remove_codex(config, paths)

    assert read_notify(config) == []


def test_removal_leaves_someone_elses_slot_alone(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)

    remove_codex(config, paths)

    assert read_notify(config) == ["/opt/thing", "turn-ended"]


def _reclaimed(shim):
    """What Codex writes after taking its slot back: its own client, with whatever it
    displaced preserved as `--previous-notify`."""
    import json as _json

    return [
        "/Applications/Codex.app/SkyComputerUseClient",
        "turn-ended",
        "--previous-notify",
        _json.dumps([shim, "hook", "codex"]),
    ]


def test_a_reclaimed_slot_is_not_stored_as_the_original(tmp_path):
    """Otherwise our chain calls Codex, which calls us, which calls Codex."""
    import json as _json

    paths = _home(tmp_path)
    config = _codex_config(tmp_path)
    install_codex(config, paths, shim="/shim/cv-hook")
    config.write_text(f"notify = {_json.dumps(_reclaimed('/shim/cv-hook'))}\n")

    install_codex(config, paths, shim="/shim/cv-hook")

    assert load(paths).codex_original_notify == ["/opt/thing", "turn-ended"]


def test_a_command_mentioning_our_shim_anywhere_is_recognised():
    from cvoice.install import _is_ours

    assert _is_ours(_reclaimed("/shim/cv-hook")) is True
    assert _is_ours(["/opt/thing", "turn-ended"]) is False
    assert _is_ours([]) is False
