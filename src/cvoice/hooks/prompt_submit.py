"""You are typing again, so this session's pending speech is stale.

Other sessions are left alone: silencing another agent's summary because you typed here
would be wrong. This hook must print nothing at all - stdout on UserPromptSubmit is fed
straight into the model's context.
"""

from __future__ import annotations

import subprocess
from typing import Callable, Optional

from ..queue import pending, read_item
from ..state import Paths
from . import common


def stop_playback() -> None:
    for binary in ("say", "afplay"):
        subprocess.run(["pkill", "-x", binary], capture_output=True)


def handle(
    payload: dict,
    paths: Optional[Paths] = None,
    stopper: Optional[Callable[[], None]] = None,
) -> None:
    session = payload.get("session_id")
    if not session:
        return

    paths = paths or Paths.default()
    for path in pending(paths):
        try:
            item = read_item(path)
        except Exception:  # noqa: BLE001
            continue
        if item.session == session:
            path.unlink(missing_ok=True)

    current = paths.state_dir / "current-session"
    try:
        speaking_for = current.read_text().strip()
    except FileNotFoundError:
        speaking_for = ""
    if speaking_for == session:
        (stopper or stop_playback)()


def main(payload: dict, detached: bool = False) -> None:
    if common.is_child():
        return
    handle(payload)
