"""Claude is asking something: get attention now.

Runs before the tool is allowed to proceed, so it must stay fast - no summarizer here.
The banner can carry the question verbatim; the spoken line cannot, because a voice
tuned for one language mangles any other.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..state import Paths
from . import common

TOOLS = ("AskUserQuestion", "ExitPlanMode")


def handle(
    payload: dict,
    paths: Optional[Paths] = None,
    notifier: Optional[Callable[..., None]] = None,
    worker: Optional[Callable[[], None]] = None,
) -> None:
    tool = payload.get("tool_name", "")
    if tool not in TOOLS:
        return

    context = common.build_context(payload, paths=paths)
    if context.mode == "off":
        return

    if tool == "ExitPlanMode":
        spoken = banner = context.pack.phrase("plan.ready")
    else:
        questions = payload.get("tool_input", {}).get("questions", []) or []
        first = (questions[0].get("question") if questions else "") or ""
        banner = first or context.pack.phrase("question.single")
        if len(questions) > 1:
            banner = f"{banner} (+{len(questions) - 1})"
        if first and context.pack.matches_language(first):
            spoken = context.pack.phrase("question.with_text", question=first)
        elif len(questions) > 1:
            spoken = context.pack.phrase("question.many")
        else:
            spoken = context.pack.phrase("question.single")

    common.emit(
        context,
        kind="question",
        text=spoken,
        banner=banner,
        priority=0,
        notifier=notifier,
        worker=worker,
    )


def main(payload: dict, detached: bool = False) -> None:
    if common.is_child():
        return
    handle(payload)
