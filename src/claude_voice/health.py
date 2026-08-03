"""Failure journal.

Nothing in this tool raises at the user. Every component that degrades records why it
degraded here, and the menu bar turns that into a warning icon with a reason.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .state import Paths


@dataclass
class Failure:
    component: str
    error: str
    ts: float


def _read(paths: Paths) -> Dict[str, dict]:
    try:
        data = json.loads(paths.health_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(paths: Paths, data: Dict[str, dict]) -> None:
    paths.health_file.parent.mkdir(parents=True, exist_ok=True)
    paths.health_file.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def record(paths: Paths, component: str, error: str) -> None:
    data = _read(paths)
    data[component] = {"error": str(error)[:200], "ts": time.time()}
    _write(paths, data)


def failures(paths: Paths) -> List[Failure]:
    return [
        Failure(component=name, error=entry.get("error", ""), ts=entry.get("ts", 0.0))
        for name, entry in sorted(_read(paths).items())
    ]


def clear(paths: Paths, component: Optional[str] = None) -> None:
    if component is None:
        paths.health_file.unlink(missing_ok=True)
        return
    data = _read(paths)
    data.pop(component, None)
    _write(paths, data)
