"""Append-only record of everything reported, so any message can be replayed later."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import List, Optional

from .state import Paths

KEEP_DEFAULT = 200
# Idle nudges carry no information after the fact and used to crowd out real content.
EPHEMERAL_KINDS = {"notice"}


@dataclass
class Entry:
    id: str
    ts: float
    kind: str
    label: str
    text: str
    directory: str = ""
    namespace: str = ""


def _new_id() -> str:
    return f"{time.time():016.5f}"


def _lines(paths: Paths) -> List[str]:
    try:
        return paths.history_file.read_text().splitlines()
    except FileNotFoundError:
        return []


def _parse(line: str) -> Optional[Entry]:
    try:
        return Entry(**json.loads(line))
    except (json.JSONDecodeError, TypeError):
        return None


def add(
    paths: Paths,
    kind: str,
    label: str,
    text: str,
    directory: str = "",
    namespace: str = "",
    keep: int = KEEP_DEFAULT,
) -> Optional[Entry]:
    if kind in EPHEMERAL_KINDS:
        return None

    lines = _lines(paths)
    if lines:
        last = _parse(lines[-1])
        if last is not None and last.text == text:
            return None

    entry = Entry(
        id=_new_id(),
        ts=time.time(),
        kind=kind,
        label=label,
        text=text,
        directory=directory,
        namespace=namespace,
    )
    lines.append(json.dumps(asdict(entry), ensure_ascii=False))
    paths.history_file.parent.mkdir(parents=True, exist_ok=True)
    paths.history_file.write_text("\n".join(lines[-keep:]) + "\n")
    return entry


def recent(paths: Paths, limit: int = 15) -> List[Entry]:
    entries = [entry for entry in (_parse(line) for line in _lines(paths)) if entry]
    return list(reversed(entries))[:limit]


def get(paths: Paths, entry_id: str) -> Optional[Entry]:
    for entry in recent(paths, limit=KEEP_DEFAULT):
        if entry.id == entry_id:
            return entry
    return None
