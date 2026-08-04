"""Turn a long reply into one or two spoken sentences.

Runs a separate, cheap Claude invocation. Two details are load-bearing: hooks are
disabled in the child (otherwise it triggers this very hook and recurses forever), and
the reply is embedded inside the prompt between markers rather than piped on stdin -
piping made the model answer the instructions instead of summarizing them.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from typing import Optional

from .i18n import Pack

MAX_INPUT_CHARS = 6000
CHILD_ENV_VAR = "CVOICE_CHILD"


def strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[#*_>|~]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def run(text: str, pack: Pack, model: str = "haiku", timeout: int = 120) -> Optional[str]:
    """Condense a reply into one or two spoken sentences.

    Three details are load-bearing, each learned the hard way:

    * stdin is closed. A child inherits the parent's stdin, and a hook's stdin is the
      JSON payload Claude Code sent it - the model would summarize that instead.
    * The task lives in the system prompt and the reply is the whole user message, so
      instructions and data cannot be confused for one another.
    * It runs in an empty directory with memory and CLAUDE.md switched off, otherwise
      the child answers from the project's context rather than from the text given.
    """
    settings = json.dumps(
        {
            "disableAllHooks": True,
            "autoMemoryEnabled": False,
            "claudeMdExcludes": ["**/CLAUDE.md"],
            "disableBundledSkills": True,
        }
    )
    env = dict(os.environ, **{CHILD_ENV_VAR: "1"})
    try:
        with tempfile.TemporaryDirectory() as sandbox:
            result = subprocess.run(
                [
                    "claude", "-p",
                    "--model", model,
                    "--strict-mcp-config",
                    "--mcp-config", '{"mcpServers":{}}',
                    "--settings", settings,
                    "--append-system-prompt", pack.summary_system,
                    text[:MAX_INPUT_CHARS],
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=sandbox,
                stdin=subprocess.DEVNULL,
            )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

    if result.returncode != 0:
        return None
    answer = strip_markdown(result.stdout or "")
    return answer or None
