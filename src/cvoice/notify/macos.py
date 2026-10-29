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
import re
import shutil
import subprocess
import sys
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

TERMINAL_APP = "com.apple.Terminal"
_TTY_NAME = re.compile(r"ttys\d+")

# Brings forward the Terminal tab whose tty is the only argument. The tty arrives as an
# argument rather than spliced into the text, so nothing in it can become AppleScript.
# Answers "missing" when no tab has it, and the caller falls back to the app itself.
_FOCUS_TERMINAL_TAB = """
on run argv
    set wanted to "/dev/" & item 1 of argv
    tell application "Terminal"
        repeat with w in windows
            repeat with t in tabs of w
                if tty of t is wanted then
                    if miniaturized of w then set miniaturized of w to false
                    set selected of t to true
                    set index of w to 1
                    activate
                    return "found"
                end if
            end repeat
        end repeat
    end tell
    return "missing"
end run
"""


class NotifyError(Exception):
    """No notification mechanism could deliver the message."""


def terminal_bundle_id() -> Optional[str]:
    """Bundle id of the terminal this session runs in, so a click returns to it."""
    return TERMINAL_BUNDLES.get(os.environ.get("TERM_PROGRAM", ""))


def valid_tty(value: object) -> Optional[str]:
    """A tty name such as "ttys001", or None for anything else."""
    return value if isinstance(value, str) and _TTY_NAME.fullmatch(value) else None


def focus(bundle: str, tty: Optional[str]) -> None:
    """Bring the session's terminal forward when its banner is clicked.

    Terminal can be asked for the exact tab. Any other app, a tab closed since, or
    Automation permission refused still gets the app itself brought forward.
    """
    tty = valid_tty(tty)
    if bundle == TERMINAL_APP and tty:
        result = subprocess.run(["osascript", "-e", _FOCUS_TERMINAL_TAB, tty], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip() == "found":
            return
    subprocess.run(["open", "-b", bundle], capture_output=True, text=True)


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


def _swiftbar_url(title: str, body: str, tty: Optional[str]) -> str:
    params: List[Tuple[str, str]] = [
        ("plugin", SWIFTBAR_PLUGIN),
        ("title", _swiftbar_text(title)),
        ("body", _swiftbar_text(body)),
        ("silent", "true"),
    ]
    bundle = terminal_bundle_id()
    if bundle:
        # A click runs `cvoice focus`; SwiftBar passes param1..N as its arguments.
        args = ["-m", "cvoice.cli", "focus", bundle] + ([tty] if valid_tty(tty) else [])
        params.append(("bash", sys.executable))
        params += [(f"param{number}", arg) for number, arg in enumerate(args, start=1)]
        params.append(("terminal", "false"))
    return "swiftbar://notify?" + "&".join(f"{key}={quote(value, safe='')}" for key, value in params)


def _channels(title: str, body: str, group: str, tty: Optional[str]) -> Iterator[Tuple[str, List[str]]]:
    if swiftbar_plugin_installed():
        yield "swiftbar", ["open", "-g", _swiftbar_url(title, body, tty)]
    if shutil.which("terminal-notifier"):
        argv = ["terminal-notifier", "-title", title, "-message", body, "-group", group]
        bundle = terminal_bundle_id()
        if bundle:
            argv += ["-activate", bundle]
        yield "terminal-notifier", argv
    if shutil.which("osascript"):
        script = f'display notification {body!r} with title {title!r}'
        yield "osascript", ["osascript", "-e", script]


def send(title: str, body: str, group: str = "cvoice", tty: Optional[str] = None) -> None:
    failures = []
    for name, argv in _channels(title, body, group, tty):
        result = subprocess.run(argv, capture_output=True, text=True)
        if result.returncode == 0:
            return
        failures.append(f"{name}: {result.stderr.strip() or f'exited {result.returncode}'}")
    if not failures:
        raise NotifyError("neither SwiftBar, terminal-notifier nor osascript is available")
    raise NotifyError("; ".join(failures))
