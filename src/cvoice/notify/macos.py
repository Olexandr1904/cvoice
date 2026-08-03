"""Silent macOS banners.

No sound on purpose: the point is not to interrupt a call. Note that Focus / Do Not
Disturb suppresses banners entirely even though delivery succeeds, which is why the
menu bar carries the unread counter.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional

TERMINAL_BUNDLES = {
    "iTerm.app": "com.googlecode.iterm2",
    "Apple_Terminal": "com.apple.Terminal",
    "vscode": "com.microsoft.VSCode",
    "ghostty": "com.mitchellh.ghostty",
    "WarpTerminal": "dev.warp.Warp-Stable",
}


class NotifyError(Exception):
    """No notification mechanism could deliver the message."""


def terminal_bundle_id() -> Optional[str]:
    """Bundle id of the terminal this session runs in, so a click returns to it."""
    return TERMINAL_BUNDLES.get(os.environ.get("TERM_PROGRAM", ""))


def send(title: str, body: str, group: str = "cvoice") -> None:
    if shutil.which("terminal-notifier"):
        argv = ["terminal-notifier", "-title", title, "-message", body, "-group", group]
        bundle = terminal_bundle_id()
        if bundle:
            argv += ["-activate", bundle]
    elif shutil.which("osascript"):
        script = f'display notification {body!r} with title {title!r}'
        argv = ["osascript", "-e", script]
    else:
        raise NotifyError("neither terminal-notifier nor osascript is available")

    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise NotifyError(result.stderr.strip() or f"{argv[0]} exited {result.returncode}")
