import json

from claude_voice.install import EVENTS, install_hooks, remove_hooks


def _settings(tmp_path, payload):
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps(payload))
    return config_dir


def test_hooks_are_added_for_every_event(tmp_path):
    config_dir = _settings(tmp_path, {})

    install_hooks(config_dir, shim="/home/me/.claude-voice/bin/cv-hook")

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
