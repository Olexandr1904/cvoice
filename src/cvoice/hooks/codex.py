"""Codex has finished a turn.

Codex offers one notification slot, already occupied on a normal install, so this runs as
a chain: the stored original command goes first, then our own work. It reports summaries
only - Codex surfaces neither questions nor permission prompts as events.
"""

from __future__ import annotations

import json
import subprocess
from typing import Callable, Dict, List, Optional

from .. import codex as codex_files
from .. import config as config_module
from .. import summarize
from ..agents import CODEX
from ..state import Paths
from . import common

MESSAGE_KEYS = ("last-assistant-message", "last_agent_message", "message")
TURN_KEYS = ("turn-id", "turn_id")
CWD_KEYS = ("cwd", "workdir", "working-directory")

VERBATIM_LIMIT = 300
MIN_SUMMARIZE = 40
MIN_CHATTER = 120


def parse_payload(args: List[str]) -> Optional[Dict[str, str]]:
    """Pull the finished turn out of whatever Codex passed on the command line.

    Every argument is tried, because the exact layout is undocumented and has not been
    observed directly. A payload with no message is not worth reporting.
    """
    for argument in args:
        try:
            data = json.loads(argument)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue

        message = ""
        for key in MESSAGE_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                message = value.strip()
                break
        if not message:
            continue

        turn_id = ""
        for key in TURN_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value:
                turn_id = value
                break

        parsed = {"message": message, "turn_id": turn_id}
        for key in CWD_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value:
                parsed["cwd"] = value
                break
        return parsed
    return None


def chain(original: List[str], args: List[str], paths: Optional[Paths] = None) -> None:
    """Run the command our shim displaced, with its own arguments plus ours.

    This happens before any work of our own, so that a failure on our side cannot stop
    whatever was in the slot first - on a normal install, Codex Computer Use.

    Only a failure to start is visible from here: the process is detached on purpose, so
    whatever it does afterwards is its own business.
    """
    if not original:
        return
    try:
        subprocess.Popen(
            list(original) + list(args),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as error:  # noqa: BLE001 - the chain must never take us down
        if paths is not None:
            from .. import health

            health.record(paths, "codex-notify-chain", str(error))


def handle(
    args: List[str],
    paths: Optional[Paths] = None,
    notifier: Optional[Callable[..., None]] = None,
    worker: Optional[Callable[[], None]] = None,
) -> None:
    parsed = parse_payload(args)
    if parsed is None:
        return

    context = common.build_context(
        {"session_id": parsed["turn_id"] or "codex"},
        paths=paths,
        agent=CODEX,
        project_dir=parsed.get("cwd"),
    )
    if context.mode == "off":
        return

    # Codex can call notify more than once for a turn; the id is what makes it one turn.
    if parsed["turn_id"]:
        seen = context.paths.state_dir / f"codex-{parsed['turn_id']}"
        if seen.exists():
            return
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text("")

    clean = summarize.strip_markdown(parsed["message"])
    if not clean:
        return

    if not codex_files.turn_used_tools(parsed["turn_id"]) and len(clean) < MIN_CHATTER:
        return

    if len(clean) < MIN_SUMMARIZE or (
        len(clean) <= VERBATIM_LIMIT and context.pack.matches_language(clean)
    ):
        spoken = summarize.condense(clean)
    else:
        spoken = summarize.run(clean, context.pack, model=context.config.model) or context.pack.phrase(
            "summary.fallback"
        )

    common.emit(context, kind="tldr", text=spoken, priority=1, notifier=notifier, worker=worker)


def main(args: List[str], paths: Optional[Paths] = None) -> None:
    """The notify entry point. The chain comes first, whatever happens afterwards."""
    if common.is_child():
        return

    paths = paths or Paths.default()
    paths.ensure()
    chain(config_module.load(paths).codex_original_notify, args, paths=paths)

    try:
        handle(args, paths=paths)
    except Exception:  # noqa: BLE001 - a hook that crashes must not surface to the user
        pass
