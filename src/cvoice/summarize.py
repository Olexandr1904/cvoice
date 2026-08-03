"""Turn a long reply into one or two spoken sentences.

Runs a separate, cheap Claude invocation. Two details are load-bearing: hooks are
disabled in the child (otherwise it triggers this very hook and recurses forever), and
the reply is embedded inside the prompt between markers rather than piped on stdin -
piping made the model answer the instructions instead of summarizing them.
"""

from __future__ import annotations

import os
import re
import subprocess
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


def run(text: str, pack: Pack, timeout: int = 120) -> Optional[str]:
    prompt = pack.summary_prompt.format(text=text[:MAX_INPUT_CHARS])
    env = dict(os.environ, **{CHILD_ENV_VAR: "1"})
    try:
        result = subprocess.run(
            [
                "claude", "-p",
                "--model", "haiku",
                "--strict-mcp-config",
                "--mcp-config", '{"mcpServers":{}}',
                "--settings", '{"disableAllHooks":true}',
                prompt,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

    if result.returncode != 0:
        return None
    answer = strip_markdown(result.stdout or "")
    return answer or None
