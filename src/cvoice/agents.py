"""Which agent produced a message.

The agent is folded into the label rather than announced separately: the speaker already
says a label only when it differs from the previous utterance, so switching agents is
heard and a run of turns from the same one is not.
"""

from __future__ import annotations

CLAUDE = "claude"
CODEX = "codex"

DISPLAY_NAMES = {CODEX: "Codex"}


def label_for(agent: str, project: str) -> str:
    """The label spoken and shown for a message from `agent` in `project`."""
    name = DISPLAY_NAMES.get(agent, "")
    if not name:
        return project
    return f"{name}, {project}" if project else name
