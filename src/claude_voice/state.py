"""Where everything lives on disk.

Every module takes its paths from here rather than building them, so tests can
point the whole tool at a temporary directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    root: Path

    @classmethod
    def default(cls) -> "Paths":
        override = os.environ.get("CLAUDE_VOICE_HOME")
        if override:
            return cls(root=Path(override))
        return cls(root=Path(os.environ.get("HOME", "~")).expanduser() / ".claude-voice")

    @property
    def config_file(self) -> Path:
        return self.root / "config.toml"

    @property
    def queue_dir(self) -> Path:
        return self.root / "queue"

    @property
    def lock_dir(self) -> Path:
        return self.root / "lock"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def scopes_dir(self) -> Path:
        return self.root / "scopes"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def history_file(self) -> Path:
        return self.root / "history.jsonl"

    @property
    def health_file(self) -> Path:
        return self.root / "health.json"

    @property
    def snooze_file(self) -> Path:
        return self.state_dir / "snooze"

    @property
    def seen_file(self) -> Path:
        return self.state_dir / "seen-until"

    @property
    def last_label_file(self) -> Path:
        return self.state_dir / "last-label"

    def ensure(self) -> None:
        for directory in (self.root, self.queue_dir, self.cache_dir, self.scopes_dir, self.state_dir):
            directory.mkdir(parents=True, exist_ok=True)


import time
from typing import Optional


def snoozed_until(paths: Paths) -> Optional[float]:
    """Epoch second the mute expires, or None. Expired files are cleaned up here."""
    try:
        raw = paths.snooze_file.read_text().strip()
    except FileNotFoundError:
        return None
    try:
        until = float(raw)
    except ValueError:
        paths.snooze_file.unlink(missing_ok=True)
        return None
    if until <= time.time():
        paths.snooze_file.unlink(missing_ok=True)
        return None
    return until


def set_snooze(paths: Paths, minutes: float) -> float:
    until = time.time() + minutes * 60
    paths.snooze_file.parent.mkdir(parents=True, exist_ok=True)
    paths.snooze_file.write_text(str(until))
    return until


def clear_snooze(paths: Paths) -> None:
    paths.snooze_file.unlink(missing_ok=True)
