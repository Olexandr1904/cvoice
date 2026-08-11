"""Shared plumbing for every hook: payload, context, emit, detach.

Hooks must return control to Claude Code immediately, so anything slow is handed to a
detached process. Everything here takes its collaborators as arguments so tests never
touch the network, the speakers or the notification centre.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .. import config as config_module
from .. import health, history
from ..agents import CLAUDE, label_for
from ..i18n import Pack
from ..i18n import load as load_pack
from ..queue import Item, enqueue
from ..speech.base import speak_with_fallback
from ..state import Paths, snoozed_until
from ..summarize import CHILD_ENV_VAR


@dataclass
class Context:
    paths: Paths
    config: config_module.Config
    pack: Pack
    mode: str
    project_dir: str
    namespace: str
    session: str
    agent: str = CLAUDE

    @property
    def label(self) -> str:
        return label_for(self.agent, label(self.project_dir, self.namespace))


def is_child() -> bool:
    """True inside our own summarizer invocation, where every hook must do nothing."""
    return os.environ.get(CHILD_ENV_VAR) == "1"


def read_payload(source: Optional[Path]) -> dict:
    try:
        raw = source.read_text() if source else sys.stdin.read()
        data = json.loads(raw)
    except Exception:  # noqa: BLE001 - a malformed payload must not crash a hook
        return {}
    return data if isinstance(data, dict) else {}


def label(project_dir: str, namespace: str) -> str:
    return os.path.basename(project_dir.rstrip("/")) or project_dir


def build_context(
    payload: dict,
    paths: Optional[Paths] = None,
    agent: str = CLAUDE,
    project_dir: Optional[str] = None,
) -> Context:
    paths = paths or Paths.default()
    paths.ensure()
    config = config_module.load(paths)
    project_dir = project_dir or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    namespace = os.path.basename(os.environ.get("CLAUDE_CONFIG_DIR", ".claude").rstrip("/"))
    mode = config_module.resolve_mode(
        paths,
        project_dir=project_dir,
        namespace=namespace,
        default_mode=config.mode,
        snoozed=snoozed_until(paths) is not None,
    )
    return Context(
        paths=paths,
        config=config,
        pack=load_pack(config.language),
        mode=mode,
        project_dir=project_dir,
        namespace=namespace,
        session=str(payload.get("session_id", "unknown")),
        agent=agent,
    )


def summarise(context: Context, text: str) -> str:
    """Condense a reply, and say out loud when that could not be done.

    A summariser that quietly returns nothing is exactly the silent degradation this
    design exists to avoid: the fixed phrase is spoken, the entry looks fine, and the
    reason - a missing CLI, a timeout - is invisible. It is recorded instead.
    """
    from .. import summarize

    answer = summarize.run(text, context.pack, model=context.config.model)
    if answer:
        health.clear(context.paths, component="summariser")
        return answer

    if summarize.claude_binary() is None:
        health.record(context.paths, "summariser", "the claude CLI could not be found")
    return context.pack.phrase("summary.fallback")


def emit(
    context: Context,
    kind: str,
    text: str,
    banner: Optional[str] = None,
    priority: int = 1,
    notifier: Optional[Callable[..., None]] = None,
    worker: Optional[Callable[[], None]] = None,
) -> None:
    """Route one message to history, a banner and the speech queue as the mode dictates."""
    if not text.strip():
        return

    history.add(
        context.paths,
        kind=kind,
        label=context.label,
        text=text,
        directory=context.project_dir,
        namespace=context.namespace,
        agent=context.agent,
    )
    context.paths.state_dir.mkdir(parents=True, exist_ok=True)
    (context.paths.state_dir / "last-text").write_text(text)

    if context.mode in ("notify", "both"):
        send = notifier or _default_notifier
        try:
            send(title=f"{context.label}", body=banner or text, group=f"cvoice-{context.session}")
        except Exception as error:  # noqa: BLE001
            health.record(context.paths, "notify", str(error))

    if context.mode in ("voice", "both"):
        enqueue(context.paths, Item(priority=priority, label=context.label, session=context.session, text=text))
        (worker or spawn_worker)()


def _default_notifier(title: str, body: str, group: str) -> None:
    from ..notify.macos import send

    send(title=title, body=body, group=group)


def make_speaker(paths: Paths, engines: List[object], sink: Optional[Callable[[str], None]] = None):
    """Build the callable the queue drains through.

    The project name is spoken only when it differs from the previous utterance: with one
    agent talking it would be noise, with several it is the only way to tell them apart.
    """

    def speak(text: str, item: Item) -> None:
        last = ""
        try:
            last = paths.last_label_file.read_text()
        except FileNotFoundError:
            pass
        spoken = f"{item.label}. {text}" if item.label and item.label != last else text
        paths.last_label_file.parent.mkdir(parents=True, exist_ok=True)
        paths.last_label_file.write_text(item.label)

        if sink is not None:
            sink(spoken)
            return

        interrupted = []
        used = speak_with_fallback(
            engines,
            spoken,
            on_error=lambda name, error: health.record(paths, name, str(error)),
            on_success=lambda name: health.clear(paths, component=name),
            on_unavailable=lambda name: health.record(paths, name, "not installed or not reachable"),
            on_interrupted=lambda name: interrupted.append(name),
        )
        if used is None and not interrupted:
            health.record(paths, "speech", "every engine failed")

    return speak


def detach(hook_name: str, payload: dict) -> None:
    """Re-enter this hook in a background process so the session is never held up."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(payload, handle)
    handle.close()
    subprocess.Popen(
        [sys.executable, "-m", "cvoice.cli", "hook", hook_name, "--payload", handle.name, "--detached"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def spawn_worker() -> None:
    subprocess.Popen(
        [sys.executable, "-m", "cvoice.cli", "worker"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
