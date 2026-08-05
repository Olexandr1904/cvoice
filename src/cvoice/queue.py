"""The speech queue.

One utterance at a time, machine-wide, so parallel Claude sessions and aliases never
talk over each other. Ordering is encoded in the filename: priority first, then a
fixed-width timestamp, so a plain sort is both by urgency and by arrival.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from .state import Paths


# Last-resort guard: nothing this long should ever reach the speakers, whatever put
# it in the queue.
HARD_CAP = 700


@dataclass
class Item:
    priority: int  # 0 = needs attention now, 1 = end-of-turn summary
    label: str
    session: str
    text: str
    flags: str = ""  # "force" speaks even while paused


def enqueue(paths: Paths, item: Item) -> Optional[Path]:
    if not item.text.strip():
        return None

    paths.queue_dir.mkdir(parents=True, exist_ok=True)
    name = f"{item.priority}-{time.time():016.5f}-{os.getpid()}.json"
    target = paths.queue_dir / name
    partial = target.with_suffix(".json.part")
    payload = asdict(item)
    payload["text"] = item.text.strip()[:HARD_CAP]
    partial.write_text(json.dumps(payload, ensure_ascii=False))
    partial.rename(target)
    return target


def pending(paths: Paths) -> List[Path]:
    try:
        files = [path for path in paths.queue_dir.iterdir() if path.suffix == ".json"]
    except FileNotFoundError:
        return []
    return sorted(files, key=lambda path: path.name)


def read_item(path: Path) -> Item:
    return Item(**json.loads(path.read_text()))


from contextlib import contextmanager
from typing import Iterator


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by someone else
    return True


def _try_mkdir(paths: Paths) -> bool:
    try:
        paths.lock_dir.mkdir(parents=True)
    except FileExistsError:
        return False
    # Write via a temp file + atomic rename so a concurrent reader can never observe
    # a truncated-but-not-yet-written pid file (plain write_text() truncates first,
    # which is exactly the window a competing thread/process could misread as "no
    # owner recorded" and mistake for a stale lock).
    pid_file = paths.lock_dir / "pid"
    tmp = pid_file.with_suffix(".tmp")
    tmp.write_text(str(os.getpid()))
    tmp.rename(pid_file)
    return True


@contextmanager
def lock(paths: Paths) -> Iterator[bool]:
    """Machine-wide mutex built on atomic mkdir.

    Yields True when this process owns the lock. A directory left behind by a crashed
    worker is reclaimed by checking the pid recorded inside it.
    """
    acquired = _try_mkdir(paths)
    if not acquired:
        try:
            owner_raw = (paths.lock_dir / "pid").read_text().strip()
            owner = int(owner_raw)
        except (FileNotFoundError, ValueError):
            # The directory exists but its pid file has not landed yet (or is
            # unreadable mid-write): someone else is mid-acquisition, not dead.
            # Treating this as "stale" would let a second thread/process steal the
            # lock out from under its real owner.
            owner = None
        if owner is not None and not _process_alive(owner):
            _remove_lock(paths)
            acquired = _try_mkdir(paths)
    try:
        yield acquired
    finally:
        if acquired:
            _remove_lock(paths)


def _remove_lock(paths: Paths) -> None:
    for child in list(paths.lock_dir.glob("*")) if paths.lock_dir.exists() else []:
        child.unlink(missing_ok=True)
    try:
        paths.lock_dir.rmdir()
    except (FileNotFoundError, OSError):
        pass


from typing import Callable

Speaker = Callable[[str, Item], None]


def _clear(paths: Paths) -> None:
    for path in pending(paths):
        path.unlink(missing_ok=True)


def _drain_once(
    paths: Paths,
    speaker: Speaker,
    is_paused: Callable[[], bool],
    is_hard_muted: Callable[[], bool],
) -> int:
    spoken = 0
    while True:
        queued = pending(paths)
        if not queued:
            return spoken
        path = queued[0]
        try:
            item = read_item(path)
        except (json.JSONDecodeError, TypeError):
            path.unlink(missing_ok=True)
            continue
        path.unlink(missing_ok=True)

        # A hard mute is a live condition of the room - someone is recording - and no
        # explicit request may talk over it. A snooze is a timer the user set earlier,
        # so an explicit replay is allowed to override that one.
        if is_hard_muted():
            _clear(paths)
            return spoken

        # Paused mid-drain: drop what is queued rather than say it late. State is
        # re-read for every single utterance.
        if item.flags != "force" and is_paused():
            _clear(paths)
            return spoken

        try:
            speaker(item.text, item)
        except Exception:  # noqa: BLE001 - one bad utterance must not stop the queue
            pass
        spoken += 1


def drain(
    paths: Paths,
    speaker: Speaker,
    is_paused: Callable[[], bool] = lambda: False,
    is_hard_muted: Callable[[], bool] = lambda: False,
) -> int:
    """Speak everything queued. Returns how many utterances this call handled.

    Returns 0 immediately if another process holds the lock - that process will pick up
    whatever we queued.
    """
    with lock(paths) as acquired:
        if not acquired:
            return 0
        spoken = _drain_once(paths, speaker, is_paused, is_hard_muted)

    # Something may have been queued between the last check and releasing the lock.
    if pending(paths):
        with lock(paths) as acquired:
            if acquired:
                spoken += _drain_once(paths, speaker, is_paused, is_hard_muted)
    return spoken
