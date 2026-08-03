"""Import the bash prototype's data.

The old directory is never modified: it stays a working fallback until the user deletes
it themselves.
"""

from __future__ import annotations

import json
from pathlib import Path

from .history import Entry
from .state import Paths

KNOWN_FIELDS = set(Entry.__dataclass_fields__)


def migrate(old_root: Path, paths: Paths) -> int:
    """Returns how many history entries were imported."""
    source = Path(old_root) / "history.jsonl"
    try:
        lines = source.read_text().splitlines()
    except (FileNotFoundError, OSError):
        return 0

    existing = set()
    try:
        for line in paths.history_file.read_text().splitlines():
            try:
                existing.add(json.loads(line)["id"])
            except (json.JSONDecodeError, KeyError):
                continue
    except FileNotFoundError:
        pass

    imported = []
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("id") in existing:
            continue
        cleaned = {key: value for key, value in record.items() if key in KNOWN_FIELDS}
        cleaned.setdefault("label", "")
        cleaned.setdefault("text", "")
        if not cleaned.get("text"):
            continue
        imported.append(json.dumps(cleaned, ensure_ascii=False))

    if imported:
        with paths.history_file.open("a") as handle:
            handle.write("\n".join(imported) + "\n")
    return len(imported)
