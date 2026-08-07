"""Wiring the hooks into Claude Code's settings.json.

Ownership is recognised by the command path rather than an injected marker key, because
settings.json is validated against a published schema and unknown keys must not appear
there. That also makes installation naturally idempotent.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Dict, List

SHIM_MARKER = "cv-hook"

# event -> (matcher or None, hook subcommand, extra keys)
EVENTS: Dict[str, tuple] = {
    "PreToolUse": ("AskUserQuestion|ExitPlanMode", "question", {"timeout": 10}),
    "Notification": (None, "notification", {"timeout": 10}),
    "Stop": (None, "stop", {"async": True, "timeout": 120}),
    "UserPromptSubmit": (None, "prompt-submit", {"timeout": 10}),
}


def _load(settings: Path) -> dict:
    try:
        return json.loads(settings.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(settings: Path, data: dict) -> None:
    settings.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _backup(settings: Path) -> None:
    """Copy `settings` next to itself, named `<original name>.backup-<timestamp>`.

    Built with `with_name` rather than `with_suffix` so this works for any extension -
    `settings.json` as much as Codex's `config.toml`.
    """
    if settings.exists():
        backup = settings.with_name(f"{settings.name}.backup-{time.strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(settings, backup)


def _owned(command: str) -> bool:
    return SHIM_MARKER in command


def install_hooks(config_dir: Path, shim: str) -> None:
    """Add our hooks, and touch nothing if they are already there.

    The backup is taken only when something is actually going to change: installing is
    idempotent, and a copy of settings.json on every run just litters the user's config
    directory.
    """
    settings = Path(config_dir) / "settings.json"
    data = _load(settings)
    hooks = data.setdefault("hooks", {})
    added = False

    for event, (matcher, subcommand, extra) in EVENTS.items():
        groups: List[dict] = hooks.setdefault(event, [])
        already = any(_owned(hook.get("command", "")) for group in groups for hook in group.get("hooks", []))
        if already:
            continue
        entry = {"type": "command", "command": f"{shim} hook {subcommand}", **extra}
        target = None
        for group in groups:
            if group.get("matcher") == matcher:
                target = group
                break
        if target is None:
            target = {"hooks": []} if matcher is None else {"matcher": matcher, "hooks": []}
            groups.append(target)
        target.setdefault("hooks", []).append(entry)
        added = True

    if not added and settings.exists():
        return
    _backup(settings)
    _save(settings, data)


def remove_hooks(config_dir: Path) -> None:
    """Remove only our own hook entries, and only if there are any.

    This must never write to a settings.json it does not own something in. Uninstalling
    walks every ~/.claude* directory, most of which belong to unrelated tools or other
    Claude installations: rewriting them would reformat files we were never asked to
    touch, and writing to a directory with no settings.json would create one from
    nothing.
    """
    settings = Path(config_dir) / "settings.json"
    if not settings.exists():
        return

    data = _load(settings)
    hooks = data.get("hooks", {})
    removed = False
    for event, groups in list(hooks.items()):
        for group in groups:
            kept = [hook for hook in group.get("hooks", []) if not _owned(hook.get("command", ""))]
            if len(kept) != len(group.get("hooks", [])):
                removed = True
            group["hooks"] = kept
        hooks[event] = [group for group in groups if group.get("hooks")]
        if not hooks[event]:
            del hooks[event]

    if removed:
        _save(settings, data)


from . import codex as codex_files
from . import config as config_module
from .state import Paths


def _is_ours(command: List[str]) -> bool:
    return bool(command) and SHIM_MARKER in command[0]


def install_codex(codex_config: Path, paths: Paths, shim: str) -> bool:
    """Take Codex's notify slot, remembering whatever was in it. Returns False when Codex
    is not installed.

    The displaced command is stored in our own config, never in Codex's: that file is
    rewritten by the app itself, so recovering the original must not depend on it.
    """
    codex_config = Path(codex_config)
    if not codex_config.exists():
        return False

    current = codex_files.read_notify(codex_config)
    ours = [shim, "hook", "codex"]
    if current == ours:
        return True  # already installed; installing twice must not chain to ourselves

    config = config_module.load(paths)
    if not _is_ours(current):
        config.codex_original_notify = current
        config_module.save(paths, config)

    _backup(codex_config)
    codex_files.write_notify(codex_config, ours)
    return True


def remove_codex(codex_config: Path, paths: Paths) -> bool:
    """Put back whatever we displaced, and forget it."""
    codex_config = Path(codex_config)
    if not codex_config.exists():
        return False
    if not _is_ours(codex_files.read_notify(codex_config)):
        return False  # not ours to restore

    config = config_module.load(paths)
    _backup(codex_config)
    codex_files.write_notify(codex_config, config.codex_original_notify)
    config.codex_original_notify = []
    config_module.save(paths, config)
    return True
