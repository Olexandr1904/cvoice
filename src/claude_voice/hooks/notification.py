"""Claude is blocked: waiting for a permission decision or simply idle.

These are announced but deliberately never stored - "waiting for your input" carries no
information after the fact, and in the prototype such lines crowded the history out.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Optional

from ..state import Paths
from . import common

QUIET_SECONDS = 180
_TOOL = re.compile(r"to use ([A-Za-z_]+)")


def handle(
    payload: dict,
    paths: Optional[Paths] = None,
    notifier: Optional[Callable[..., None]] = None,
    worker: Optional[Callable[[], None]] = None,
) -> None:
    message = str(payload.get("message", ""))
    if not message:
        return

    context = common.build_context(payload, paths=paths)
    if context.mode == "off":
        return

    lowered = message.lower()
    if "permission" in lowered:
        match = _TOOL.search(message)
        spoken = (
            context.pack.phrase("permission.tool", tool=match.group(1))
            if match
            else context.pack.phrase("permission.generic")
        )
    elif "waiting" in lowered or "idle" in lowered:
        stamp = context.paths.state_dir / f"notified-{context.session}"
        try:
            last = float(stamp.read_text())
        except (FileNotFoundError, ValueError):
            last = 0.0
        if time.time() - last < QUIET_SECONDS:
            return
        spoken = context.pack.phrase("waiting")
    else:
        return

    stamp = context.paths.state_dir / f"notified-{context.session}"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(str(time.time()))

    common.emit(
        context,
        kind="notice",
        text=spoken,
        banner=message,
        priority=0,
        notifier=notifier,
        worker=worker,
    )


def main(payload: dict, detached: bool = False) -> None:
    if common.is_child():
        return
    handle(payload)
