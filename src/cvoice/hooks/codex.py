"""Codex has finished a turn.

Codex offers one notification slot, already occupied on a normal install, so this runs as
a chain: the stored original command goes first, then our own work. It reports summaries
only - Codex surfaces neither questions nor permission prompts as events.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

MESSAGE_KEYS = ("last-assistant-message", "last_agent_message", "message")
TURN_KEYS = ("turn-id", "turn_id")
CWD_KEYS = ("cwd", "workdir", "working-directory")


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
