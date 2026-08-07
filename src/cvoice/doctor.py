"""Self-diagnosis.

The single most confusing failure in the prototype was banners being delivered but
suppressed by Do Not Disturb, which looks exactly like the feature being broken. That is
why Focus gets its own check.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List

from . import health
from .config import Config
from .queue import _process_alive  # noqa: F401 - reused rather than duplicated
from .state import Paths

FOCUS_ASSERTIONS = Path.home() / "Library/DoNotDisturb/DB/Assertions.json"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    remedy: str = ""
    advisory: bool = False
    """A condition of the machine rather than a fault of ours: reported, but it must not
    make the whole check fail. Focus being on is the case this exists for - a first run
    that exits non-zero reads as a broken install."""


REQUIRED_BINARIES = {
    "edge-tts": "pip install edge-tts (inside ~/.cvoice/.venv)",
    "terminal-notifier": "brew install terminal-notifier",
    "say": "part of macOS; this tool is macOS only",
    "afplay": "part of macOS; this tool is macOS only",
    "claude": "install the Claude Code CLI",
}


def focus_active() -> bool:
    try:
        data = json.loads(FOCUS_ASSERTIONS.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    return bool(data.get("data", [{}])[0].get("storeAssertionRecords"))


def hook_check() -> List[Check]:
    """Every Claude config directory should reference an existing shim."""
    results = []
    home = Path(os.environ.get("HOME", "~")).expanduser()
    for config_dir in sorted(home.glob(".claude*")):
        settings = config_dir / "settings.json"
        if not settings.exists():
            continue
        try:
            text = settings.read_text()
        except OSError:
            continue
        installed = "cv-hook" in text
        results.append(
            Check(
                name=f"hooks in {config_dir.name}",
                ok=installed,
                detail="installed" if installed else "no cvoice hooks found",
                remedy="run ./install.sh again",
            )
        )
    return results


def checks(paths: Paths, config: Config) -> List[Check]:
    results: List[Check] = []

    from .speech.edge import edge_binary

    for binary, remedy in REQUIRED_BINARIES.items():
        # Resolve edge-tts exactly as the worker does, or doctor reports OK while
        # playback quietly falls back to the built-in voice.
        found = edge_binary() if binary == "edge-tts" else shutil.which(binary)
        results.append(
            Check(name=binary, ok=bool(found), detail=found or "not found", remedy=remedy)
        )

    failures = health.failures(paths)
    results.append(
        Check(
            name="recent failures",
            ok=not failures,
            detail="; ".join(f"{item.component}: {item.error}" for item in failures) or "none",
            remedy="fix the component above, then run: cvoice doctor",
        )
    )

    stale = False
    if paths.lock_dir.exists():
        try:
            owner = int((paths.lock_dir / "pid").read_text().strip())
        except (FileNotFoundError, ValueError):
            owner = 0
        stale = not _process_alive(owner)
    results.append(
        Check(
            name="speech lock",
            ok=not stale,
            detail="stale lock left by a dead worker" if stale else "free",
            remedy=f"rm -rf {paths.lock_dir}",
        )
    )

    if config.mute_while_mic_in_use:
        from .mic import in_use

        built = paths.mic_helper.exists()
        results.append(
            Check(
                name="microphone detection",
                ok=built,
                detail=("recording right now" if in_use(paths.mic_helper) else "idle")
                if built
                else "helper not built (needs swiftc)",
                remedy="install Xcode command line tools, then run ./install.sh again",
                advisory=True,
            )
        )

    from .codex import config_path as codex_config_path
    from .codex import is_installed as codex_installed
    from .codex import read_notify

    codex_config = codex_config_path()
    if codex_installed(codex_config):
        notify = read_notify(codex_config)
        installed = bool(notify) and "cv-hook" in notify[0]
        results.append(
            Check(
                name="codex",
                ok=installed,
                detail="reporting through cvoice"
                if installed
                else f"notify points elsewhere: {' '.join(notify) or 'unset'}",
                remedy="run ./install.sh again to take the slot back",
            )
        )

    suppressed = focus_active()
    results.append(
        Check(
            name="focus",
            ok=not suppressed,
            detail="Do Not Disturb is on: banners are delivered but not shown" if suppressed else "off",
            remedy="allow time-sensitive notifications for terminal-notifier, or rely on the menu bar",
            advisory=True,
        )
    )

    results.extend(hook_check())
    return results


def report(paths: Paths, config: Config) -> int:
    results = checks(paths, config)
    for check in results:
        mark = "OK  " if check.ok else ("WARN" if check.advisory else "FAIL")
        line = f"[{mark}] {check.name}: {check.detail}"
        if not check.ok and check.remedy:
            line += f"\n         -> {check.remedy}"
        print(line)
    return 0 if all(check.ok or check.advisory for check in results) else 1
