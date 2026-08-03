"""End of turn: say what was done.

A reply short enough and already in the target language is read as it stands; anything
else is condensed by the summarizer. The work happens in a detached process because the
summarizer takes seconds and the session must not wait for it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from .. import summarize
from ..state import Paths
from . import common

VERBATIM_LIMIT = 300


def last_assistant_text(transcript_path: Path) -> str:
    """Text blocks of the last main-thread assistant message."""
    try:
        lines = transcript_path.read_text().splitlines()
    except (FileNotFoundError, OSError):
        return ""
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("type") != "assistant" or record.get("isSidechain"):
            continue
        content = record.get("message", {}).get("content", [])
        parts = [block.get("text", "") for block in content if block.get("type") == "text"]
        joined = " ".join(part for part in parts if part).strip()
        if joined:
            return joined
    return ""


def handle(
    payload: dict,
    paths: Optional[Paths] = None,
    notifier: Optional[Callable[..., None]] = None,
    worker: Optional[Callable[[], None]] = None,
) -> None:
    context = common.build_context(payload, paths=paths)
    if context.mode == "off":
        return

    transcript = payload.get("transcript_path")
    if not transcript:
        return

    raw = last_assistant_text(Path(transcript))
    clean = summarize.strip_markdown(raw)
    if not clean:
        return

    if len(clean) <= VERBATIM_LIMIT and context.pack.matches_language(clean):
        spoken = clean
    else:
        spoken = summarize.run(clean, context.pack) or context.pack.phrase("summary.fallback")

    common.emit(context, kind="tldr", text=spoken, priority=1, notifier=notifier, worker=worker)


def main(payload: dict, detached: bool = False) -> None:
    if common.is_child():
        return
    if detached:
        handle(payload)
    else:
        common.detach("stop", payload)
