"""SwiftBar menu.

Focus suppresses banners but cannot touch the menu bar, so the unread counter and the
text of the last message live here. The plugin itself is three lines; all of the logic
is this function, which means it is testable.
"""

from __future__ import annotations

import time
from typing import List

from .. import health, history
from ..config import Config
from ..state import Paths, snoozed_until

ICONS = {"off": "🔇", "notify": "🔔", "voice": "🔊", "both": "🔊"}
RUN = 'bash="/bin/bash" terminal=false refresh=true'
TRUNCATE_AT = 64


def _shell(paths: Paths) -> str:
    # SwiftBar numbers arguments from param1, so the shim is param1 and the subcommand
    # is param2. Getting this off by one silently produces a menu whose items do nothing.
    return f'param1="{paths.root}/bin/cv-hook"'


def _unread(paths: Paths) -> int:
    try:
        seen = paths.seen_file.read_text().strip()
    except FileNotFoundError:
        seen = ""
    return sum(1 for entry in history.recent(paths, limit=200) if entry.id > seen)


def _clean(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def render(paths: Paths, config: Config) -> str:
    lines: List[str] = []
    failures = health.failures(paths)
    until = snoozed_until(paths)
    unread = _unread(paths)

    muted_by_mic = False
    if config.mute_while_mic_in_use and paths.mic_helper.exists():
        from ..mic import in_use

        muted_by_mic = in_use(paths.mic_helper)

    if failures:
        icon = "⚠️"
    elif muted_by_mic:
        icon = "🎙"
    elif until is not None:
        icon = f"⏸ {int((until - time.time()) / 60) + 1}m"
    else:
        icon = ICONS.get(config.mode, "🔔")
    lines.append(f"{icon} {unread}" if unread else icon)
    lines.append("---")
    if muted_by_mic:
        lines.append("Quiet while you are recording | color=#8e8e93")

    for failure in failures:
        lines.append(f"{_clean(failure.component)}: {_clean(failure.error)} | color=#ff9f0a")
    if failures:
        lines.append(f'Run doctor | {RUN} {_shell(paths)} param2="doctor"')
        lines.append("---")

    entries = history.recent(paths, limit=12)
    if entries:
        lines.append(_clean(entries[0].text) + " | size=12")
    if unread:
        lines.append(f'Mark as read ({unread}) | {RUN} {_shell(paths)} param2="seen"')
    lines.append("---")

    if until is not None:
        lines.append(f'Resume | {RUN} {_shell(paths)} param2="resume"')
    else:
        lines.append("Pause")
        for minutes in (15, 30, 60):
            lines.append(
                f'-- {minutes} minutes | {RUN} {_shell(paths)} param2="snooze" param3="{minutes}"'
            )

    lines.append("Mode")
    for mode in ("off", "notify", "voice", "both"):
        mark = "●" if mode == config.mode else "○"
        lines.append(f'-- {mark} {mode} | {RUN} {_shell(paths)} param2="mode" param3="{mode}"')

    lines.append("---")
    lines.append("History")
    for entry in entries:
        text = entry.text if len(entry.text) <= TRUNCATE_AT else entry.text[:TRUNCATE_AT] + "…"
        marker = "?" if entry.kind == "question" else "+"
        stamp = time.strftime("%H:%M", time.localtime(entry.ts))
        lines.append(
            f'{marker} {stamp}  {_clean(text)} | {RUN} {_shell(paths)} param2="play" param3="{entry.id}"'
        )

    lines.append("---")
    lines.append(f'Replay last | {RUN} {_shell(paths)} param2="replay"')
    lines.append(f'Skip | {RUN} {_shell(paths)} param2="skip"')
    lines.append(f'Silence now | {RUN} {_shell(paths)} param2="shut"')
    lines.append("Refresh | refresh=true")
    return "\n".join(lines)
