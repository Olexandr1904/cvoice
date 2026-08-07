"""Codex's own files.

Only two things are needed: the `notify` slot in its config, and the rollout transcript of
a finished turn. Codex rewrites this config itself, so nothing of ours is ever stored in
it beyond the one key we own.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on older interpreters
    import tomli as tomllib

import tomli_w


def config_path() -> Path:
    home = os.environ.get("CODEX_HOME")
    return Path(home) / "config.toml" if home else Path.home() / ".codex" / "config.toml"


def sessions_dir() -> Path:
    home = os.environ.get("CODEX_HOME")
    return Path(home) / "sessions" if home else Path.home() / ".codex" / "sessions"


def is_installed(config: Optional[Path] = None) -> bool:
    return (config or config_path()).exists()


def _load(config: Path) -> dict:
    try:
        return tomllib.loads(config.read_text())
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return {}


def read_notify(config: Optional[Path] = None) -> List[str]:
    """The configured notify command, as a list. Empty when unset or unreadable."""
    value = _load(config or config_path()).get("notify")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def write_notify(config: Path, command: List[str]) -> None:
    """Replace the notify command, preserving everything else in the file."""
    data = _load(config)
    data["notify"] = list(command)
    config.write_bytes(tomli_w.dumps(data).encode())


ROLLOUTS_SEARCHED = 5


def _rollout_files(sessions: Path) -> List[Path]:
    """Newest first. Only a handful: the turn that just ended is in a recent file."""
    try:
        files = [path for path in sessions.rglob("rollout-*.jsonl") if path.is_file()]
    except OSError:
        return []
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[:ROLLOUTS_SEARCHED]


def turn_used_tools(turn_id: str, sessions: Optional[Path] = None) -> bool:
    """Did this turn call a tool, or only talk?

    Returns True when we cannot tell. Unlike Claude Code there is no second source of
    truth here, and a missed summary is worse than an occasional needless one.
    """
    for path in _rollout_files(sessions or sessions_dir()):
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue

        used = False
        for line in lines:
            try:
                payload = json.loads(line).get("payload") or {}
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            kind = payload.get("type")
            if kind == "user_message":
                used = False  # a new turn starts here
            elif kind in ("custom_tool_call", "function_call", "local_shell_call"):
                used = True
            elif kind == "task_complete" and payload.get("turn_id") == turn_id:
                return used
    return True
