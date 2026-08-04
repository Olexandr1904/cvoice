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
# Asking a model for "at most 200 characters" is a request, not a guarantee - one reply
# came back at 1248 characters, which is a minute and a half of speech. The limit has to
# live in the code.
SPOKEN_MAX_SENTENCES = 3
SPOKEN_MAX_CHARS = 320

# A boundary is punctuation followed by space or end - never the dot in "parser.py".
_SENTENCE_END = re.compile(r"[.!?\u2026]+(?=\s|$)")
CHILD_ENV_VAR = "CVOICE_CHILD"


def strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[#*_>|~]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def condense(
    text: str,
    max_sentences: int = SPOKEN_MAX_SENTENCES,
    max_chars: int = SPOKEN_MAX_CHARS,
) -> str:
    """Trim anything on its way to the speakers down to a couple of sentences.

    The original string is sliced rather than rebuilt from pieces, so file names and
    version numbers survive intact.
    """
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""

    ends = [match.end() for match in _SENTENCE_END.finditer(text)]
    if len(ends) >= max_sentences:
        text = text[: ends[max_sentences - 1]]

    if len(text) > max_chars:
        fitting = [end for end in ends if end <= max_chars]
        if fitting:
            text = text[: fitting[-1]]
        else:
            text = text[:max_chars].rsplit(" ", 1)[0].rstrip(" ,;:") + "\u2026"
    return text


def run(text: str, pack: Pack, model: str = "sonnet", timeout: int = 120) -> Optional[str]:
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
    answer = condense(strip_markdown(result.stdout or ""))
    if "?" in answer:
        # A summary never asks anything. When the model starts a conversation instead
        # of condensing ("Sorry, I am not sure what you need"), the caller's fixed
        # phrase is a better thing to say out loud than the model's confusion.
        return None
    return answer or None
