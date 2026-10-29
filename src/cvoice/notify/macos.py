"""Silent macOS banners.

No sound on purpose: the point is not to interrupt a call. Note that Focus / Do Not
Disturb suppresses banners entirely even though delivery succeeds, which is why the
menu bar carries the unread counter.

Channels are tried in order and a failing one falls through to the next. SwiftBar comes
first when our menu-bar plugin is installed: it is a signed, notarized app, whereas a
Homebrew terminal-notifier is ad-hoc signed and macOS can refuse it permission without
ever asking - after an upgrade it no longer matches the copy that was once allowed.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path
from typing import Iterator, List, Optional, Tuple
from urllib.parse import quote

TERMINAL_BUNDLES = {
    "iTerm.app": "com.googlecode.iterm2",
    "Apple_Terminal": "com.apple.Terminal",
    "vscode": "com.microsoft.VSCode",
    "ghostty": "com.mitchellh.ghostty",
    "WarpTerminal": "dev.warp.Warp-Stable",
}

SWIFTBAR_PREFS = Path("~/Library/Preferences/com.ameba.SwiftBar.plist")
SWIFTBAR_PLUGIN = "cvoice"


class NotifyError(Exception):
    """No notification mechanism could deliver the message."""


def terminal_bundle_id() -> Optional[str]:
    """Bundle id of the terminal this session runs in, so a click returns to it."""
    return TERMINAL_BUNDLES.get(os.environ.get("TERM_PROGRAM", ""))


def swiftbar_plugin_installed() -> bool:
    """SwiftBar drops a notify URL naming a plugin it does not have, without a word."""
    try:
        with SWIFTBAR_PREFS.expanduser().open("rb") as handle:
            directory = plistlib.load(handle).get("PluginDirectory")
    except (OSError, plistlib.InvalidFileException, ValueError):
        return False
    if not isinstance(directory, str):
        return False
    return any(Path(directory).expanduser().glob(f"{SWIFTBAR_PLUGIN}.*"))


def _swiftbar_text(text: str) -> str:
    """Make text safe to carry through SwiftBar's notify URL.

    SwiftBar rebuilds the query into a `key=value` line and parses it again to find the
    click action. A value is quoted only when it holds a space, and nothing inside it is
    escaped: an apostrophe - in every other Ukrainian sentence - ends the quote early, a
    backslash escapes the closing one, and a tab avoids quoting altogether. Either way the
    rest of the text is read as parameters, including bash=, which runs on click.
    "+" is shown as a space.
    """
    text = " ".join(text.split())
    return text.replace("'", "’").replace("\\", "/").replace("+", "＋")


def _swiftbar_url(title: str, body: str) -> str:
    params: List[Tuple[str, str]] = [
        ("plugin", SWIFTBAR_PLUGIN),
        ("title", _swiftbar_text(title)),
        ("body", _swiftbar_text(body)),
        ("silent", "true"),
    ]
    bundle = terminal_bundle_id()
    if bundle:
        params += [("bash", "/usr/bin/open"), ("param1", "-b"), ("param2", bundle), ("terminal", "false")]
    return "swiftbar://notify?" + "&".join(f"{key}={quote(value, safe='')}" for key, value in params)


def _channels(title: str, body: str, group: str) -> Iterator[Tuple[str, List[str]]]:
    if swiftbar_plugin_installed():
        yield "swiftbar", ["open", "-g", _swiftbar_url(title, body)]
    if shutil.which("terminal-notifier"):
        argv = ["terminal-notifier", "-title", title, "-message", body, "-group", group]
        bundle = terminal_bundle_id()
        if bundle:
            argv += ["-activate", bundle]
        yield "terminal-notifier", argv
    if shutil.which("osascript"):
        script = f'display notification {body!r} with title {title!r}'
        yield "osascript", ["osascript", "-e", script]


def send(title: str, body: str, group: str = "cvoice") -> None:
    failures = []
    for name, argv in _channels(title, body, group):
        result = subprocess.run(argv, capture_output=True, text=True)
        if result.returncode == 0:
            return
        failures.append(f"{name}: {result.stderr.strip() or f'exited {result.returncode}'}")
    if not failures:
        raise NotifyError("neither SwiftBar, terminal-notifier nor osascript is available")
    raise NotifyError("; ".join(failures))
