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
# Below this, asking a model to summarize gives it almost nothing to work with and it
# answers the instructions instead ("Understood, I'll write one-line summaries").
MIN_SUMMARIZE = 40
# A turn that used no tools and said little did nothing worth announcing: greetings,
# "waiting for your task", acknowledgements.
MIN_CHATTER = 120


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


def turn_used_tools(transcript_path: Path) -> bool:
    """Did the assistant actually do something since the last real user prompt?

    Tool results come back as `user` records holding `tool_result` blocks, so walking
    backwards stops only at a genuine prompt from the person.
    """
    try:
        lines = transcript_path.read_text().splitlines()
    except (FileNotFoundError, OSError):
        return False

    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("isSidechain"):
            continue
        blocks = record.get("message", {}).get("content")
        blocks = blocks if isinstance(blocks, list) else []
        if record.get("type") == "user":
            if not blocks or any(block.get("type") != "tool_result" for block in blocks):
                return False
        elif record.get("type") == "assistant":
            if any(block.get("type") == "tool_use" for block in blocks):
                return True
    return False


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

    if not turn_used_tools(Path(transcript)) and len(clean) < MIN_CHATTER:
        return

    if len(clean) < MIN_SUMMARIZE or (
        len(clean) <= VERBATIM_LIMIT and context.pack.matches_language(clean)
    ):
        spoken = summarize.condense(clean)
    else:
        spoken = common.summarise(context, clean)

    common.emit(context, kind="tldr", text=spoken, priority=1, notifier=notifier, worker=worker)


def main(payload: dict, detached: bool = False) -> None:
    if common.is_child():
        return
    if detached:
        handle(payload)
    else:
        common.detach("stop", payload)
