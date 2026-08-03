# claude-voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `~/.claude-tts` bash prototype as a tested, publishable Python package that reports Claude Code activity through macOS banners, neural speech and a menu-bar item.

**Architecture:** A Python package holds all logic; Claude Code hooks call a three-line bash shim that execs the package's console entry point. State lives in `~/.claude-voice/`. A machine-wide file lock guarantees exactly one utterance at a time across every Claude alias. Every component failure is recorded and degraded through a fallback chain instead of raised.

**Tech Stack:** Python 3.9+, pytest, `edge-tts` (Azure neural voices), macOS `say`/`afplay`/`terminal-notifier`, SwiftBar, GitHub Actions on `macos-latest`.

**Spec:** `docs/superpowers/specs/2026-08-03-claude-voice-design.md`

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/claude_voice/state.py` | Filesystem layout: every path the tool uses, plus snooze |
| `src/claude_voice/config.py` | Config file loading and the project > alias > global cascade |
| `src/claude_voice/history.py` | Append-only JSONL of everything reported |
| `src/claude_voice/health.py` | Failure journal and doctor checks |
| `src/claude_voice/queue.py` | Speech queue, machine-wide lock, drain loop |
| `src/claude_voice/speech/base.py` | Engine protocol and fallback chain |
| `src/claude_voice/speech/translit.py` | Latin to target-script conversion |
| `src/claude_voice/speech/macos_say.py` | Built-in `say` engine |
| `src/claude_voice/speech/edge.py` | Neural engine with audio cache |
| `src/claude_voice/notify/macos.py` | Banner delivery |
| `src/claude_voice/i18n/__init__.py` | Phrase packs, summarizer prompt, language detection |
| `src/claude_voice/summarize.py` | `claude -p` wrapper |
| `src/claude_voice/hooks/common.py` | Payload parsing, guards, detach, emit |
| `src/claude_voice/hooks/{stop,question,notification,prompt_submit}.py` | One hook each |
| `src/claude_voice/menubar/render.py` | SwiftBar menu text |
| `src/claude_voice/cli.py` | Argument parsing and user commands |
| `install.sh`, `uninstall.sh` | Bootstrap and removal |

---

## Task 1: Package skeleton and CI

**Files:**
- Create: `pyproject.toml`, `src/claude_voice/__init__.py`, `tests/test_package.py`, `.github/workflows/ci.yml`, `.gitignore`

- [ ] **Step 1: Write the failing test**

`tests/test_package.py`:

```python
def test_package_exposes_version():
    import claude_voice

    assert claude_voice.__version__
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_package.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice'`

- [ ] **Step 3: Write minimal implementation**

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "claude-voice"
version = "0.1.0"
description = "Spoken and banner reporting for Claude Code on macOS"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.9"
dependencies = [
    "edge-tts>=6.1",
    "tomli>=2.0; python_version<'3.11'",
    "tomli-w>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=7.4"]

[project.scripts]
claude-voice = "claude_voice.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
claude_voice = ["i18n/*.toml", "menubar/*.sh"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`src/claude_voice/__init__.py`:

```python
"""Spoken and banner reporting for Claude Code."""

__version__ = "0.1.0"
```

`.gitignore`:

```
__pycache__/
*.egg-info/
.venv/
.pytest_cache/
dist/
```

`.github/workflows/ci.yml`:

```yaml
name: ci
on: [push, pull_request]

jobs:
  test:
    runs-on: macos-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e ".[dev]"
      - run: pytest -v
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pip install -e ".[dev]" && python3 -m pytest tests/test_package.py -v`
Expected: PASS, 1 passed

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src tests .github .gitignore
git commit -m "chore: package skeleton with CI"
```

---

## Task 2: Filesystem layout

**Files:**
- Create: `src/claude_voice/state.py`, `tests/test_state.py`

- [ ] **Step 1: Write the failing test**

`tests/test_state.py`:

```python
from claude_voice.state import Paths


def test_paths_derive_from_root(tmp_path):
    paths = Paths(root=tmp_path)

    assert paths.config_file == tmp_path / "config.toml"
    assert paths.queue_dir == tmp_path / "queue"
    assert paths.history_file == tmp_path / "history.jsonl"


def test_ensure_creates_directories(tmp_path):
    paths = Paths(root=tmp_path / "home")
    paths.ensure()

    assert paths.queue_dir.is_dir()
    assert paths.cache_dir.is_dir()
    assert paths.scopes_dir.is_dir()
    assert paths.state_dir.is_dir()


def test_default_root_is_dot_claude_voice(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CLAUDE_VOICE_HOME", raising=False)

    assert Paths.default().root == tmp_path / ".claude-voice"


def test_env_var_overrides_default_root(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_VOICE_HOME", str(tmp_path / "custom"))

    assert Paths.default().root == tmp_path / "custom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.state'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/state.py`:

```python
"""Where everything lives on disk.

Every module takes its paths from here rather than building them, so tests can
point the whole tool at a temporary directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    root: Path

    @classmethod
    def default(cls) -> "Paths":
        override = os.environ.get("CLAUDE_VOICE_HOME")
        if override:
            return cls(root=Path(override))
        return cls(root=Path(os.environ.get("HOME", "~")).expanduser() / ".claude-voice")

    @property
    def config_file(self) -> Path:
        return self.root / "config.toml"

    @property
    def queue_dir(self) -> Path:
        return self.root / "queue"

    @property
    def lock_dir(self) -> Path:
        return self.root / "lock"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def scopes_dir(self) -> Path:
        return self.root / "scopes"

    @property
    def state_dir(self) -> Path:
        return self.root / "state"

    @property
    def history_file(self) -> Path:
        return self.root / "history.jsonl"

    @property
    def health_file(self) -> Path:
        return self.root / "health.json"

    @property
    def snooze_file(self) -> Path:
        return self.state_dir / "snooze"

    @property
    def seen_file(self) -> Path:
        return self.state_dir / "seen-until"

    @property
    def last_label_file(self) -> Path:
        return self.state_dir / "last-label"

    def ensure(self) -> None:
        for directory in (self.root, self.queue_dir, self.cache_dir, self.scopes_dir, self.state_dir):
            directory.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_state.py -v`
Expected: PASS, 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/state.py tests/test_state.py
git commit -m "feat: filesystem layout"
```

---

## Task 3: Snooze

**Files:**
- Modify: `src/claude_voice/state.py` (append to the module)
- Modify: `tests/test_state.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_state.py`:

```python
import time

from claude_voice.state import clear_snooze, set_snooze, snoozed_until


def test_no_snooze_by_default(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()

    assert snoozed_until(paths) is None


def test_set_snooze_returns_future_timestamp(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()

    until = set_snooze(paths, minutes=30)

    assert until > time.time() + 29 * 60
    assert snoozed_until(paths) == until


def test_expired_snooze_reads_as_none_and_removes_file(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    paths.snooze_file.write_text(str(time.time() - 1))

    assert snoozed_until(paths) is None
    assert not paths.snooze_file.exists()


def test_clear_snooze(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    set_snooze(paths, minutes=5)

    clear_snooze(paths)

    assert snoozed_until(paths) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_state.py -v`
Expected: FAIL with `ImportError: cannot import name 'clear_snooze'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/claude_voice/state.py`:

```python
import time
from typing import Optional


def snoozed_until(paths: Paths) -> Optional[float]:
    """Epoch second the mute expires, or None. Expired files are cleaned up here."""
    try:
        raw = paths.snooze_file.read_text().strip()
    except FileNotFoundError:
        return None
    try:
        until = float(raw)
    except ValueError:
        paths.snooze_file.unlink(missing_ok=True)
        return None
    if until <= time.time():
        paths.snooze_file.unlink(missing_ok=True)
        return None
    return until


def set_snooze(paths: Paths, minutes: float) -> float:
    until = time.time() + minutes * 60
    paths.snooze_file.parent.mkdir(parents=True, exist_ok=True)
    paths.snooze_file.write_text(str(until))
    return until


def clear_snooze(paths: Paths) -> None:
    paths.snooze_file.unlink(missing_ok=True)
```

Note: `Path.unlink(missing_ok=...)` requires Python 3.8+, which the project already requires.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_state.py -v`
Expected: PASS, 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/state.py tests/test_state.py
git commit -m "feat: snooze with automatic expiry"
```

---

## Task 4: Configuration file

**Files:**
- Create: `src/claude_voice/config.py`, `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`tests/test_config.py`:

```python
from claude_voice.config import Config, load, save
from claude_voice.state import Paths


def test_defaults_are_neutral(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()

    config = load(paths)

    assert config.language == "en"
    assert config.mode == "notify"
    assert config.engine == "edge"


def test_load_reads_values(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    paths.config_file.write_text(
        'language = "uk"\n'
        'mode = "both"\n'
        'engine = "say"\n'
        "[edge]\n"
        'voice = "uk-UA-PolinaNeural"\n'
        'rate = "+10%"\n'
        "[say]\n"
        'voice = "Lesya"\n'
        "rate = 190\n"
    )

    config = load(paths)

    assert config.language == "uk"
    assert config.mode == "both"
    assert config.engine == "say"
    assert config.edge_voice == "uk-UA-PolinaNeural"
    assert config.edge_rate == "+10%"
    assert config.say_voice == "Lesya"
    assert config.say_rate == 190


def test_save_then_load_roundtrips(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()

    save(paths, Config(language="uk", mode="voice", say_rate=200))

    config = load(paths)
    assert config.language == "uk"
    assert config.mode == "voice"
    assert config.say_rate == 200


def test_unknown_mode_falls_back_to_off(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    paths.config_file.write_text('mode = "shout"\n')

    assert load(paths).mode == "off"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.config'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/config.py`:

```python
"""Configuration file and output modes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on older interpreters
    import tomli as tomllib

import tomli_w

from .state import Paths

MODES: Tuple[str, ...] = ("off", "notify", "voice", "both")


@dataclass
class Config:
    language: str = "en"
    mode: str = "notify"
    engine: str = "edge"
    edge_voice: str = "en-US-AriaNeural"
    edge_rate: str = "+0%"
    say_voice: str = "Samantha"
    say_rate: int = 180


def normalise_mode(value: str) -> str:
    """Anything unrecognised means silence: never guess and speak by accident."""
    return value if value in MODES else "off"


def load(paths: Paths) -> Config:
    try:
        data = tomllib.loads(paths.config_file.read_text())
    except FileNotFoundError:
        return Config()
    edge = data.get("edge", {})
    say = data.get("say", {})
    defaults = Config()
    return Config(
        language=data.get("language", defaults.language),
        mode=normalise_mode(data.get("mode", defaults.mode)),
        engine=data.get("engine", defaults.engine),
        edge_voice=edge.get("voice", defaults.edge_voice),
        edge_rate=edge.get("rate", defaults.edge_rate),
        say_voice=say.get("voice", defaults.say_voice),
        say_rate=int(say.get("rate", defaults.say_rate)),
    )


def save(paths: Paths, config: Config) -> None:
    payload = {
        "language": config.language,
        "mode": config.mode,
        "engine": config.engine,
        "edge": {"voice": config.edge_voice, "rate": config.edge_rate},
        "say": {"voice": config.say_voice, "rate": config.say_rate},
    }
    paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_bytes(tomli_w.dumps(payload).encode())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: PASS, 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/config.py tests/test_config.py
git commit -m "feat: configuration file"
```

---

## Task 5: Scope cascade

**Files:**
- Modify: `src/claude_voice/config.py` (append)
- Modify: `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
from claude_voice.config import clear_scope, resolve_mode, scope_file, set_scope


def test_global_default_applies_when_no_scope_set(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()

    mode = resolve_mode(paths, project_dir="/work/app", namespace=".claude", default_mode="notify")

    assert mode == "notify"


def test_alias_scope_overrides_global(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    set_scope(paths, "alias", ".claude-work", "off")

    mode = resolve_mode(paths, project_dir="/work/app", namespace=".claude-work", default_mode="voice")

    assert mode == "off"


def test_project_scope_overrides_alias(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    set_scope(paths, "alias", ".claude", "off")
    set_scope(paths, "project", "/work/app", "voice")

    mode = resolve_mode(paths, project_dir="/work/app", namespace=".claude", default_mode="notify")

    assert mode == "voice"


def test_scope_for_another_project_is_ignored(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    set_scope(paths, "project", "/work/other", "voice")

    mode = resolve_mode(paths, project_dir="/work/app", namespace=".claude", default_mode="off")

    assert mode == "off"


def test_clear_scope_falls_back_to_broader_level(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    set_scope(paths, "project", "/work/app", "voice")
    clear_scope(paths, "project", "/work/app")

    mode = resolve_mode(paths, project_dir="/work/app", namespace=".claude", default_mode="notify")

    assert mode == "notify"


def test_snoozed_forces_off(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    set_scope(paths, "project", "/work/app", "both")

    mode = resolve_mode(
        paths, project_dir="/work/app", namespace=".claude", default_mode="both", snoozed=True
    )

    assert mode == "off"


def test_scope_file_name_is_filesystem_safe(tmp_path):
    paths = Paths(root=tmp_path)

    path = scope_file(paths, "project", "/Users/me/My Repo")

    assert path.parent == paths.scopes_dir
    assert "/" not in path.name
    assert " " not in path.name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'clear_scope'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/claude_voice/config.py`:

```python
import re
from pathlib import Path
from typing import Optional

_UNSAFE = re.compile(r"[^A-Za-z0-9]+")


def scope_file(paths: Paths, kind: str, value: str) -> Path:
    """One file per scope. Project settings live here, never inside the user's repos."""
    slug = _UNSAFE.sub("-", value).strip("-")
    return paths.scopes_dir / f"{kind}-{slug}"


def set_scope(paths: Paths, kind: str, value: str, mode: str) -> None:
    path = scope_file(paths, kind, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(normalise_mode(mode))


def clear_scope(paths: Paths, kind: str, value: str) -> None:
    scope_file(paths, kind, value).unlink(missing_ok=True)


def _read_scope(paths: Paths, kind: str, value: str) -> Optional[str]:
    try:
        raw = scope_file(paths, kind, value).read_text().strip()
    except FileNotFoundError:
        return None
    return normalise_mode(raw) if raw else None


def resolve_mode(
    paths: Paths,
    project_dir: str,
    namespace: str,
    default_mode: str,
    snoozed: bool = False,
) -> str:
    """Most specific level with an explicit value wins: project > alias > global."""
    if snoozed:
        return "off"
    for kind, value in (("project", project_dir), ("alias", namespace)):
        mode = _read_scope(paths, kind, value)
        if mode is not None:
            return mode
    return normalise_mode(default_mode)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config.py -v`
Expected: PASS, 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/config.py tests/test_config.py
git commit -m "feat: project > alias > global mode cascade"
```

---

## Task 6: History

**Files:**
- Create: `src/claude_voice/history.py`, `tests/test_history.py`

- [ ] **Step 1: Write the failing test**

`tests/test_history.py`:

```python
from claude_voice.history import add, get, recent
from claude_voice.state import Paths


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def test_add_returns_entry_with_id(tmp_path):
    paths = _paths(tmp_path)

    entry = add(paths, kind="tldr", label="app", text="Done.", directory="/work/app", namespace=".claude")

    assert entry is not None
    assert entry.id
    assert entry.text == "Done."
    assert entry.kind == "tldr"


def test_notices_are_never_stored(tmp_path):
    paths = _paths(tmp_path)

    assert add(paths, kind="notice", label="app", text="Waiting for you.") is None
    assert recent(paths) == []


def test_consecutive_duplicates_are_collapsed(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="Same thing")

    assert add(paths, kind="tldr", label="app", text="Same thing") is None
    assert len(recent(paths)) == 1


def test_recent_returns_newest_first(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="first")
    add(paths, kind="question", label="app", text="second")

    entries = recent(paths, limit=10)

    assert [entry.text for entry in entries] == ["second", "first"]


def test_get_finds_entry_by_id(tmp_path):
    paths = _paths(tmp_path)
    entry = add(paths, kind="tldr", label="app", text="findable")

    assert get(paths, entry.id).text == "findable"


def test_get_returns_none_for_unknown_id(tmp_path):
    paths = _paths(tmp_path)

    assert get(paths, "nope") is None


def test_file_is_trimmed_to_the_keep_limit(tmp_path):
    paths = _paths(tmp_path)
    for index in range(12):
        add(paths, kind="tldr", label="app", text=f"line {index}", keep=5)

    assert len(paths.history_file.read_text().strip().splitlines()) <= 5


def test_corrupt_line_does_not_break_reading(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="good")
    with paths.history_file.open("a") as handle:
        handle.write("{not json\n")

    assert [entry.text for entry in recent(paths)] == ["good"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_history.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.history'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/history.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_history.py -v`
Expected: PASS, 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/history.py tests/test_history.py
git commit -m "feat: history with dedupe and trimming"
```

---

## Task 7: Queue items and ordering

**Files:**
- Create: `src/claude_voice/queue.py`, `tests/test_queue.py`

- [ ] **Step 1: Write the failing test**

`tests/test_queue.py`:

```python
from claude_voice.queue import Item, enqueue, pending, read_item
from claude_voice.state import Paths


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def test_enqueue_writes_a_file(tmp_path):
    paths = _paths(tmp_path)

    enqueue(paths, Item(priority=1, label="app", session="s1", text="hello"))

    assert len(pending(paths)) == 1


def test_read_item_roundtrips(tmp_path):
    paths = _paths(tmp_path)
    enqueue(paths, Item(priority=0, label="app", session="s1", text="hi", flags="force"))

    item = read_item(pending(paths)[0])

    assert item.text == "hi"
    assert item.flags == "force"
    assert item.priority == 0


def test_questions_come_before_summaries(tmp_path):
    paths = _paths(tmp_path)
    enqueue(paths, Item(priority=1, label="app", session="s1", text="summary"))
    enqueue(paths, Item(priority=0, label="app", session="s1", text="question"))

    order = [read_item(path).text for path in pending(paths)]

    assert order == ["question", "summary"]


def test_same_priority_keeps_chronological_order(tmp_path):
    paths = _paths(tmp_path)
    for index in range(5):
        enqueue(paths, Item(priority=1, label="app", session="s1", text=f"item {index}"))

    order = [read_item(path).text for path in pending(paths)]

    assert order == [f"item {index}" for index in range(5)]


def test_empty_text_is_not_queued(tmp_path):
    paths = _paths(tmp_path)

    assert enqueue(paths, Item(priority=1, label="app", session="s1", text="   ")) is None
    assert pending(paths) == []


def test_partial_files_are_ignored(tmp_path):
    paths = _paths(tmp_path)
    (paths.queue_dir / "1-000.json.part").write_text("{}")

    assert pending(paths) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_queue.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.queue'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/queue.py`:

```python
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
    partial.write_text(json.dumps(asdict(item), ensure_ascii=False))
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_queue.py -v`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/queue.py tests/test_queue.py
git commit -m "feat: speech queue with priority ordering"
```

---

## Task 8: The lock

**Files:**
- Modify: `src/claude_voice/queue.py` (append)
- Modify: `tests/test_queue.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_queue.py`:

```python
import os

from claude_voice.queue import lock


def test_lock_is_acquired_when_free(tmp_path):
    paths = _paths(tmp_path)

    with lock(paths) as acquired:
        assert acquired is True


def test_second_lock_is_refused_while_held(tmp_path):
    paths = _paths(tmp_path)

    with lock(paths) as first:
        assert first is True
        with lock(paths) as second:
            assert second is False


def test_lock_is_released_on_exit(tmp_path):
    paths = _paths(tmp_path)

    with lock(paths):
        pass

    with lock(paths) as acquired:
        assert acquired is True


def test_lock_is_released_even_when_body_raises(tmp_path):
    paths = _paths(tmp_path)

    try:
        with lock(paths):
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    with lock(paths) as acquired:
        assert acquired is True


def test_stale_lock_from_dead_process_is_reclaimed(tmp_path):
    paths = _paths(tmp_path)
    paths.lock_dir.mkdir(parents=True, exist_ok=True)
    # PID 0 is never a live user process, so this stands in for a crashed worker.
    (paths.lock_dir / "pid").write_text("0")

    with lock(paths) as acquired:
        assert acquired is True


def test_live_owner_pid_is_respected(tmp_path):
    paths = _paths(tmp_path)
    paths.lock_dir.mkdir(parents=True, exist_ok=True)
    (paths.lock_dir / "pid").write_text(str(os.getpid()))

    with lock(paths) as acquired:
        assert acquired is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_queue.py -v`
Expected: FAIL with `ImportError: cannot import name 'lock'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/claude_voice/queue.py`:

```python
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
    # Write the pid via temp file + atomic rename. A plain write_text() truncates
    # first, and that window is exactly what a competing process misreads as "no
    # owner recorded" - see the note on lock() below.
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

    The unreadable-pid case must NOT be treated as stale. Creating the directory and
    recording the pid cannot be one atomic step, so a competitor can find the directory
    present but the pid not yet landed. Reading that as "owner is dead" lets it delete
    the directory the real owner is holding and re-create it, and then two processes
    both believe they hold the lock. Only an explicitly recorded pid that fails the
    liveness check may trigger a reclaim.
    """
    acquired = _try_mkdir(paths)
    if not acquired:
        try:
            owner = int((paths.lock_dir / "pid").read_text().strip())
        except (FileNotFoundError, ValueError):
            owner = None  # mid-acquisition, not dead
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_queue.py -v`
Expected: PASS, 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/queue.py tests/test_queue.py
git commit -m "feat: machine-wide lock with stale-owner reclaim"
```

---

## Task 9: Draining the queue

This is the riskiest logic in the tool and the reason the prototype needed rewriting. It comes before anything that depends on it.

**Files:**
- Modify: `src/claude_voice/queue.py` (append)
- Create: `tests/test_queue_drain.py`

- [ ] **Step 1: Write the failing test**

`tests/test_queue_drain.py`:

```python
import threading
import time

from claude_voice.queue import Item, drain, enqueue, pending
from claude_voice.state import Paths


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


class RecordingSpeaker:
    """Records the interval each utterance occupied, so overlap can be detected."""

    def __init__(self, delay=0.02):
        self.delay = delay
        self.spoken = []
        self.intervals = []
        self._guard = threading.Lock()

    def __call__(self, text, item):
        start = time.monotonic()
        time.sleep(self.delay)
        end = time.monotonic()
        with self._guard:
            self.spoken.append(text)
            self.intervals.append((start, end))


def test_drain_speaks_everything_in_order(tmp_path):
    paths = _paths(tmp_path)
    speaker = RecordingSpeaker(delay=0)
    enqueue(paths, Item(priority=1, label="app", session="s", text="one"))
    enqueue(paths, Item(priority=1, label="app", session="s", text="two"))

    spoken = drain(paths, speaker)

    assert spoken == 2
    assert speaker.spoken == ["one", "two"]
    assert pending(paths) == []


def test_drain_returns_zero_when_lock_is_held(tmp_path):
    from claude_voice.queue import lock

    paths = _paths(tmp_path)
    enqueue(paths, Item(priority=1, label="app", session="s", text="one"))
    speaker = RecordingSpeaker(delay=0)

    with lock(paths):
        assert drain(paths, speaker) == 0

    assert len(pending(paths)) == 1


def test_pause_drops_queued_items(tmp_path):
    paths = _paths(tmp_path)
    speaker = RecordingSpeaker(delay=0)
    enqueue(paths, Item(priority=1, label="app", session="s", text="stale"))

    drain(paths, speaker, is_paused=lambda: True)

    assert speaker.spoken == []
    assert pending(paths) == []


def test_forced_item_is_spoken_even_while_paused(tmp_path):
    paths = _paths(tmp_path)
    speaker = RecordingSpeaker(delay=0)
    enqueue(paths, Item(priority=0, label="app", session="s", text="replay", flags="force"))

    drain(paths, speaker, is_paused=lambda: True)

    assert speaker.spoken == ["replay"]


def test_speaker_failure_does_not_block_the_rest(tmp_path):
    paths = _paths(tmp_path)
    calls = []

    def flaky(text, item):
        calls.append(text)
        if text == "bad":
            raise RuntimeError("engine down")

    enqueue(paths, Item(priority=1, label="app", session="s", text="bad"))
    enqueue(paths, Item(priority=1, label="app", session="s", text="good"))

    drain(paths, flaky)

    assert calls == ["bad", "good"]
    assert pending(paths) == []


def test_item_queued_during_drain_is_still_spoken(tmp_path):
    paths = _paths(tmp_path)
    spoken = []

    def speaker(text, item):
        spoken.append(text)
        if text == "first":
            enqueue(paths, Item(priority=1, label="app", session="s", text="late"))

    enqueue(paths, Item(priority=1, label="app", session="s", text="first"))

    drain(paths, speaker)

    assert spoken == ["first", "late"]


def test_only_one_utterance_at_a_time_across_threads(tmp_path):
    paths = _paths(tmp_path)
    speaker = RecordingSpeaker(delay=0.02)
    for index in range(6):
        enqueue(paths, Item(priority=1, label="app", session="s", text=f"item {index}"))

    threads = [threading.Thread(target=drain, args=(paths, speaker)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(speaker.spoken) == 6
    ordered = sorted(speaker.intervals)
    for (_, first_end), (second_start, _) in zip(ordered, ordered[1:]):
        assert first_end <= second_start + 1e-6, "two utterances overlapped"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_queue_drain.py -v`
Expected: FAIL with `ImportError: cannot import name 'drain'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/claude_voice/queue.py`:

```python
from typing import Callable

Speaker = Callable[[str, Item], None]


def _clear(paths: Paths) -> None:
    for path in pending(paths):
        path.unlink(missing_ok=True)


def _drain_once(paths: Paths, speaker: Speaker, is_paused: Callable[[], bool]) -> int:
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

        # Paused mid-drain: drop what is queued rather than say it late. An explicit
        # replay still goes through. State is re-read for every single utterance.
        if item.flags != "force" and is_paused():
            _clear(paths)
            return spoken

        try:
            speaker(item.text, item)
        except Exception:  # noqa: BLE001 - one bad utterance must not stop the queue
            pass
        spoken += 1


def drain(paths: Paths, speaker: Speaker, is_paused: Callable[[], bool] = lambda: False) -> int:
    """Speak everything queued. Returns how many utterances this call handled.

    Returns 0 immediately if another process holds the lock - that process will pick up
    whatever we queued.
    """
    with lock(paths) as acquired:
        if not acquired:
            return 0
        spoken = _drain_once(paths, speaker, is_paused)

    # Something may have been queued between the last check and releasing the lock.
    if pending(paths):
        with lock(paths) as acquired:
            if acquired:
                spoken += _drain_once(paths, speaker, is_paused)
    return spoken
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_queue_drain.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/queue.py tests/test_queue_drain.py
git commit -m "feat: queue drain with pause, force and single-speaker guarantee"
```

---

## Task 10: Failure journal

**Files:**
- Create: `src/claude_voice/health.py`, `tests/test_health.py`

- [ ] **Step 1: Write the failing test**

`tests/test_health.py`:

```python
from claude_voice.health import clear, failures, record
from claude_voice.state import Paths


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def test_no_failures_initially(tmp_path):
    assert failures(_paths(tmp_path)) == []


def test_record_stores_component_and_reason(tmp_path):
    paths = _paths(tmp_path)

    record(paths, "edge-tts", "no network")

    stored = failures(paths)
    assert len(stored) == 1
    assert stored[0].component == "edge-tts"
    assert stored[0].error == "no network"
    assert stored[0].ts > 0


def test_repeated_failure_updates_rather_than_duplicates(tmp_path):
    paths = _paths(tmp_path)

    record(paths, "edge-tts", "no network")
    record(paths, "edge-tts", "timeout")

    stored = failures(paths)
    assert len(stored) == 1
    assert stored[0].error == "timeout"


def test_different_components_are_kept_separately(tmp_path):
    paths = _paths(tmp_path)

    record(paths, "edge-tts", "no network")
    record(paths, "terminal-notifier", "missing")

    assert {failure.component for failure in failures(paths)} == {"edge-tts", "terminal-notifier"}


def test_clear_removes_everything(tmp_path):
    paths = _paths(tmp_path)
    record(paths, "edge-tts", "no network")

    clear(paths)

    assert failures(paths) == []


def test_clear_one_component(tmp_path):
    paths = _paths(tmp_path)
    record(paths, "edge-tts", "no network")
    record(paths, "say", "voice missing")

    clear(paths, component="edge-tts")

    assert [failure.component for failure in failures(paths)] == ["say"]


def test_corrupt_health_file_reads_as_empty(tmp_path):
    paths = _paths(tmp_path)
    paths.health_file.write_text("{not json")

    assert failures(paths) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.health'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/health.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_health.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/health.py tests/test_health.py
git commit -m "feat: failure journal"
```

---

## Task 11: Engine protocol and fallback chain

**Files:**
- Create: `src/claude_voice/speech/__init__.py`, `src/claude_voice/speech/base.py`, `tests/test_speech_base.py`

- [ ] **Step 1: Write the failing test**

`tests/test_speech_base.py`:

```python
from claude_voice.speech.base import SpeechError, speak_with_fallback


class FakeEngine:
    def __init__(self, name, available=True, fails=False):
        self.name = name
        self._available = available
        self._fails = fails
        self.spoken = []

    def available(self):
        return self._available

    def speak(self, text):
        if self._fails:
            raise SpeechError(f"{self.name} is broken")
        self.spoken.append(text)


def test_first_working_engine_is_used():
    first, second = FakeEngine("edge"), FakeEngine("say")

    used = speak_with_fallback([first, second], "hello")

    assert used == "edge"
    assert first.spoken == ["hello"]
    assert second.spoken == []


def test_unavailable_engine_is_skipped():
    first, second = FakeEngine("edge", available=False), FakeEngine("say")

    used = speak_with_fallback([first, second], "hello")

    assert used == "say"


def test_failing_engine_falls_through_to_the_next():
    first, second = FakeEngine("edge", fails=True), FakeEngine("say")

    used = speak_with_fallback([first, second], "hello")

    assert used == "say"
    assert second.spoken == ["hello"]


def test_all_engines_failing_returns_none():
    engines = [FakeEngine("edge", fails=True), FakeEngine("say", fails=True)]

    assert speak_with_fallback(engines, "hello") is None


def test_failures_are_reported_to_the_callback():
    reported = []
    engines = [FakeEngine("edge", fails=True), FakeEngine("say")]

    speak_with_fallback(engines, "hello", on_error=lambda name, err: reported.append((name, str(err))))

    assert reported[0][0] == "edge"
    assert "broken" in reported[0][1]


def test_success_reports_recovery_for_the_engine_used():
    recovered = []
    engines = [FakeEngine("edge")]

    speak_with_fallback(engines, "hello", on_success=recovered.append)

    assert recovered == ["edge"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_speech_base.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.speech'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/speech/__init__.py`:

```python
"""Speech engines."""
```

`src/claude_voice/speech/base.py`:

```python
"""Engine protocol and the fallback chain.

Losing the voice is acceptable; losing the message is not. Each engine that cannot
speak hands over to the next one, and every handover is reported so the menu bar can
show what degraded.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional


class SpeechError(Exception):
    """Raised by an engine that could not speak this text."""


class Engine:
    """Structural protocol. Implementations need `name`, `available()` and `speak()`."""

    name: str

    def available(self) -> bool:  # pragma: no cover - interface only
        raise NotImplementedError

    def speak(self, text: str) -> None:  # pragma: no cover - interface only
        raise NotImplementedError


def speak_with_fallback(
    engines: Iterable[Engine],
    text: str,
    on_error: Optional[Callable[[str, Exception], None]] = None,
    on_success: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """Try each engine in order. Returns the name of the one that spoke, or None."""
    for engine in engines:
        try:
            if not engine.available():
                continue
            engine.speak(text)
        except Exception as error:  # noqa: BLE001 - any engine failure is a handover
            if on_error is not None:
                on_error(engine.name, error)
            continue
        if on_success is not None:
            on_success(engine.name)
        return engine.name
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_speech_base.py -v`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/speech tests/test_speech_base.py
git commit -m "feat: engine protocol and fallback chain"
```

---

## Task 12: Transliteration

**Files:**
- Create: `src/claude_voice/speech/translit.py`, `tests/test_translit.py`

- [ ] **Step 1: Write the failing test**

`tests/test_translit.py`:

```python
from claude_voice.speech.translit import Table, has_latin_words, transliterate

TABLE = Table(
    # "sync" must be listed: phonetically "Sync" becomes "сйнк" (y -> й), which is why the
    # production pack in Task 16 spells common terms out instead of relying on the fallback.
    terms={
        "pull request": "пул реквест",
        "manager": "менеджер",
        "login": "логін",
        "api": "апі",
        "sync": "синк",
    },
    digraphs=[("sh", "ш"), ("ch", "ч"), ("ck", "к")],
    letters={
        "a": "а", "b": "б", "c": "к", "d": "д", "e": "е", "f": "ф", "g": "ґ", "h": "г",
        "i": "і", "j": "дж", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
        "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в", "x": "кс",
        "y": "й", "z": "з",
    },
)


def test_text_without_latin_is_unchanged():
    assert transliterate("Готово, тести зелені.", TABLE) == "Готово, тести зелені."


def test_known_term_uses_the_dictionary():
    assert transliterate("Відкрив pull request", TABLE) == "Відкрив пул реквест"


def test_multiword_term_wins_over_its_parts():
    result = transliterate("pull request", TABLE)

    assert result == "пул реквест"


def test_unknown_word_is_transliterated_phonetically():
    assert transliterate("blob", TABLE) == "блоб"


def test_camel_case_is_split_into_words():
    assert transliterate("SyncManager", TABLE) == "синк менеджер"


def test_short_acronym_is_spelled_out():
    assert transliterate("URL", TABLE) == "у-р-л"


def test_known_acronym_beats_spelling_it_out():
    assert transliterate("API", TABLE) == "апі"


def test_matching_is_case_insensitive():
    assert transliterate("Login", TABLE) == "логін"


def test_has_latin_words_ignores_short_fragments():
    assert has_latin_words("Готово, все ок") is False
    assert has_latin_words("Готово, SyncManager") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_translit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.speech.translit'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/speech/translit.py`:

```python
"""Last line of defence before the built-in macOS voice.

A voice tuned for one language reads latin letter by letter, which is unintelligible.
Known technical terms come from the language pack's dictionary; anything else is
converted phonetically. Neural engines do not need this - they pronounce English well
enough on their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")
_LATIN_RUN = re.compile(r"[A-Za-z]{3,}")
_CAMEL_PARTS = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z']*|[a-z']+")


@dataclass
class Table:
    terms: Dict[str, str] = field(default_factory=dict)
    digraphs: List[Tuple[str, str]] = field(default_factory=list)
    letters: Dict[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.letters


def has_latin_words(text: str) -> bool:
    return bool(_LATIN_RUN.search(text))


def _phonetic(word: str, table: Table) -> str:
    lowered = word.lower()
    if word.isupper() and len(word) <= 4:
        return "-".join(table.letters.get(char, char) for char in lowered)
    for source, target in table.digraphs:
        lowered = lowered.replace(source, target)
    return "".join(table.letters.get(char, char) for char in lowered)


def _one_word(word: str, table: Table) -> str:
    known = table.terms.get(word.lower())
    if known:
        return known
    parts = _CAMEL_PARTS.findall(word)
    if len(parts) > 1:
        return " ".join(table.terms.get(part.lower(), _phonetic(part, table)) for part in parts)
    return _phonetic(word, table)


def transliterate(text: str, table: Table) -> str:
    if table.empty:
        return text
    # Multi-word terms first, longest first, so "pull request" wins over "pull".
    for term in sorted((term for term in table.terms if " " in term), key=len, reverse=True):
        text = re.sub(re.escape(term), table.terms[term], text, flags=re.IGNORECASE)
    return _LATIN_WORD.sub(lambda match: _one_word(match.group(0), table), text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_translit.py -v`
Expected: PASS, 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/speech/translit.py tests/test_translit.py
git commit -m "feat: transliteration for the built-in voice"
```

---

## Task 13: Built-in `say` engine

**Files:**
- Create: `src/claude_voice/speech/macos_say.py`, `tests/test_say_engine.py`

- [ ] **Step 1: Write the failing test**

`tests/test_say_engine.py`:

```python
import claude_voice.speech.macos_say as macos_say
from claude_voice.speech.base import SpeechError
from claude_voice.speech.macos_say import SayEngine
from claude_voice.speech.translit import Table

TABLE = Table(terms={"manager": "менеджер"}, digraphs=[], letters={"a": "а", "s": "с", "y": "й", "n": "н", "c": "к"})


class FakeRun:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)

        class Result:
            pass

        result = Result()
        result.returncode = self.returncode
        result.stderr = self.stderr
        return result


def test_available_requires_the_say_binary(monkeypatch):
    monkeypatch.setattr(macos_say.shutil, "which", lambda name: None)

    assert SayEngine(voice="Lesya", rate=180).available() is False


def test_speak_passes_voice_and_rate(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(macos_say.subprocess, "run", run)

    SayEngine(voice="Lesya", rate=190).speak("Готово")

    assert run.calls[0][:5] == ["say", "-v", "Lesya", "-r", "190"]
    assert run.calls[0][-1] == "Готово"


def test_latin_is_transliterated_before_speaking(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(macos_say.subprocess, "run", run)

    SayEngine(voice="Lesya", rate=180, table=TABLE).speak("Виправив SyncManager")

    assert "SyncManager" not in run.calls[0][-1]


def test_text_without_latin_is_untouched(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(macos_say.subprocess, "run", run)

    SayEngine(voice="Lesya", rate=180, table=TABLE).speak("Готово, тести зелені")

    assert run.calls[0][-1] == "Готово, тести зелені"


def test_non_zero_exit_raises_speech_error(monkeypatch):
    monkeypatch.setattr(macos_say.subprocess, "run", FakeRun(returncode=1, stderr="voice not found"))

    try:
        SayEngine(voice="Nope", rate=180).speak("hello")
    except SpeechError as error:
        assert "voice not found" in str(error)
    else:
        raise AssertionError("expected SpeechError")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_say_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.speech.macos_say'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/speech/macos_say.py`:

```python
"""The synthesiser built into macOS. Always available offline, sounds mechanical."""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from .base import SpeechError
from .translit import Table, has_latin_words, transliterate


class SayEngine:
    name = "say"

    def __init__(self, voice: str, rate: int, table: Optional[Table] = None) -> None:
        self.voice = voice
        self.rate = rate
        self.table = table

    def available(self) -> bool:
        return shutil.which("say") is not None

    def speak(self, text: str) -> None:
        # This engine cannot pronounce latin at all, so it gets the transliterated text.
        # Banners and history keep the readable original.
        if self.table is not None and has_latin_words(text):
            text = transliterate(text, self.table)
        result = subprocess.run(
            ["say", "-v", self.voice, "-r", str(self.rate), "--", text],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SpeechError(result.stderr.strip() or f"say exited {result.returncode}")
```

Note: the test asserts `argv[-1]` is the text, which holds because `--` precedes it.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_say_engine.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/speech/macos_say.py tests/test_say_engine.py
git commit -m "feat: macOS say engine"
```

---

## Task 14: Neural engine with cache

**Files:**
- Create: `src/claude_voice/speech/edge.py`, `tests/test_edge_engine.py`

- [ ] **Step 1: Write the failing test**

`tests/test_edge_engine.py`:

```python
import claude_voice.speech.edge as edge_module
from claude_voice.speech.base import SpeechError
from claude_voice.speech.edge import EdgeEngine


class FakeRunner:
    """Stands in for both edge-tts and afplay. No network is ever touched in tests."""

    def __init__(self, synth_ok=True, play_ok=True):
        self.synth_ok = synth_ok
        self.play_ok = play_ok
        self.synth_calls = 0
        self.played = []

    def __call__(self, argv, **kwargs):
        class Result:
            pass

        result = Result()
        result.stderr = ""
        if argv[0] == "edge-tts":
            self.synth_calls += 1
            result.returncode = 0 if self.synth_ok else 1
            if self.synth_ok:
                target = argv[argv.index("--write-media") + 1]
                with open(target, "wb") as handle:
                    handle.write(b"fake mp3")
            else:
                result.stderr = "network unreachable"
        else:
            self.played.append(argv[-1])
            result.returncode = 0 if self.play_ok else 1
        return result


def _engine(tmp_path, voice="uk-UA-PolinaNeural"):
    return EdgeEngine(voice=voice, rate="+0%", cache_dir=tmp_path / "cache")


def test_available_requires_the_edge_tts_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(edge_module.shutil, "which", lambda name: None)

    assert _engine(tmp_path).available() is False


def test_speak_synthesises_then_plays(monkeypatch, tmp_path):
    runner = FakeRunner()
    monkeypatch.setattr(edge_module.subprocess, "run", runner)

    _engine(tmp_path).speak("Готово")

    assert runner.synth_calls == 1
    assert runner.played and runner.played[0].endswith(".mp3")


def test_second_identical_utterance_reuses_the_cache(monkeypatch, tmp_path):
    runner = FakeRunner()
    monkeypatch.setattr(edge_module.subprocess, "run", runner)
    engine = _engine(tmp_path)

    engine.speak("Готово")
    engine.speak("Готово")

    assert runner.synth_calls == 1
    assert len(runner.played) == 2


def test_different_voice_is_cached_separately(monkeypatch, tmp_path):
    runner = FakeRunner()
    monkeypatch.setattr(edge_module.subprocess, "run", runner)

    _engine(tmp_path, voice="a").speak("Готово")
    _engine(tmp_path, voice="b").speak("Готово")

    assert runner.synth_calls == 2


def test_synthesis_failure_raises_and_leaves_no_partial_file(monkeypatch, tmp_path):
    monkeypatch.setattr(edge_module.subprocess, "run", FakeRunner(synth_ok=False))
    engine = _engine(tmp_path)

    try:
        engine.speak("Готово")
    except SpeechError as error:
        assert "network unreachable" in str(error)
    else:
        raise AssertionError("expected SpeechError")

    assert list((tmp_path / "cache").glob("*")) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_edge_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.speech.edge'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/speech/edge.py`:

```python
"""Azure neural voices through the endpoint Edge's Read Aloud uses.

No API key and no cost, but it needs the network - hence the fallback chain. Audio is
cached by a hash of text, voice and rate, so replaying a message is free and instant.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

from .base import SpeechError


class EdgeEngine:
    name = "edge-tts"

    def __init__(self, voice: str, rate: str, cache_dir: Path) -> None:
        self.voice = voice
        self.rate = rate
        self.cache_dir = Path(cache_dir)

    def available(self) -> bool:
        return shutil.which("edge-tts") is not None

    def _cache_path(self, text: str) -> Path:
        digest = hashlib.md5(f"{text}|{self.voice}|{self.rate}".encode()).hexdigest()
        return self.cache_dir / f"{digest}.mp3"

    def _synthesise(self, text: str, target: Path) -> None:
        partial = target.with_suffix(".part")
        result = subprocess.run(
            [
                "edge-tts",
                "--voice", self.voice,
                f"--rate={self.rate}",
                "--text", text,
                "--write-media", str(partial),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not partial.exists() or partial.stat().st_size == 0:
            partial.unlink(missing_ok=True)
            raise SpeechError(result.stderr.strip() or "edge-tts produced no audio")
        partial.rename(target)

    def speak(self, text: str) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        audio = self._cache_path(text)
        if not audio.exists() or audio.stat().st_size == 0:
            self._synthesise(text, audio)
        result = subprocess.run(["afplay", str(audio)], capture_output=True, text=True)
        if result.returncode != 0:
            raise SpeechError(result.stderr.strip() or f"afplay exited {result.returncode}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_edge_engine.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/speech/edge.py tests/test_edge_engine.py
git commit -m "feat: neural edge-tts engine with audio cache"
```

---

## Task 15: Banners

**Files:**
- Create: `src/claude_voice/notify/__init__.py`, `src/claude_voice/notify/macos.py`, `tests/test_notify.py`

- [ ] **Step 1: Write the failing test**

`tests/test_notify.py`:

```python
import claude_voice.notify.macos as notify_module
from claude_voice.notify.macos import NotifyError, send, terminal_bundle_id


class FakeRun:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)

        class Result:
            pass

        result = Result()
        result.returncode = self.returncode
        result.stderr = "notifier failed"
        return result


def test_uses_terminal_notifier_when_present(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(notify_module.shutil, "which", lambda name: "/usr/local/bin/terminal-notifier")
    monkeypatch.setattr(notify_module.subprocess, "run", run)

    send("Title", "Body", group="g1")

    argv = run.calls[0]
    assert argv[0] == "terminal-notifier"
    assert "Title" in argv and "Body" in argv and "g1" in argv


def test_no_sound_flag_is_never_passed(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(notify_module.shutil, "which", lambda name: "/usr/local/bin/terminal-notifier")
    monkeypatch.setattr(notify_module.subprocess, "run", run)

    send("Title", "Body", group="g1")

    assert "-sound" not in run.calls[0]


def test_falls_back_to_osascript(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(notify_module.shutil, "which", lambda name: None if name == "terminal-notifier" else "/usr/bin/osascript")
    monkeypatch.setattr(notify_module.subprocess, "run", run)

    send("Title", "Body", group="g1")

    assert run.calls[0][0] == "osascript"


def test_raises_when_nothing_can_deliver(monkeypatch):
    monkeypatch.setattr(notify_module.shutil, "which", lambda name: None)

    try:
        send("Title", "Body", group="g1")
    except NotifyError:
        pass
    else:
        raise AssertionError("expected NotifyError")


def test_known_terminal_maps_to_bundle_id(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "iTerm.app")

    assert terminal_bundle_id() == "com.googlecode.iterm2"


def test_unknown_terminal_maps_to_none(monkeypatch):
    monkeypatch.setenv("TERM_PROGRAM", "something-else")

    assert terminal_bundle_id() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_notify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.notify'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/notify/__init__.py`:

```python
"""Banner delivery."""
```

`src/claude_voice/notify/macos.py`:

```python
"""Silent macOS banners.

No sound on purpose: the point is not to interrupt a call. Note that Focus / Do Not
Disturb suppresses banners entirely even though delivery succeeds, which is why the
menu bar carries the unread counter.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional

TERMINAL_BUNDLES = {
    "iTerm.app": "com.googlecode.iterm2",
    "Apple_Terminal": "com.apple.Terminal",
    "vscode": "com.microsoft.VSCode",
    "ghostty": "com.mitchellh.ghostty",
    "WarpTerminal": "dev.warp.Warp-Stable",
}


class NotifyError(Exception):
    """No notification mechanism could deliver the message."""


def terminal_bundle_id() -> Optional[str]:
    """Bundle id of the terminal this session runs in, so a click returns to it."""
    return TERMINAL_BUNDLES.get(os.environ.get("TERM_PROGRAM", ""))


def send(title: str, body: str, group: str = "claude-voice") -> None:
    if shutil.which("terminal-notifier"):
        argv = ["terminal-notifier", "-title", title, "-message", body, "-group", group]
        bundle = terminal_bundle_id()
        if bundle:
            argv += ["-activate", bundle]
    elif shutil.which("osascript"):
        script = f'display notification {body!r} with title {title!r}'
        argv = ["osascript", "-e", script]
    else:
        raise NotifyError("neither terminal-notifier nor osascript is available")

    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise NotifyError(result.stderr.strip() or f"{argv[0]} exited {result.returncode}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_notify.py -v`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/notify tests/test_notify.py
git commit -m "feat: silent macOS banners"
```

---

## Task 16: Language packs

**Design refinement over the spec:** the spec listed "no latin word of three or more
letters" as a separate condition for reading a reply verbatim. That rule cannot hold for a
latin-script language — an English pack would never read anything verbatim and would pay for
a summary every turn. The rule therefore moves *into* the pack: `detect.forbids` is a regex,
and the Ukrainian pack puts `[A-Za-z]{3,}` in it. One mechanism, both cases.

**Files:**
- Create: `src/claude_voice/i18n/__init__.py`, `src/claude_voice/i18n/en.toml`, `src/claude_voice/i18n/uk.toml`, `tests/test_i18n.py`

- [ ] **Step 1: Write the failing test**

`tests/test_i18n.py`:

```python
import pytest

from claude_voice.i18n import REQUIRED_PHRASES, available_languages, load


def test_english_pack_loads():
    pack = load("en")

    assert pack.language == "en"
    assert pack.phrase("waiting")


def test_unknown_language_raises():
    with pytest.raises(LookupError):
        load("kl")


def test_phrase_interpolates_arguments():
    pack = load("en")

    assert "Bash" in pack.phrase("permission.tool", tool="Bash")


def test_missing_placeholder_does_not_crash():
    pack = load("en")

    assert pack.phrase("permission.tool")  # no tool= given


@pytest.mark.parametrize("language", available_languages())
def test_every_pack_has_every_required_phrase(language):
    pack = load(language)

    missing = [key for key in REQUIRED_PHRASES if key not in pack.phrases]
    assert missing == [], f"{language} is missing {missing}"


@pytest.mark.parametrize("language", available_languages())
def test_every_pack_prompt_has_a_text_placeholder(language):
    assert "{text}" in load(language).summary_prompt


def test_english_accepts_english_and_rejects_cyrillic():
    pack = load("en")

    assert pack.matches_language("All tests passed, nothing left to do.") is True
    assert pack.matches_language("Готово, тести зелені") is False


def test_ukrainian_accepts_ukrainian():
    pack = load("uk")

    assert pack.matches_language("Готово, всі тести зелені") is True


def test_ukrainian_rejects_russian_letters():
    pack = load("uk")

    assert pack.matches_language("Готово, все тесты зелёные") is False


def test_ukrainian_rejects_text_with_latin_words():
    pack = load("uk")

    assert pack.matches_language("Готово, виправив SyncManager") is False


def test_ukrainian_pack_carries_a_translit_table():
    pack = load("uk")

    assert pack.translit_table.letters
    assert pack.translit_table.terms


def test_english_pack_needs_no_translit_table():
    assert load("en").translit_table.empty is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_i18n.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.i18n'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/i18n/__init__.py`:

```python
"""Language packs: spoken phrases, the summarizer prompt, and language detection.

Everything the user can hear lives in a pack, so adding a language never means touching
logic. A test asserts every pack carries every required key, which stops a language from
shipping half-translated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from ..speech.translit import Table

PACKS_DIR = Path(__file__).parent

REQUIRED_PHRASES = (
    "question.single",
    "question.with_text",
    "question.many",
    "plan.ready",
    "permission.tool",
    "permission.generic",
    "waiting",
    "summary.fallback",
    "voice.enabled",
    "test.phrase",
)


@dataclass
class Pack:
    language: str
    name: str
    phrases: Dict[str, str]
    summary_prompt: str
    requires: Optional[str] = None
    forbids: Optional[str] = None
    translit_table: Table = field(default_factory=Table)

    def phrase(self, key: str, **kwargs: object) -> str:
        template = self.phrases.get(key, key)
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            # A missing argument must never take the message down.
            return re.sub(r"\{[^}]*\}", "", template).strip()

    def matches_language(self, text: str) -> bool:
        """True when the text can be spoken as-is by this pack's voice."""
        if self.forbids and re.search(self.forbids, text):
            return False
        if not self.requires:
            return False  # a pack that declares nothing always summarizes
        return bool(re.search(self.requires, text))


def available_languages() -> List[str]:
    return sorted(path.stem for path in PACKS_DIR.glob("*.toml"))


def load(language: str) -> Pack:
    path = PACKS_DIR / f"{language}.toml"
    if not path.exists():
        raise LookupError(f"no language pack for {language!r}")
    data = tomllib.loads(path.read_text())
    detect = data.get("detect", {})
    translit = data.get("translit", {})
    return Pack(
        language=data["language"],
        name=data.get("name", data["language"]),
        phrases=data.get("phrases", {}),
        summary_prompt=data["summary_prompt"],
        requires=detect.get("requires"),
        forbids=detect.get("forbids"),
        translit_table=Table(
            terms=translit.get("terms", {}),
            digraphs=[tuple(pair) for pair in translit.get("digraphs", [])],
            letters=translit.get("letters", {}),
        ),
    )
```

`src/claude_voice/i18n/en.toml`:

```toml
language = "en"
name = "English"

[detect]
requires = "[A-Za-z]"
forbids = "[\\u0400-\\u04FF]"

[phrases]
"question.single" = "I have a question for you."
"question.with_text" = "I have a question. {question}"
"question.many" = "I have a few questions, check the terminal."
"plan.ready" = "The plan is ready, take a look."
"permission.tool" = "I need permission to use {tool}."
"permission.generic" = "I need your permission, check the terminal."
"waiting" = "Waiting for your answer."
"summary.fallback" = "The turn is done, the details are in the terminal."
"voice.enabled" = "Voice output is on."
"test.phrase" = "Connection check. This is the {voice} voice."

summary_prompt = """
This is an assistant's final reply in a terminal. Tell the user the outcome in one or two
short conversational sentences, at most 200 characters: what was done and what matters next.
No markdown, no file paths, no code, no preamble like "here is the summary".

===== BEGIN REPLY =====
{text}
===== END REPLY =====

Return only the summary sentence. Nothing else.
"""
```

`src/claude_voice/i18n/uk.toml`:

```toml
language = "uk"
name = "Ukrainian"

# Russian-specific letters disqualify the text outright; latin words of three or more
# letters do too, because the built-in voice cannot pronounce them.
[detect]
requires = "[іїєґІЇЄҐ]"
forbids = "[ыэъёЫЭЪЁ]|[A-Za-z]{3,}"

[phrases]
"question.single" = "У мене питання, глянь у термінал."
"question.with_text" = "У мене питання. {question}"
"question.many" = "У мене кілька питань, глянь у термінал."
"plan.ready" = "План готовий, глянь і скажи, йдемо чи ні."
"permission.tool" = "Потрібен дозвіл на {tool}."
"permission.generic" = "Потрібен твій дозвіл, глянь у термінал."
"waiting" = "Чекаю на твою відповідь."
"summary.fallback" = "Хід завершено, підсумок у терміналі."
"voice.enabled" = "Голос увімкнено."
"test.phrase" = "Перевірка звʼязку. Це голос {voice}."

summary_prompt = """
Це фінальна відповідь асистента в терміналі. Скажи користувачеві підсумок одним-двома
короткими реченнями розмовною українською, максимум 200 символів: що зроблено і що важливо
знати далі. Пиши виключно українською кирилицею, навіть якщо текст нижче іншою мовою.
Англійські терміни транслітеруй так, як їх вимовляють уголос. Без markdown, без шляхів до
файлів, без коду, без вступів.

===== ПОЧАТОК ВІДПОВІДІ =====
{text}
===== КІНЕЦЬ ВІДПОВІДІ =====

Поверни лише одну фразу-підсумок. Нічого більше.
"""

[translit]
digraphs = [
    ["sch", "ш"], ["tch", "ч"], ["ch", "ч"], ["sh", "ш"], ["th", "з"], ["ph", "ф"],
    ["ck", "к"], ["qu", "кв"], ["ee", "і"], ["oo", "у"], ["ou", "ау"], ["ea", "і"],
    ["ai", "ей"], ["ay", "ей"], ["ey", "ей"], ["oa", "оу"], ["ie", "і"], ["ng", "нг"],
    ["wh", "в"], ["kn", "н"],
]

[translit.terms]
"pull request" = "пул реквест"
"merge request" = "мердж реквест"
"code review" = "код ревʼю"
commit = "коміт"
branch = "бранч"
build = "білд"
release = "реліз"
deploy = "деплой"
test = "тест"
tests = "тести"
lint = "лінт"
linter = "лінтер"
config = "конфіг"
cache = "кеш"
retry = "ретрай"
crash = "креш"
fix = "фікс"
hook = "хук"
queue = "черга"
log = "лог"
api = "апі"
url = "юар-ел"
json = "джейсон"
npm = "ен-пі-ем"
gradle = "ґредл"
kotlin = "котлін"
python = "пайтон"
docker = "докер"
github = "ґітхаб"
gitlab = "ґітлаб"
git = "ґіт"
claude = "клод"
prompt = "промпт"
agent = "агент"
model = "модель"
settings = "налаштування"
login = "логін"
start = "старт"
class = "клас"
scope = "скоуп"
parser = "парсер"
manager = "менеджер"
handler = "хендлер"
service = "сервіс"
client = "клієнт"
server = "сервер"
request = "реквест"
response = "респонс"
unit = "юніт"
sync = "синк"

[translit.letters]
a = "а"
b = "б"
c = "к"
d = "д"
e = "е"
f = "ф"
g = "ґ"
h = "г"
i = "і"
j = "дж"
k = "к"
l = "л"
m = "м"
n = "н"
o = "о"
p = "п"
q = "к"
r = "р"
s = "с"
t = "т"
u = "у"
v = "в"
w = "в"
x = "кс"
y = "й"
z = "з"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_i18n.py -v`
Expected: PASS, 16 passed (the two parametrized tests run once per pack)

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/i18n tests/test_i18n.py
git commit -m "feat: English and Ukrainian language packs"
```

---

## Task 17: Summarizer

**Files:**
- Create: `src/claude_voice/summarize.py`, `tests/test_summarize.py`

- [ ] **Step 1: Write the failing test**

`tests/test_summarize.py`:

```python
import claude_voice.summarize as summarize_module
from claude_voice.i18n import load
from claude_voice.summarize import run

PACK = load("en")


class FakeRun:
    def __init__(self, stdout="Fixed the parser and added tests.", returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.calls = []
        self.env = None

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        self.env = kwargs.get("env")

        class Result:
            pass

        result = Result()
        result.returncode = self.returncode
        result.stdout = self.stdout
        result.stderr = ""
        return result


def test_returns_the_model_output(monkeypatch):
    monkeypatch.setattr(summarize_module.subprocess, "run", FakeRun())

    assert run("a long reply", PACK) == "Fixed the parser and added tests."


def test_reply_is_embedded_in_the_prompt_not_piped(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("REPLY-MARKER", PACK)

    prompt = fake.calls[0][-1]
    assert "REPLY-MARKER" in prompt
    assert "BEGIN REPLY" in prompt


def test_hooks_are_disabled_in_the_child(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("a reply", PACK)

    argv = fake.calls[0]
    assert "--settings" in argv
    assert '"disableAllHooks":true' in argv[argv.index("--settings") + 1].replace(" ", "")


def test_child_marker_env_var_is_set(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("a reply", PACK)

    assert fake.env["CLAUDE_VOICE_CHILD"] == "1"


def test_haiku_model_is_requested(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("a reply", PACK)

    argv = fake.calls[0]
    assert argv[argv.index("--model") + 1] == "haiku"


def test_long_reply_is_truncated_before_sending(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(summarize_module.subprocess, "run", fake)

    run("x" * 20000, PACK)

    assert len(fake.calls[0][-1]) < 12000


def test_non_zero_exit_returns_none(monkeypatch):
    monkeypatch.setattr(summarize_module.subprocess, "run", FakeRun(returncode=1))

    assert run("a reply", PACK) is None


def test_empty_output_returns_none(monkeypatch):
    monkeypatch.setattr(summarize_module.subprocess, "run", FakeRun(stdout="   \n"))

    assert run("a reply", PACK) is None


def test_markdown_is_stripped_from_the_answer(monkeypatch):
    monkeypatch.setattr(summarize_module.subprocess, "run", FakeRun(stdout="**Done**: fixed `parser.py`"))

    assert run("a reply", PACK) == "Done: fixed parser.py"


def test_timeout_returns_none(monkeypatch):
    def explode(argv, **kwargs):
        raise summarize_module.subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(summarize_module.subprocess, "run", explode)

    assert run("a reply", PACK) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_summarize.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.summarize'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/summarize.py`:

```python
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
CHILD_ENV_VAR = "CLAUDE_VOICE_CHILD"


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_summarize.py -v`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/summarize.py tests/test_summarize.py
git commit -m "feat: haiku summarizer with recursion guard"
```

---

## Task 18: Hook plumbing

**Files:**
- Create: `src/claude_voice/hooks/__init__.py`, `src/claude_voice/hooks/common.py`, `tests/test_hooks_common.py`

- [ ] **Step 1: Write the failing test**

`tests/test_hooks_common.py`:

```python
import json

import claude_voice.hooks.common as common
from claude_voice.config import Config
from claude_voice.i18n import load as load_pack
from claude_voice.queue import Item, pending, read_item
from claude_voice.state import Paths


def _context(tmp_path, mode="both", monkeypatch=None):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return common.Context(
        paths=paths,
        config=Config(language="en", mode=mode),
        pack=load_pack("en"),
        mode=mode,
        project_dir="/work/app",
        namespace=".claude",
        session="s1",
    )


def test_is_child_reads_the_env_var(monkeypatch):
    monkeypatch.setenv("CLAUDE_VOICE_CHILD", "1")

    assert common.is_child() is True


def test_is_child_false_without_the_env_var(monkeypatch):
    monkeypatch.delenv("CLAUDE_VOICE_CHILD", raising=False)

    assert common.is_child() is False


def test_read_payload_from_stdin(monkeypatch):
    import io

    monkeypatch.setattr(common.sys, "stdin", io.StringIO('{"session_id": "abc"}'))

    assert common.read_payload(None) == {"session_id": "abc"}


def test_read_payload_from_file(tmp_path):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text('{"session_id": "abc"}')

    assert common.read_payload(payload_file) == {"session_id": "abc"}


def test_read_payload_tolerates_garbage(tmp_path):
    payload_file = tmp_path / "payload.json"
    payload_file.write_text("not json")

    assert common.read_payload(payload_file) == {}


def test_label_is_the_project_folder_name():
    assert common.label("/work/my-app", ".claude") == "my-app"


def test_emit_records_history(tmp_path):
    context = _context(tmp_path)

    common.emit(context, kind="tldr", text="All done.", notifier=lambda *a, **k: None, worker=lambda: None)

    from claude_voice.history import recent

    assert [entry.text for entry in recent(context.paths)] == ["All done."]


def test_emit_queues_speech_in_voice_mode(tmp_path):
    context = _context(tmp_path, mode="voice")

    common.emit(context, kind="tldr", text="All done.", notifier=lambda *a, **k: None, worker=lambda: None)

    assert [read_item(path).text for path in pending(context.paths)] == ["All done."]


def test_emit_does_not_queue_speech_in_notify_mode(tmp_path):
    context = _context(tmp_path, mode="notify")
    sent = []

    common.emit(context, kind="tldr", text="All done.", notifier=lambda **kw: sent.append(kw), worker=lambda: None)

    assert pending(context.paths) == []
    assert sent and sent[0]["body"] == "All done."


def test_emit_prefers_the_banner_text_when_given(tmp_path):
    context = _context(tmp_path, mode="notify")
    sent = []

    common.emit(
        context,
        kind="question",
        text="I have a question.",
        banner="Which cache layer?",
        notifier=lambda **kw: sent.append(kw),
        worker=lambda: None,
    )

    assert sent[0]["body"] == "Which cache layer?"


def test_emit_records_a_notifier_failure_in_health(tmp_path):
    from claude_voice.health import failures

    context = _context(tmp_path, mode="notify")

    def broken(**kwargs):
        raise RuntimeError("no notifier")

    common.emit(context, kind="tldr", text="All done.", notifier=broken, worker=lambda: None)

    assert [failure.component for failure in failures(context.paths)] == ["notify"]


def test_speaker_announces_the_project_only_when_it_changes(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    said = []
    speaker = common.make_speaker(paths, engines=[], sink=said.append)

    speaker("first", Item(priority=1, label="app", session="s", text="first"))
    speaker("second", Item(priority=1, label="app", session="s", text="second"))
    speaker("third", Item(priority=1, label="other", session="s", text="third"))

    assert said == ["app. first", "second", "other. third"]


def test_detach_spawns_a_background_process(tmp_path, monkeypatch):
    spawned = {}

    def fake_popen(argv, **kwargs):
        spawned["argv"] = argv
        spawned["kwargs"] = kwargs

        class Handle:
            pass

        return Handle()

    monkeypatch.setattr(common.subprocess, "Popen", fake_popen)

    common.detach("stop", {"session_id": "abc"})

    assert "hook" in spawned["argv"] and "stop" in spawned["argv"]
    assert spawned["kwargs"]["start_new_session"] is True
    payload_path = spawned["argv"][spawned["argv"].index("--payload") + 1]
    assert json.loads(open(payload_path).read())["session_id"] == "abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hooks_common.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.hooks'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/hooks/__init__.py`:

```python
"""One module per Claude Code hook event."""
```

`src/claude_voice/hooks/common.py`:

```python
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

    @property
    def label(self) -> str:
        return label(self.project_dir, self.namespace)


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


def build_context(payload: dict, paths: Optional[Paths] = None) -> Context:
    paths = paths or Paths.default()
    paths.ensure()
    config = config_module.load(paths)
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
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
    )


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
    )
    context.paths.state_dir.mkdir(parents=True, exist_ok=True)
    (context.paths.state_dir / "last-text").write_text(text)

    if context.mode in ("notify", "both"):
        send = notifier or _default_notifier
        try:
            send(title=f"{context.label}", body=banner or text, group=f"claude-voice-{context.session}")
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

        used = speak_with_fallback(
            engines,
            spoken,
            on_error=lambda name, error: health.record(paths, name, str(error)),
            on_success=lambda name: health.clear(paths, component=name),
        )
        if used is None:
            health.record(paths, "speech", "every engine failed")

    return speak


def detach(hook_name: str, payload: dict) -> None:
    """Re-enter this hook in a background process so the session is never held up."""
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
    json.dump(payload, handle)
    handle.close()
    subprocess.Popen(
        [sys.executable, "-m", "claude_voice.cli", "hook", hook_name, "--payload", handle.name, "--detached"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def spawn_worker() -> None:
    subprocess.Popen(
        [sys.executable, "-m", "claude_voice.cli", "worker"],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_hooks_common.py -v`
Expected: PASS, 13 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/hooks tests/test_hooks_common.py
git commit -m "feat: shared hook plumbing"
```

---

## Task 19: Stop hook

**Files:**
- Create: `src/claude_voice/hooks/stop.py`, `tests/test_hook_stop.py`, `tests/conftest.py`

- [ ] **Step 1: Write the failing test**

`tests/conftest.py`:

```python
import json

import pytest


@pytest.fixture
def transcript(tmp_path):
    """Writes a Claude Code transcript and returns its path."""

    def build(*texts, sidechain=False):
        path = tmp_path / "transcript.jsonl"
        lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}})]
        for text in texts:
            lines.append(
                json.dumps(
                    {
                        "type": "assistant",
                        "isSidechain": sidechain,
                        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
                    }
                )
            )
        path.write_text("\n".join(lines) + "\n")
        return path

    return build
```

`tests/test_hook_stop.py`:

```python
import claude_voice.hooks.stop as stop_hook
from claude_voice.config import Config, save
from claude_voice.history import recent
from claude_voice.state import Paths


def _prepare(tmp_path, mode="notify", language="en"):
    paths = Paths(root=tmp_path / "home")
    paths.ensure()
    save(paths, Config(language=language, mode=mode))
    return paths


def _run(paths, transcript_path, monkeypatch, summary="Summarised."):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/Users/me/.claude")
    monkeypatch.delenv("CLAUDE_VOICE_CHILD", raising=False)
    monkeypatch.setattr(stop_hook.summarize, "run", lambda text, pack, **kw: summary)
    stop_hook.handle(
        {"session_id": "s1", "transcript_path": str(transcript_path)},
        paths=paths,
        notifier=lambda **kwargs: None,
        worker=lambda: None,
    )


def test_last_assistant_message_becomes_history(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, transcript("first reply", "final reply"), monkeypatch, summary="Short summary.")

    assert [entry.text for entry in recent(paths)] == ["Short summary."]


def test_short_reply_in_the_target_language_is_used_verbatim(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, transcript("All tests pass, nothing else to do."), monkeypatch, summary="SHOULD NOT BE USED")

    assert [entry.text for entry in recent(paths)] == ["All tests pass, nothing else to do."]


def test_long_reply_is_summarised(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, transcript("word " * 200), monkeypatch, summary="Summarised.")

    assert [entry.text for entry in recent(paths)] == ["Summarised."]


def test_markdown_is_stripped_before_deciding(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, transcript("All tests pass, `nothing` else to do."), monkeypatch, summary="unused")

    assert "`" not in recent(paths)[0].text


def test_summariser_failure_falls_back_to_a_phrase(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, transcript("word " * 200), monkeypatch, summary=None)

    assert recent(paths)[0].text == "The turn is done, the details are in the terminal."


def test_sidechain_messages_are_ignored(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)
    path = transcript("subagent chatter", sidechain=True)

    _run(paths, path, monkeypatch)

    assert recent(paths) == []


def test_same_reply_twice_is_not_repeated(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path)
    path = transcript("All tests pass, nothing else to do.")

    _run(paths, path, monkeypatch)
    _run(paths, path, monkeypatch)

    assert len(recent(paths)) == 1


def test_mode_off_does_nothing(tmp_path, transcript, monkeypatch):
    paths = _prepare(tmp_path, mode="off")

    _run(paths, transcript("All tests pass."), monkeypatch)

    assert recent(paths) == []


def test_missing_transcript_is_survivable(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, tmp_path / "nope.jsonl", monkeypatch)

    assert recent(paths) == []


def test_entry_point_detaches_and_returns_immediately(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(stop_hook.common, "detach", lambda name, payload: calls.append(name))
    monkeypatch.delenv("CLAUDE_VOICE_CHILD", raising=False)

    stop_hook.main({"session_id": "s1"}, detached=False)

    assert calls == ["stop"]


def test_entry_point_does_nothing_inside_the_summariser_child(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(stop_hook.common, "detach", lambda name, payload: calls.append(name))
    monkeypatch.setenv("CLAUDE_VOICE_CHILD", "1")

    stop_hook.main({"session_id": "s1"}, detached=False)

    assert calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hook_stop.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.hooks.stop'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/hooks/stop.py`:

```python
"""End of turn: say what was done.

A reply short enough and already in the target language is read as it stands; anything
else is condensed by the summarizer. The work happens in a detached process because the
summarizer takes seconds and the session must not wait for it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from .. import summarize
from ..state import Paths
from . import common

VERBATIM_LIMIT = 300


def last_assistant_text(transcript_path: Path) -> str:
    """Text blocks of the last main-thread assistant message."""
    try:
        lines = transcript_path.read_text().splitlines()
    except (FileNotFoundError, OSError):
        return ""
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("type") != "assistant" or record.get("isSidechain"):
            continue
        content = record.get("message", {}).get("content", [])
        parts = [block.get("text", "") for block in content if block.get("type") == "text"]
        joined = " ".join(part for part in parts if part).strip()
        if joined:
            return joined
    return ""


def handle(
    payload: dict,
    paths: Optional[Paths] = None,
    notifier: Optional[Callable[..., None]] = None,
    worker: Optional[Callable[[], None]] = None,
) -> None:
    context = common.build_context(payload, paths=paths)
    if context.mode == "off":
        return

    transcript = payload.get("transcript_path")
    if not transcript:
        return

    raw = last_assistant_text(Path(transcript))
    clean = summarize.strip_markdown(raw)
    if not clean:
        return

    if len(clean) <= VERBATIM_LIMIT and context.pack.matches_language(clean):
        spoken = clean
    else:
        spoken = summarize.run(clean, context.pack) or context.pack.phrase("summary.fallback")

    common.emit(context, kind="tldr", text=spoken, priority=1, notifier=notifier, worker=worker)


def main(payload: dict, detached: bool = False) -> None:
    if common.is_child():
        return
    if detached:
        handle(payload)
    else:
        common.detach("stop", payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_hook_stop.py -v`
Expected: PASS, 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/hooks/stop.py tests/test_hook_stop.py tests/conftest.py
git commit -m "feat: stop hook with detached summarisation"
```

---

## Task 20: Question hook

**Files:**
- Create: `src/claude_voice/hooks/question.py`, `tests/test_hook_question.py`

- [ ] **Step 1: Write the failing test**

`tests/test_hook_question.py`:

```python
import claude_voice.hooks.question as question_hook
from claude_voice.config import Config, save
from claude_voice.history import recent
from claude_voice.state import Paths


def _paths(tmp_path, language="en", mode="both"):
    paths = Paths(root=tmp_path / "home")
    paths.ensure()
    save(paths, Config(language=language, mode=mode))
    return paths


def _run(paths, payload, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")
    monkeypatch.delenv("CLAUDE_VOICE_CHILD", raising=False)
    sent = []
    question_hook.handle(payload, paths=paths, notifier=lambda **kw: sent.append(kw), worker=lambda: None)
    return sent


def test_plan_mode_announces_the_plan(tmp_path, monkeypatch):
    paths = _paths(tmp_path)

    _run(paths, {"session_id": "s", "tool_name": "ExitPlanMode", "tool_input": {}}, monkeypatch)

    assert recent(paths)[0].text == "The plan is ready, take a look."


def test_question_in_the_target_language_is_spoken_in_full(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    payload = {
        "session_id": "s",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "Which cache layer should we use?"}]},
    }

    _run(paths, payload, monkeypatch)

    assert "Which cache layer" in recent(paths)[0].text


def test_question_in_another_language_falls_back_to_a_generic_phrase(tmp_path, monkeypatch):
    paths = _paths(tmp_path, language="uk")
    payload = {
        "session_id": "s",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "Which cache layer should we use?"}]},
    }

    _run(paths, payload, monkeypatch)

    assert recent(paths)[0].text == "У мене питання, глянь у термінал."


def test_banner_always_shows_the_question_verbatim(tmp_path, monkeypatch):
    paths = _paths(tmp_path, language="uk")
    payload = {
        "session_id": "s",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "Which cache layer?"}]},
    }

    sent = _run(paths, payload, monkeypatch)

    assert sent[0]["body"] == "Which cache layer?"


def test_several_questions_are_counted_in_the_banner(tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    payload = {
        "session_id": "s",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "First?"}, {"question": "Second?"}]},
    }

    sent = _run(paths, payload, monkeypatch)

    assert "+1" in sent[0]["body"]


def test_questions_are_queued_at_high_priority(tmp_path, monkeypatch):
    from claude_voice.queue import pending, read_item

    paths = _paths(tmp_path, mode="voice")
    payload = {"session_id": "s", "tool_name": "ExitPlanMode", "tool_input": {}}

    _run(paths, payload, monkeypatch)

    assert read_item(pending(paths)[0]).priority == 0


def test_other_tools_are_ignored(tmp_path, monkeypatch):
    paths = _paths(tmp_path)

    _run(paths, {"session_id": "s", "tool_name": "Bash", "tool_input": {}}, monkeypatch)

    assert recent(paths) == []


def test_mode_off_does_nothing(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="off")

    _run(paths, {"session_id": "s", "tool_name": "ExitPlanMode", "tool_input": {}}, monkeypatch)

    assert recent(paths) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hook_question.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.hooks.question'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/hooks/question.py`:

```python
"""Claude is asking something: get attention now.

Runs before the tool is allowed to proceed, so it must stay fast - no summarizer here.
The banner can carry the question verbatim; the spoken line cannot, because a voice
tuned for one language mangles any other.
"""

from __future__ import annotations

from typing import Callable, Optional

from ..state import Paths
from . import common

TOOLS = ("AskUserQuestion", "ExitPlanMode")


def handle(
    payload: dict,
    paths: Optional[Paths] = None,
    notifier: Optional[Callable[..., None]] = None,
    worker: Optional[Callable[[], None]] = None,
) -> None:
    tool = payload.get("tool_name", "")
    if tool not in TOOLS:
        return

    context = common.build_context(payload, paths=paths)
    if context.mode == "off":
        return

    if tool == "ExitPlanMode":
        spoken = banner = context.pack.phrase("plan.ready")
    else:
        questions = payload.get("tool_input", {}).get("questions", []) or []
        first = (questions[0].get("question") if questions else "") or ""
        banner = first or context.pack.phrase("question.single")
        if len(questions) > 1:
            banner = f"{banner} (+{len(questions) - 1})"
        if first and context.pack.matches_language(first):
            spoken = context.pack.phrase("question.with_text", question=first)
        elif len(questions) > 1:
            spoken = context.pack.phrase("question.many")
        else:
            spoken = context.pack.phrase("question.single")

    common.emit(
        context,
        kind="question",
        text=spoken,
        banner=banner,
        priority=0,
        notifier=notifier,
        worker=worker,
    )


def main(payload: dict, detached: bool = False) -> None:
    if common.is_child():
        return
    handle(payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_hook_question.py -v`
Expected: PASS, 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/hooks/question.py tests/test_hook_question.py
git commit -m "feat: question and plan-approval hook"
```

---

## Task 21: Notification hook

**Files:**
- Create: `src/claude_voice/hooks/notification.py`, `tests/test_hook_notification.py`

- [ ] **Step 1: Write the failing test**

`tests/test_hook_notification.py`:

```python
import time

import claude_voice.hooks.notification as notification_hook
from claude_voice.config import Config, save
from claude_voice.history import recent
from claude_voice.queue import pending, read_item
from claude_voice.state import Paths


def _paths(tmp_path, mode="both"):
    paths = Paths(root=tmp_path / "home")
    paths.ensure()
    save(paths, Config(language="en", mode=mode))
    return paths


def _run(paths, message, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")
    monkeypatch.delenv("CLAUDE_VOICE_CHILD", raising=False)
    sent = []
    notification_hook.handle(
        {"session_id": "s", "message": message},
        paths=paths,
        notifier=lambda **kw: sent.append(kw),
        worker=lambda: None,
    )
    return sent


def test_permission_request_names_the_tool(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="voice")

    _run(paths, "Claude needs your permission to use Bash", monkeypatch)

    assert read_item(pending(paths)[0]).text == "I need permission to use Bash."


def test_permission_request_without_a_tool_name(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="voice")

    _run(paths, "Claude needs your permission", monkeypatch)

    assert read_item(pending(paths)[0]).text == "I need your permission, check the terminal."


def test_idle_nudge_is_announced(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="voice")

    _run(paths, "Claude is waiting for your input", monkeypatch)

    assert read_item(pending(paths)[0]).text == "Waiting for your answer."


def test_idle_nudge_is_not_repeated_within_the_quiet_window(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="voice")

    _run(paths, "Claude is waiting for your input", monkeypatch)
    _run(paths, "Claude is waiting for your input", monkeypatch)

    assert len(pending(paths)) == 1


def test_idle_nudge_returns_after_the_quiet_window(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="voice")
    _run(paths, "Claude is waiting for your input", monkeypatch)
    stamp = paths.state_dir / "notified-s"
    stamp.write_text(str(time.time() - notification_hook.QUIET_SECONDS - 1))

    _run(paths, "Claude is waiting for your input", monkeypatch)

    assert len(pending(paths)) == 2


def test_notices_are_never_written_to_history(tmp_path, monkeypatch):
    paths = _paths(tmp_path)

    _run(paths, "Claude needs your permission to use Bash", monkeypatch)

    assert recent(paths) == []


def test_banner_shows_the_original_message(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="notify")

    sent = _run(paths, "Claude needs your permission to use Bash", monkeypatch)

    assert sent[0]["body"] == "Claude needs your permission to use Bash"


def test_unrecognised_message_is_ignored(tmp_path, monkeypatch):
    paths = _paths(tmp_path, mode="voice")

    _run(paths, "Something entirely different", monkeypatch)

    assert pending(paths) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hook_notification.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.hooks.notification'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/hooks/notification.py`:

```python
"""Claude is blocked: waiting for a permission decision or simply idle.

These are announced but deliberately never stored - "waiting for your input" carries no
information after the fact, and in the prototype such lines crowded the history out.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Optional

from ..state import Paths
from . import common

QUIET_SECONDS = 180
_TOOL = re.compile(r"to use ([A-Za-z_]+)")


def handle(
    payload: dict,
    paths: Optional[Paths] = None,
    notifier: Optional[Callable[..., None]] = None,
    worker: Optional[Callable[[], None]] = None,
) -> None:
    message = str(payload.get("message", ""))
    if not message:
        return

    context = common.build_context(payload, paths=paths)
    if context.mode == "off":
        return

    lowered = message.lower()
    if "permission" in lowered:
        match = _TOOL.search(message)
        spoken = (
            context.pack.phrase("permission.tool", tool=match.group(1))
            if match
            else context.pack.phrase("permission.generic")
        )
    elif "waiting" in lowered or "idle" in lowered:
        stamp = context.paths.state_dir / f"notified-{context.session}"
        try:
            last = float(stamp.read_text())
        except (FileNotFoundError, ValueError):
            last = 0.0
        if time.time() - last < QUIET_SECONDS:
            return
        spoken = context.pack.phrase("waiting")
    else:
        return

    stamp = context.paths.state_dir / f"notified-{context.session}"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(str(time.time()))

    common.emit(
        context,
        kind="notice",
        text=spoken,
        banner=message,
        priority=0,
        notifier=notifier,
        worker=worker,
    )


def main(payload: dict, detached: bool = False) -> None:
    if common.is_child():
        return
    handle(payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_hook_notification.py -v`
Expected: PASS, 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/hooks/notification.py tests/test_hook_notification.py
git commit -m "feat: permission and idle notification hook"
```

---

## Task 22: Prompt-submit hook

**Files:**
- Create: `src/claude_voice/hooks/prompt_submit.py`, `tests/test_hook_prompt_submit.py`

- [ ] **Step 1: Write the failing test**

`tests/test_hook_prompt_submit.py`:

```python
import claude_voice.hooks.prompt_submit as prompt_hook
from claude_voice.queue import Item, enqueue, pending, read_item
from claude_voice.state import Paths


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def test_drops_only_this_sessions_pending_speech(tmp_path):
    paths = _paths(tmp_path)
    enqueue(paths, Item(priority=1, label="app", session="mine", text="stale"))
    enqueue(paths, Item(priority=1, label="app", session="other", text="keep"))

    prompt_hook.handle({"session_id": "mine"}, paths=paths, stopper=lambda: None)

    assert [read_item(path).text for path in pending(paths)] == ["keep"]


def test_stops_playback_when_the_current_utterance_is_ours(tmp_path):
    paths = _paths(tmp_path)
    (paths.state_dir / "current-session").write_text("mine")
    stopped = []

    prompt_hook.handle({"session_id": "mine"}, paths=paths, stopper=lambda: stopped.append(True))

    assert stopped == [True]


def test_leaves_another_sessions_playback_alone(tmp_path):
    paths = _paths(tmp_path)
    (paths.state_dir / "current-session").write_text("other")
    stopped = []

    prompt_hook.handle({"session_id": "mine"}, paths=paths, stopper=lambda: stopped.append(True))

    assert stopped == []


def test_missing_session_id_is_a_no_op(tmp_path):
    paths = _paths(tmp_path)
    enqueue(paths, Item(priority=1, label="app", session="mine", text="stale"))

    prompt_hook.handle({}, paths=paths, stopper=lambda: None)

    assert len(pending(paths)) == 1


def test_hook_prints_nothing(tmp_path, capsys):
    paths = _paths(tmp_path)

    prompt_hook.handle({"session_id": "mine"}, paths=paths, stopper=lambda: None)

    assert capsys.readouterr().out == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_hook_prompt_submit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.hooks.prompt_submit'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/hooks/prompt_submit.py`:

```python
"""You are typing again, so this session's pending speech is stale.

Other sessions are left alone: silencing another agent's summary because you typed here
would be wrong. This hook must print nothing at all - stdout on UserPromptSubmit is fed
straight into the model's context.
"""

from __future__ import annotations

import subprocess
from typing import Callable, Optional

from ..queue import pending, read_item
from ..state import Paths
from . import common


def stop_playback() -> None:
    for binary in ("say", "afplay"):
        subprocess.run(["pkill", "-x", binary], capture_output=True)


def handle(
    payload: dict,
    paths: Optional[Paths] = None,
    stopper: Optional[Callable[[], None]] = None,
) -> None:
    session = payload.get("session_id")
    if not session:
        return

    paths = paths or Paths.default()
    for path in pending(paths):
        try:
            item = read_item(path)
        except Exception:  # noqa: BLE001
            continue
        if item.session == session:
            path.unlink(missing_ok=True)

    current = paths.state_dir / "current-session"
    try:
        speaking_for = current.read_text().strip()
    except FileNotFoundError:
        speaking_for = ""
    if speaking_for == session:
        (stopper or stop_playback)()


def main(payload: dict, detached: bool = False) -> None:
    if common.is_child():
        return
    handle(payload)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_hook_prompt_submit.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/hooks/prompt_submit.py tests/test_hook_prompt_submit.py
git commit -m "feat: prompt-submit hook clears stale speech"
```

---

## Task 23: Command line and worker

**Files:**
- Create: `src/claude_voice/cli.py`, `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:

```python
import claude_voice.cli as cli
from claude_voice.config import Config, load, save
from claude_voice.history import add
from claude_voice.queue import Item, enqueue, pending, read_item
from claude_voice.state import Paths, snoozed_until


def _home(tmp_path, monkeypatch, **config_kwargs):
    monkeypatch.setenv("CLAUDE_VOICE_HOME", str(tmp_path / "home"))
    paths = Paths.default()
    paths.ensure()
    save(paths, Config(**config_kwargs) if config_kwargs else Config())
    return paths


def test_status_reports_the_current_mode(tmp_path, monkeypatch, capsys):
    _home(tmp_path, monkeypatch, mode="voice", language="en")

    assert cli.main(["status"]) == 0
    assert "voice" in capsys.readouterr().out


def test_mode_sets_the_global_default(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)

    cli.main(["mode", "off"])

    assert load(paths).mode == "off"


def test_mode_with_project_scope_writes_a_scope_file(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)

    cli.main(["mode", "voice", "--scope", "project", "--project", "/work/app"])

    from claude_voice.config import resolve_mode

    assert resolve_mode(paths, "/work/app", ".claude", default_mode="off") == "voice"


def test_auto_clears_a_scope(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    cli.main(["mode", "voice", "--scope", "project", "--project", "/work/app"])

    cli.main(["auto", "--scope", "project", "--project", "/work/app"])

    from claude_voice.config import resolve_mode

    assert resolve_mode(paths, "/work/app", ".claude", default_mode="off") == "off"


def test_snooze_then_resume(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)

    cli.main(["snooze", "30"])
    assert snoozed_until(paths) is not None

    cli.main(["resume"])
    assert snoozed_until(paths) is None


def test_snooze_clears_the_queue(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    enqueue(paths, Item(priority=1, label="app", session="s", text="stale"))
    monkeypatch.setattr(cli, "stop_playback", lambda: None)

    cli.main(["snooze", "30"])

    assert pending(paths) == []


def test_history_lists_entries_with_ids(tmp_path, monkeypatch, capsys):
    paths = _home(tmp_path, monkeypatch)
    entry = add(paths, kind="tldr", label="app", text="All done.")

    cli.main(["history"])

    output = capsys.readouterr().out
    assert "All done." in output and entry.id in output


def test_play_queues_the_entry_with_the_force_flag(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    entry = add(paths, kind="tldr", label="app", text="Replay me.")
    monkeypatch.setattr(cli.common, "spawn_worker", lambda: None)
    monkeypatch.setattr(cli, "stop_playback", lambda: None)

    cli.main(["play", entry.id])

    item = read_item(pending(paths)[0])
    assert item.text == "Replay me."
    assert item.flags == "force"


def test_play_with_an_unknown_id_fails(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)

    assert cli.main(["play", "nope"]) == 1


def test_replay_speaks_the_newest_entry(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    add(paths, kind="tldr", label="app", text="older")
    add(paths, kind="tldr", label="app", text="newest")
    monkeypatch.setattr(cli.common, "spawn_worker", lambda: None)
    monkeypatch.setattr(cli, "stop_playback", lambda: None)

    cli.main(["replay"])

    assert read_item(pending(paths)[0]).text == "newest"


def test_replay_marks_history_as_seen(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    entry = add(paths, kind="tldr", label="app", text="newest")
    monkeypatch.setattr(cli.common, "spawn_worker", lambda: None)
    monkeypatch.setattr(cli, "stop_playback", lambda: None)

    cli.main(["replay"])

    assert paths.seen_file.read_text().strip() == entry.id


def test_shut_clears_the_queue_and_stops_playback(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    enqueue(paths, Item(priority=1, label="app", session="s", text="stale"))
    stopped = []
    monkeypatch.setattr(cli, "stop_playback", lambda: stopped.append(True))

    cli.main(["shut"])

    assert pending(paths) == [] and stopped == [True]


def test_worker_drains_the_queue(tmp_path, monkeypatch):
    paths = _home(tmp_path, monkeypatch)
    enqueue(paths, Item(priority=1, label="app", session="s", text="hello"))
    spoken = []
    monkeypatch.setattr(cli.common, "make_speaker", lambda *a, **k: lambda text, item: spoken.append(text))

    cli.main(["worker"])

    assert spoken == ["app. hello"] or spoken == ["hello"]
    assert pending(paths) == []


def test_hook_subcommand_dispatches_to_the_module(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)
    called = []
    monkeypatch.setattr(cli.stop_hook, "main", lambda payload, detached: called.append(detached))
    monkeypatch.setattr(cli.common, "read_payload", lambda source: {"session_id": "s"})

    cli.main(["hook", "stop"])

    assert called == [False]


def test_unknown_subcommand_returns_non_zero(tmp_path, monkeypatch):
    _home(tmp_path, monkeypatch)

    assert cli.main(["nonsense"]) != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.cli'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/cli.py`:

```python
"""Every command the user and the hooks go through."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from . import config as config_module
from . import health, history
from .hooks import common
from .hooks import notification as notification_hook
from .hooks import prompt_submit as prompt_submit_hook
from .hooks import question as question_hook
from .hooks import stop as stop_hook
from .queue import Item, drain, enqueue, pending
from .state import Paths, clear_snooze, set_snooze, snoozed_until

HOOKS = {
    "stop": stop_hook,
    "question": question_hook,
    "notification": notification_hook,
    "prompt-submit": prompt_submit_hook,
}


def stop_playback() -> None:
    for binary in ("say", "afplay"):
        subprocess.run(["pkill", "-x", binary], capture_output=True)


def _clear_queue(paths: Paths) -> None:
    for path in pending(paths):
        path.unlink(missing_ok=True)


def _project_dir(args: argparse.Namespace) -> str:
    return args.project or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()


def _namespace() -> str:
    return os.path.basename(os.environ.get("CLAUDE_CONFIG_DIR", ".claude").rstrip("/"))


def _effective_mode(paths: Paths, config: config_module.Config, project_dir: str) -> str:
    return config_module.resolve_mode(
        paths,
        project_dir=project_dir,
        namespace=_namespace(),
        default_mode=config.mode,
        snoozed=snoozed_until(paths) is not None,
    )


def _engines(paths: Paths, config: config_module.Config):
    from .i18n import load as load_pack
    from .speech.edge import EdgeEngine
    from .speech.macos_say import SayEngine

    pack = load_pack(config.language)
    edge = EdgeEngine(voice=config.edge_voice, rate=config.edge_rate, cache_dir=paths.cache_dir)
    say = SayEngine(voice=config.say_voice, rate=config.say_rate, table=pack.translit_table)
    return [edge, say] if config.engine == "edge" else [say, edge]


def _speak_now(paths: Paths, text: str, label: str = "") -> None:
    _clear_queue(paths)
    stop_playback()
    paths.last_label_file.unlink(missing_ok=True)
    enqueue(paths, Item(priority=0, label=label, session="cli", text=text, flags="force"))
    common.spawn_worker()


def _mark_seen(paths: Paths) -> None:
    entries = history.recent(paths, limit=1)
    if entries:
        paths.seen_file.parent.mkdir(parents=True, exist_ok=True)
        paths.seen_file.write_text(entries[0].id)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claude-voice")
    sub = parser.add_subparsers(dest="command")

    hook = sub.add_parser("hook")
    hook.add_argument("name", choices=sorted(HOOKS))
    hook.add_argument("--payload", type=Path, default=None)
    hook.add_argument("--detached", action="store_true")

    sub.add_parser("worker")
    sub.add_parser("status")

    for name in ("mode", "auto"):
        command = sub.add_parser(name)
        if name == "mode":
            command.add_argument("value", choices=config_module.MODES)
        command.add_argument("--scope", choices=("global", "alias", "project"), default="global")
        command.add_argument("--project", default=None)

    snooze = sub.add_parser("snooze")
    snooze.add_argument("minutes", type=float, nargs="?", default=30)
    sub.add_parser("resume")

    listing = sub.add_parser("history")
    listing.add_argument("-n", "--limit", type=int, default=15)

    play = sub.add_parser("play")
    play.add_argument("entry_id")

    sub.add_parser("replay")
    sub.add_parser("seen")
    sub.add_parser("skip")
    sub.add_parser("shut")
    sub.add_parser("doctor")
    sub.add_parser("menubar")

    speak = sub.add_parser("speak")
    speak.add_argument("text", nargs="+")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    paths = Paths.default()
    paths.ensure()
    config = config_module.load(paths)

    if args.command == "hook":
        HOOKS[args.name].main(common.read_payload(args.payload), detached=args.detached)
        return 0

    if args.command == "worker":
        speaker = common.make_speaker(paths, engines=_engines(paths, config))
        drain(paths, speaker, is_paused=lambda: snoozed_until(paths) is not None)
        return 0

    if args.command == "status":
        mode = _effective_mode(paths, config, _project_dir(argparse.Namespace(project=None)))
        until = snoozed_until(paths)
        if until is not None:
            print(f"paused for {int((until - __import__('time').time()) / 60) + 1} more minutes")
        else:
            voice = config.edge_voice if config.engine == "edge" else config.say_voice
            print(f"mode: {mode} · engine: {config.engine} · voice: {voice} · language: {config.language}")
        for failure in health.failures(paths):
            print(f"  warning: {failure.component}: {failure.error}")
        return 0

    if args.command in ("mode", "auto"):
        project_dir = _project_dir(args)
        if args.scope == "global":
            if args.command == "mode":
                config.mode = args.value
                config_module.save(paths, config)
            else:
                config.mode = "off"
                config_module.save(paths, config)
        else:
            kind = "project" if args.scope == "project" else "alias"
            value = project_dir if kind == "project" else _namespace()
            if args.command == "mode":
                config_module.set_scope(paths, kind, value, args.value)
            else:
                config_module.clear_scope(paths, kind, value)
        print(_effective_mode(paths, config_module.load(paths), project_dir))
        return 0

    if args.command == "snooze":
        set_snooze(paths, args.minutes)
        _clear_queue(paths)
        stop_playback()
        print(f"paused for {int(args.minutes)} minutes")
        return 0

    if args.command == "resume":
        clear_snooze(paths)
        print("resumed")
        return 0

    if args.command == "history":
        for entry in reversed(history.recent(paths, limit=args.limit)):
            icon = "?" if entry.kind == "question" else "+"
            print(f"{icon} {entry.label}  {entry.text}   [{entry.id}]")
        return 0

    if args.command == "play":
        entry = history.get(paths, args.entry_id)
        if entry is None:
            print(f"no history entry {args.entry_id}", file=sys.stderr)
            return 1
        _speak_now(paths, entry.text, label=entry.label)
        _mark_seen(paths)
        print(entry.text)
        return 0

    if args.command == "replay":
        entries = history.recent(paths, limit=1)
        if not entries:
            print("nothing to replay")
            return 0
        _speak_now(paths, entries[0].text, label=entries[0].label)
        _mark_seen(paths)
        print(entries[0].text)
        return 0

    if args.command == "seen":
        _mark_seen(paths)
        return 0

    if args.command == "skip":
        stop_playback()
        return 0

    if args.command == "shut":
        _clear_queue(paths)
        stop_playback()
        return 0

    if args.command == "speak":
        _speak_now(paths, " ".join(args.text))
        return 0

    if args.command == "doctor":
        from .doctor import report

        return report(paths, config)

    if args.command == "menubar":
        from .menubar.render import render

        print(render(paths, config))
        return 0

    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_cli.py -v`
Expected: PASS, 15 passed. The `doctor` and `menubar` imports are lazy, so they do not need to exist yet.

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/cli.py tests/test_cli.py
git commit -m "feat: command line and speech worker"
```

---

## Task 24: Hooks must not delay the session

**Files:**
- Create: `tests/test_performance.py`

- [ ] **Step 1: Write the failing test**

`tests/test_performance.py`:

```python
import subprocess
import sys
import time

BUDGET_SECONDS = 0.6


def _run_hook(name, payload, env_home):
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "claude_voice.cli", "hook", name],
        input=payload,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(env_home), "CLAUDE_VOICE_HOME": str(env_home)},
    )
    return time.monotonic() - start, result


def test_question_hook_returns_within_budget(tmp_path):
    elapsed, result = _run_hook(
        "question",
        '{"session_id": "s", "tool_name": "Bash", "tool_input": {}}',
        tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert elapsed < BUDGET_SECONDS, f"hook took {elapsed:.2f}s"


def test_prompt_submit_hook_prints_nothing(tmp_path):
    _, result = _run_hook("prompt-submit", '{"session_id": "s"}', tmp_path)

    assert result.stdout == ""


def test_heavy_modules_are_not_imported_by_hooks():
    """edge-tts pulls in aiohttp; importing it on every hook would blow the budget."""
    code = (
        "import sys; import claude_voice.cli as cli; "
        "assert 'edge_tts' not in sys.modules, sorted(m for m in sys.modules if 'edge' in m)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_performance.py -v`
Expected: The import test FAILS if any module imports `edge_tts` at module scope. Fix by keeping every heavy import inside a function, as `_engines` already does.

- [ ] **Step 3: Write minimal implementation**

No new module. If the budget test fails, move imports into functions. Confirm `src/claude_voice/speech/edge.py` never imports `edge_tts` — it shells out to the `edge-tts` binary instead, which is why the package is only a runtime dependency of the installer, not an import.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_performance.py -v`
Expected: PASS, 3 passed

- [ ] **Step 5: Commit**

```bash
git add tests/test_performance.py
git commit -m "test: hooks stay under the latency budget"
```

---

## Task 25: Doctor

**Files:**
- Create: `src/claude_voice/doctor.py`, `tests/test_doctor.py`

- [ ] **Step 1: Write the failing test**

`tests/test_doctor.py`:

```python
import claude_voice.doctor as doctor_module
from claude_voice.config import Config
from claude_voice.doctor import checks, report
from claude_voice.health import record
from claude_voice.state import Paths


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def _all_present(monkeypatch):
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: f"/usr/local/bin/{name}")


def test_missing_binary_is_reported_with_a_remedy(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: None if name == "edge-tts" else "/bin/x")
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])

    results = {check.name: check for check in checks(_paths(tmp_path), Config())}

    assert results["edge-tts"].ok is False
    assert "pip install" in results["edge-tts"].remedy


def test_everything_present_passes(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])

    assert all(check.ok for check in checks(_paths(tmp_path), Config()) if check.name != "focus")


def test_recorded_failures_surface_as_a_failed_check(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    paths = _paths(tmp_path)
    record(paths, "edge-tts", "no network")

    results = {check.name: check for check in checks(paths, Config())}

    assert results["recent failures"].ok is False
    assert "no network" in results["recent failures"].detail


def test_stale_lock_is_reported(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    paths = _paths(tmp_path)
    paths.lock_dir.mkdir()
    (paths.lock_dir / "pid").write_text("0")

    results = {check.name: check for check in checks(paths, Config())}

    assert results["speech lock"].ok is False


def test_focus_suppression_is_reported_not_treated_as_broken(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    monkeypatch.setattr(doctor_module, "focus_active", lambda: True)

    results = {check.name: check for check in checks(_paths(tmp_path), Config())}

    assert results["focus"].ok is False
    assert "Do Not Disturb" in results["focus"].detail


def test_report_returns_zero_when_everything_passes(tmp_path, monkeypatch, capsys):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    monkeypatch.setattr(doctor_module, "focus_active", lambda: False)

    assert report(_paths(tmp_path), Config()) == 0
    assert "OK" in capsys.readouterr().out


def test_report_returns_one_when_a_check_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(doctor_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])

    assert report(_paths(tmp_path), Config()) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_doctor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.doctor'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/doctor.py`:

```python
"""Self-diagnosis.

The single most confusing failure in the prototype was banners being delivered but
suppressed by Do Not Disturb, which looks exactly like the feature being broken. That is
why Focus gets its own check.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List

from . import health
from .config import Config
from .queue import _process_alive  # noqa: F401 - reused rather than duplicated
from .state import Paths

FOCUS_ASSERTIONS = Path.home() / "Library/DoNotDisturb/DB/Assertions.json"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    remedy: str = ""


REQUIRED_BINARIES = {
    "edge-tts": "pip install edge-tts (inside ~/.claude-voice/.venv)",
    "terminal-notifier": "brew install terminal-notifier",
    "say": "part of macOS; this tool is macOS only",
    "afplay": "part of macOS; this tool is macOS only",
    "claude": "install the Claude Code CLI",
}


def focus_active() -> bool:
    try:
        data = json.loads(FOCUS_ASSERTIONS.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    return bool(data.get("data", [{}])[0].get("storeAssertionRecords"))


def hook_check() -> List[Check]:
    """Every Claude config directory should reference an existing shim."""
    results = []
    home = Path(os.environ.get("HOME", "~")).expanduser()
    for config_dir in sorted(home.glob(".claude*")):
        settings = config_dir / "settings.json"
        if not settings.exists():
            continue
        try:
            text = settings.read_text()
        except OSError:
            continue
        installed = "cv-hook" in text
        results.append(
            Check(
                name=f"hooks in {config_dir.name}",
                ok=installed,
                detail="installed" if installed else "no claude-voice hooks found",
                remedy="run ./install.sh again",
            )
        )
    return results


def checks(paths: Paths, config: Config) -> List[Check]:
    results: List[Check] = []

    for binary, remedy in REQUIRED_BINARIES.items():
        found = shutil.which(binary)
        results.append(
            Check(name=binary, ok=bool(found), detail=found or "not found", remedy=remedy)
        )

    failures = health.failures(paths)
    results.append(
        Check(
            name="recent failures",
            ok=not failures,
            detail="; ".join(f"{item.component}: {item.error}" for item in failures) or "none",
            remedy="fix the component above, then run: claude-voice doctor",
        )
    )

    stale = False
    if paths.lock_dir.exists():
        try:
            owner = int((paths.lock_dir / "pid").read_text().strip())
        except (FileNotFoundError, ValueError):
            owner = 0
        stale = not _process_alive(owner)
    results.append(
        Check(
            name="speech lock",
            ok=not stale,
            detail="stale lock left by a dead worker" if stale else "free",
            remedy=f"rm -rf {paths.lock_dir}",
        )
    )

    suppressed = focus_active()
    results.append(
        Check(
            name="focus",
            ok=not suppressed,
            detail="Do Not Disturb is on: banners are delivered but not shown" if suppressed else "off",
            remedy="allow time-sensitive notifications for terminal-notifier, or rely on the menu bar",
        )
    )

    results.extend(hook_check())
    return results


def report(paths: Paths, config: Config) -> int:
    results = checks(paths, config)
    for check in results:
        mark = "OK  " if check.ok else "FAIL"
        line = f"[{mark}] {check.name}: {check.detail}"
        if not check.ok and check.remedy:
            line += f"\n         -> {check.remedy}"
        print(line)
    return 0 if all(check.ok for check in results) else 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_doctor.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/doctor.py tests/test_doctor.py
git commit -m "feat: doctor self-diagnosis"
```

---

## Task 26: Menu bar

**Files:**
- Create: `src/claude_voice/menubar/__init__.py`, `src/claude_voice/menubar/render.py`, `src/claude_voice/menubar/plugin.sh`, `tests/test_menubar.py`

- [ ] **Step 1: Write the failing test**

`tests/test_menubar.py`:

```python
from claude_voice.config import Config
from claude_voice.health import record
from claude_voice.history import add
from claude_voice.menubar.render import render
from claude_voice.state import Paths, set_snooze


def _paths(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()
    return paths


def _title(text):
    return text.splitlines()[0]


def test_title_shows_the_mode_icon(tmp_path):
    output = render(_paths(tmp_path), Config(mode="voice"))

    assert _title(output).startswith("🔊")


def test_silent_mode_has_its_own_icon(tmp_path):
    assert _title(render(_paths(tmp_path), Config(mode="off"))).startswith("🔇")


def test_paused_title_shows_remaining_minutes(tmp_path):
    paths = _paths(tmp_path)
    set_snooze(paths, minutes=20)

    assert "⏸" in _title(render(paths, Config(mode="voice")))


def test_unread_counter_is_shown(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="All done.")

    assert "1" in _title(render(paths, Config()))


def test_counter_disappears_once_marked_seen(tmp_path):
    paths = _paths(tmp_path)
    entry = add(paths, kind="tldr", label="app", text="All done.")
    paths.seen_file.write_text(entry.id)

    assert _title(render(paths, Config())).strip() in ("🔔", "🔊", "🔇")


def test_warning_icon_when_something_failed(tmp_path):
    paths = _paths(tmp_path)
    record(paths, "edge-tts", "no network")

    output = render(paths, Config())

    assert _title(output).startswith("⚠️")
    assert "edge-tts: no network" in output


def test_last_message_is_shown_in_the_menu(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="Refactored the sync layer.")

    assert "Refactored the sync layer." in render(paths, Config())


def test_history_entries_are_clickable(tmp_path):
    paths = _paths(tmp_path)
    entry = add(paths, kind="tldr", label="app", text="All done.")

    output = render(paths, Config())

    assert f'param2="play" param3="{entry.id}"' in output


def test_pipe_characters_are_escaped(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="a | b")

    body = "\n".join(render(paths, Config()).splitlines()[1:])

    assert "a / b" in body


def test_long_history_text_is_truncated(tmp_path):
    paths = _paths(tmp_path)
    add(paths, kind="tldr", label="app", text="x" * 200)

    assert "…" in render(paths, Config())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_menubar.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.menubar'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/menubar/__init__.py`:

```python
"""Menu-bar rendering."""
```

`src/claude_voice/menubar/render.py`:

```python
"""SwiftBar menu.

Focus suppresses banners but cannot touch the menu bar, so the unread counter and the
text of the last message live here. The plugin itself is three lines; all of the logic
is this function, which means it is testable.
"""

from __future__ import annotations

import time
from typing import List

from .. import health, history
from ..config import Config
from ..state import Paths, snoozed_until

ICONS = {"off": "🔇", "notify": "🔔", "voice": "🔊", "both": "🔊"}
RUN = 'bash="/bin/bash" terminal=false refresh=true'
TRUNCATE_AT = 64


def _shell(paths: Paths) -> str:
    # SwiftBar numbers arguments from param1, so the shim is param1 and the subcommand
    # is param2. Getting this off by one silently produces a menu whose items do nothing.
    return f'param1="{paths.root}/bin/cv-hook"'


def _unread(paths: Paths) -> int:
    try:
        seen = paths.seen_file.read_text().strip()
    except FileNotFoundError:
        seen = ""
    return sum(1 for entry in history.recent(paths, limit=200) if entry.id > seen)


def _clean(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def render(paths: Paths, config: Config) -> str:
    lines: List[str] = []
    failures = health.failures(paths)
    until = snoozed_until(paths)
    unread = _unread(paths)

    if failures:
        icon = "⚠️"
    elif until is not None:
        icon = f"⏸ {int((until - time.time()) / 60) + 1}m"
    else:
        icon = ICONS.get(config.mode, "🔔")
    lines.append(f"{icon} {unread}" if unread else icon)
    lines.append("---")

    for failure in failures:
        lines.append(f"{_clean(failure.component)}: {_clean(failure.error)} | color=#ff9f0a")
    if failures:
        lines.append(f'Run doctor | {RUN} {_shell(paths)} param2="doctor"')
        lines.append("---")

    entries = history.recent(paths, limit=12)
    if entries:
        lines.append(_clean(entries[0].text) + " | size=12")
    if unread:
        lines.append(f'Mark as read ({unread}) | {RUN} {_shell(paths)} param2="seen"')
    lines.append("---")

    if until is not None:
        lines.append(f'Resume | {RUN} {_shell(paths)} param2="resume"')
    else:
        lines.append("Pause")
        for minutes in (15, 30, 60):
            lines.append(
                f'-- {minutes} minutes | {RUN} {_shell(paths)} param2="snooze" param3="{minutes}"'
            )

    lines.append("Mode")
    for mode in ("off", "notify", "voice", "both"):
        mark = "●" if mode == config.mode else "○"
        lines.append(f'-- {mark} {mode} | {RUN} {_shell(paths)} param2="mode" param3="{mode}"')

    lines.append("---")
    lines.append("History")
    for entry in entries:
        text = entry.text if len(entry.text) <= TRUNCATE_AT else entry.text[:TRUNCATE_AT] + "…"
        marker = "?" if entry.kind == "question" else "+"
        stamp = time.strftime("%H:%M", time.localtime(entry.ts))
        lines.append(
            f'{marker} {stamp}  {_clean(text)} | {RUN} {_shell(paths)} param2="play" param3="{entry.id}"'
        )

    lines.append("---")
    lines.append(f'Replay last | {RUN} {_shell(paths)} param2="replay"')
    lines.append(f'Skip | {RUN} {_shell(paths)} param2="skip"')
    lines.append(f'Silence now | {RUN} {_shell(paths)} param2="shut"')
    lines.append("Refresh | refresh=true")
    return "\n".join(lines)
```

`src/claude_voice/menubar/plugin.sh`:

```bash
#!/bin/bash
# SwiftBar plugin. All logic lives in `claude-voice menubar`; this only calls it.
#
# <xbar.title>Claude voice</xbar.title>
# <xbar.desc>Claude Code reporting: banners, speech, history</xbar.desc>

exec "$HOME/.claude-voice/bin/cv-hook" menubar
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_menubar.py -v`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/menubar tests/test_menubar.py
git commit -m "feat: menu-bar rendering with unread counter and warnings"
```

---

## Task 27: Hook installation into settings.json

**Files:**
- Create: `src/claude_voice/install.py`, `tests/test_install.py`
- Modify: `src/claude_voice/cli.py` (add the `install-hooks` and `remove-hooks` subcommands)

- [ ] **Step 1: Write the failing test**

`tests/test_install.py`:

```python
import json

from claude_voice.install import EVENTS, install_hooks, remove_hooks


def _settings(tmp_path, payload):
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()
    (config_dir / "settings.json").write_text(json.dumps(payload))
    return config_dir


def test_hooks_are_added_for_every_event(tmp_path):
    config_dir = _settings(tmp_path, {})

    install_hooks(config_dir, shim="/home/me/.claude-voice/bin/cv-hook")

    data = json.loads((config_dir / "settings.json").read_text())
    assert set(EVENTS) <= set(data["hooks"])


def test_existing_hooks_are_preserved(tmp_path):
    config_dir = _settings(
        tmp_path,
        {"hooks": {"Notification": [{"hooks": [{"type": "command", "command": "afplay ping.aiff"}]}]}},
    )

    install_hooks(config_dir, shim="/shim/cv-hook")

    commands = [
        hook["command"]
        for group in json.loads((config_dir / "settings.json").read_text())["hooks"]["Notification"]
        for hook in group["hooks"]
    ]
    assert "afplay ping.aiff" in commands
    assert any("cv-hook" in command for command in commands)


def test_other_settings_are_untouched(tmp_path):
    config_dir = _settings(tmp_path, {"model": "opus", "permissions": {"allow": ["Read"]}})

    install_hooks(config_dir, shim="/shim/cv-hook")

    data = json.loads((config_dir / "settings.json").read_text())
    assert data["model"] == "opus"
    assert data["permissions"] == {"allow": ["Read"]}


def test_installation_is_idempotent(tmp_path):
    config_dir = _settings(tmp_path, {})

    install_hooks(config_dir, shim="/shim/cv-hook")
    install_hooks(config_dir, shim="/shim/cv-hook")

    stop_hooks = json.loads((config_dir / "settings.json").read_text())["hooks"]["Stop"]
    assert sum(len(group["hooks"]) for group in stop_hooks) == 1


def test_a_backup_is_written(tmp_path):
    config_dir = _settings(tmp_path, {"model": "opus"})

    install_hooks(config_dir, shim="/shim/cv-hook")

    backups = list(config_dir.glob("settings.json.backup-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text()) == {"model": "opus"}


def test_no_marker_keys_are_added_to_hook_entries(tmp_path):
    """settings.json is schema-validated, so ownership is recognised by command path."""
    config_dir = _settings(tmp_path, {})

    install_hooks(config_dir, shim="/shim/cv-hook")

    for groups in json.loads((config_dir / "settings.json").read_text())["hooks"].values():
        for group in groups:
            for hook in group["hooks"]:
                assert set(hook) <= {"type", "command", "timeout", "async"}


def test_question_hook_uses_the_tool_matcher(tmp_path):
    config_dir = _settings(tmp_path, {})

    install_hooks(config_dir, shim="/shim/cv-hook")

    matchers = [
        group.get("matcher")
        for group in json.loads((config_dir / "settings.json").read_text())["hooks"]["PreToolUse"]
    ]
    assert "AskUserQuestion|ExitPlanMode" in matchers


def test_stop_hook_is_async(tmp_path):
    config_dir = _settings(tmp_path, {})

    install_hooks(config_dir, shim="/shim/cv-hook")

    hook = json.loads((config_dir / "settings.json").read_text())["hooks"]["Stop"][0]["hooks"][0]
    assert hook["async"] is True


def test_remove_hooks_removes_only_ours(tmp_path):
    config_dir = _settings(
        tmp_path,
        {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}},
    )
    install_hooks(config_dir, shim="/shim/cv-hook")

    remove_hooks(config_dir)

    commands = [
        hook["command"]
        for group in json.loads((config_dir / "settings.json").read_text())["hooks"].get("Stop", [])
        for hook in group["hooks"]
    ]
    assert commands == ["echo mine"]


def test_missing_settings_file_is_created(tmp_path):
    config_dir = tmp_path / ".claude"
    config_dir.mkdir()

    install_hooks(config_dir, shim="/shim/cv-hook")

    assert (config_dir / "settings.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_install.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.install'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/install.py`:

```python
"""Wiring the hooks into Claude Code's settings.json.

Ownership is recognised by the command path rather than an injected marker key, because
settings.json is validated against a published schema and unknown keys must not appear
there. That also makes installation naturally idempotent.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Dict, List

SHIM_MARKER = "cv-hook"

# event -> (matcher or None, hook subcommand, extra keys)
EVENTS: Dict[str, tuple] = {
    "PreToolUse": ("AskUserQuestion|ExitPlanMode", "question", {"timeout": 10}),
    "Notification": (None, "notification", {"timeout": 10}),
    "Stop": (None, "stop", {"async": True, "timeout": 120}),
    "UserPromptSubmit": (None, "prompt-submit", {"timeout": 10}),
}


def _load(settings: Path) -> dict:
    try:
        return json.loads(settings.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save(settings: Path, data: dict) -> None:
    settings.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _backup(settings: Path) -> None:
    if settings.exists():
        shutil.copy2(settings, settings.with_suffix(f".json.backup-{time.strftime('%Y%m%d%H%M%S')}"))


def _owned(command: str) -> bool:
    return SHIM_MARKER in command


def install_hooks(config_dir: Path, shim: str) -> None:
    settings = Path(config_dir) / "settings.json"
    _backup(settings)
    data = _load(settings)
    hooks = data.setdefault("hooks", {})

    for event, (matcher, subcommand, extra) in EVENTS.items():
        groups: List[dict] = hooks.setdefault(event, [])
        already = any(_owned(hook.get("command", "")) for group in groups for hook in group.get("hooks", []))
        if already:
            continue
        entry = {"type": "command", "command": f"{shim} hook {subcommand}", **extra}
        target = None
        for group in groups:
            if group.get("matcher") == matcher:
                target = group
                break
        if target is None:
            target = {"hooks": []} if matcher is None else {"matcher": matcher, "hooks": []}
            groups.append(target)
        target.setdefault("hooks", []).append(entry)

    _save(settings, data)


def remove_hooks(config_dir: Path) -> None:
    settings = Path(config_dir) / "settings.json"
    data = _load(settings)
    hooks = data.get("hooks", {})
    for event, groups in list(hooks.items()):
        for group in groups:
            group["hooks"] = [hook for hook in group.get("hooks", []) if not _owned(hook.get("command", ""))]
        hooks[event] = [group for group in groups if group.get("hooks")]
        if not hooks[event]:
            del hooks[event]
    _save(settings, data)
```

Then add to `src/claude_voice/cli.py`, inside `build_parser()`:

```python
    installer = sub.add_parser("install-hooks")
    installer.add_argument("config_dirs", nargs="+", type=Path)
    remover = sub.add_parser("remove-hooks")
    remover.add_argument("config_dirs", nargs="+", type=Path)
```

and inside `main()`, before the final `return 2`:

```python
    if args.command in ("install-hooks", "remove-hooks"):
        from .install import install_hooks, remove_hooks

        shim = str(paths.root / "bin" / "cv-hook")
        for config_dir in args.config_dirs:
            if args.command == "install-hooks":
                install_hooks(config_dir, shim=shim)
            else:
                remove_hooks(config_dir)
            print(f"{args.command}: {config_dir}")
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_install.py tests/test_cli.py -v`
Expected: PASS, 25 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/install.py src/claude_voice/cli.py tests/test_install.py
git commit -m "feat: idempotent hook installation"
```

---

## Task 28: Migration from the prototype

**Files:**
- Create: `src/claude_voice/migrate.py`, `tests/test_migrate.py`
- Modify: `src/claude_voice/cli.py` (add the `migrate` subcommand)

- [ ] **Step 1: Write the failing test**

`tests/test_migrate.py`:

```python
import json

from claude_voice.history import recent
from claude_voice.migrate import migrate
from claude_voice.state import Paths


def _old(tmp_path):
    old = tmp_path / ".claude-tts"
    (old / "state").mkdir(parents=True)
    return old


def test_history_is_imported(tmp_path):
    old = _old(tmp_path)
    (old / "history.jsonl").write_text(
        json.dumps({"id": "1", "ts": 1, "kind": "tldr", "label": "app", "text": "old entry"}) + "\n"
    )
    paths = Paths(root=tmp_path / "new")
    paths.ensure()

    migrate(old, paths)

    assert [entry.text for entry in recent(paths)] == ["old entry"]


def test_unknown_fields_in_old_entries_are_dropped(tmp_path):
    old = _old(tmp_path)
    (old / "history.jsonl").write_text(
        json.dumps({"id": "1", "ts": 1, "kind": "tldr", "label": "app", "text": "x", "sid": "s", "dir": "/d"}) + "\n"
    )
    paths = Paths(root=tmp_path / "new")
    paths.ensure()

    migrate(old, paths)

    assert recent(paths)[0].text == "x"


def test_old_directory_is_left_untouched(tmp_path):
    old = _old(tmp_path)
    (old / "history.jsonl").write_text(
        json.dumps({"id": "1", "ts": 1, "kind": "tldr", "label": "app", "text": "old"}) + "\n"
    )
    paths = Paths(root=tmp_path / "new")
    paths.ensure()

    migrate(old, paths)

    assert (old / "history.jsonl").exists()


def test_missing_old_installation_is_not_an_error(tmp_path):
    paths = Paths(root=tmp_path / "new")
    paths.ensure()

    assert migrate(tmp_path / "nothing-here", paths) == 0


def test_existing_history_is_not_overwritten(tmp_path):
    old = _old(tmp_path)
    (old / "history.jsonl").write_text(
        json.dumps({"id": "1", "ts": 1, "kind": "tldr", "label": "app", "text": "old"}) + "\n"
    )
    paths = Paths(root=tmp_path / "new")
    paths.ensure()
    paths.history_file.write_text(
        json.dumps({"id": "2", "ts": 2, "kind": "tldr", "label": "app", "text": "already here"}) + "\n"
    )

    migrate(old, paths)

    texts = {entry.text for entry in recent(paths)}
    assert texts == {"old", "already here"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_migrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_voice.migrate'`

- [ ] **Step 3: Write minimal implementation**

`src/claude_voice/migrate.py`:

```python
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
```

Then add to `build_parser()`:

```python
    migration = sub.add_parser("migrate")
    migration.add_argument("--from", dest="old_root", type=Path, default=Path.home() / ".claude-tts")
```

and to `main()`:

```python
    if args.command == "migrate":
        from .migrate import migrate

        count = migrate(args.old_root, paths)
        print(f"imported {count} history entries; {args.old_root} was left untouched")
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_migrate.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/claude_voice/migrate.py src/claude_voice/cli.py tests/test_migrate.py
git commit -m "feat: import data from the bash prototype"
```

---

## Task 29: Installer scripts

**Files:**
- Create: `install.sh`, `uninstall.sh`

- [ ] **Step 1: Write the failing test**

There is no unit test for a bootstrap script; it is verified by running it. Write the
verification first so the acceptance criteria are fixed before the script exists:

```bash
# Acceptance, run from a clone after Step 3:
CLAUDE_VOICE_HOME=/tmp/cv-test ./install.sh --no-hooks --language en
/tmp/cv-test/bin/cv-hook status        # prints a mode line
/tmp/cv-test/bin/cv-hook doctor        # runs, lists checks
```

- [ ] **Step 2: Run it to verify it fails**

Run: `CLAUDE_VOICE_HOME=/tmp/cv-test ./install.sh --no-hooks --language en`
Expected: FAIL with `no such file or directory: ./install.sh`

- [ ] **Step 3: Write minimal implementation**

`install.sh`:

```bash
#!/usr/bin/env bash
# Bootstrap claude-voice: virtual environment, shim, hooks, menu-bar plugin.
set -euo pipefail

HOME_DIR="${CLAUDE_VOICE_HOME:-$HOME/.claude-voice}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LANGUAGE=""
INSTALL_HOOKS=1
INSTALL_PLUGIN=1

while [ $# -gt 0 ]; do
  case "$1" in
    --language) LANGUAGE="$2"; shift 2 ;;
    --no-hooks) INSTALL_HOOKS=0; shift ;;
    --no-menubar) INSTALL_PLUGIN=0; shift ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

echo "==> Creating $HOME_DIR"
mkdir -p "$HOME_DIR/bin"
python3 -m venv "$HOME_DIR/.venv"
"$HOME_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$HOME_DIR/.venv/bin/pip" install --quiet "$SOURCE_DIR"

# The hooks in settings.json point at this path forever; upgrading never rewrites them.
cat > "$HOME_DIR/bin/cv-hook" <<EOF
#!/usr/bin/env bash
exec "$HOME_DIR/.venv/bin/claude-voice" "\$@"
EOF
chmod +x "$HOME_DIR/bin/cv-hook"

if [ -z "$LANGUAGE" ]; then
  printf 'Speech language [en]: '
  read -r LANGUAGE || true
  LANGUAGE="${LANGUAGE:-en}"
fi
"$HOME_DIR/bin/cv-hook" language "$LANGUAGE" >/dev/null 2>&1 || true

if [ "$INSTALL_HOOKS" = 1 ]; then
  echo "==> Installing hooks"
  found=0
  for config_dir in "$HOME"/.claude*; do
    [ -d "$config_dir" ] || continue
    "$HOME_DIR/bin/cv-hook" install-hooks "$config_dir"
    found=1
  done
  [ "$found" = 1 ] || echo "    no Claude config directories found under $HOME"
fi

if [ "$INSTALL_PLUGIN" = 1 ]; then
  PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"
  if [ -n "$PLUGIN_DIR" ] && [ -d "$PLUGIN_DIR" ]; then
    ln -sf "$HOME_DIR/.venv/lib"/python*/site-packages/claude_voice/menubar/plugin.sh \
      "$PLUGIN_DIR/claude-voice.10s.sh"
    echo "==> Menu-bar plugin linked into $PLUGIN_DIR"
  else
    echo "    SwiftBar not detected; skipping the menu-bar plugin"
  fi
fi

echo
echo "Done. Try:  $HOME_DIR/bin/cv-hook doctor"
echo "Add to your shell:  alias cv='$HOME_DIR/bin/cv-hook'"
```

`uninstall.sh`:

```bash
#!/usr/bin/env bash
# Remove the hooks and the installation. User data is kept unless --purge is given.
set -euo pipefail

HOME_DIR="${CLAUDE_VOICE_HOME:-$HOME/.claude-voice}"
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

for config_dir in "$HOME"/.claude*; do
  [ -d "$config_dir" ] || continue
  [ -x "$HOME_DIR/bin/cv-hook" ] && "$HOME_DIR/bin/cv-hook" remove-hooks "$config_dir" || true
done

PLUGIN_DIR="$(defaults read com.ameba.SwiftBar PluginDirectory 2>/dev/null || true)"
[ -n "$PLUGIN_DIR" ] && rm -f "$PLUGIN_DIR/claude-voice.10s.sh"

rm -rf "$HOME_DIR/.venv" "$HOME_DIR/bin"
if [ "$PURGE" = 1 ]; then
  rm -rf "$HOME_DIR"
  echo "Removed everything, including history and settings."
else
  echo "Removed the installation. History and settings are still in $HOME_DIR."
fi
```

Also add the `language` subcommand used by the installer, in `build_parser()`:

```python
    language = sub.add_parser("language")
    language.add_argument("value")
```

and in `main()`:

```python
    if args.command == "language":
        from .i18n import available_languages

        if args.value not in available_languages():
            print(f"unknown language {args.value!r}; available: {', '.join(available_languages())}", file=sys.stderr)
            return 1
        config.language = args.value
        config_module.save(paths, config)
        print(args.value)
        return 0
```

- [ ] **Step 4: Run it to verify it passes**

```bash
chmod +x install.sh uninstall.sh
CLAUDE_VOICE_HOME=/tmp/cv-test ./install.sh --no-hooks --no-menubar --language en
/tmp/cv-test/bin/cv-hook status
/tmp/cv-test/bin/cv-hook doctor
CLAUDE_VOICE_HOME=/tmp/cv-test ./uninstall.sh --purge
```

Expected: `status` prints `mode: notify · engine: edge · ...`, `doctor` prints its checks,
and the uninstall leaves no `/tmp/cv-test`.

- [ ] **Step 5: Commit**

```bash
git add install.sh uninstall.sh src/claude_voice/cli.py
git commit -m "feat: installer and uninstaller"
```

---

## Task 30: README, licence and the switch-over

**Files:**
- Create: `README.md`, `LICENSE`, `CONTRIBUTING.md`

- [ ] **Step 1: Write the failing test**

`tests/test_readme.py`:

```python
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"


def test_readme_states_the_platform_honestly():
    assert "macOS" in README.read_text()


def test_readme_shows_the_install_command():
    assert "./install.sh" in README.read_text()


def test_readme_documents_every_mode():
    text = README.read_text()

    for mode in ("off", "notify", "voice", "both"):
        assert f"`{mode}`" in text


def test_licence_exists():
    assert (README.parent / "LICENSE").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_readme.py -v`
Expected: FAIL with `FileNotFoundError: README.md`

- [ ] **Step 3: Write minimal implementation**

`README.md` — must contain, at minimum:

```markdown
# claude-voice

Claude Code tells you when it needs you. A short banner when it asks a question, a spoken
one-line summary when a turn ends, and a menu-bar item that keeps the history.

**macOS only.** It leans on `say`, `afplay`, `terminal-notifier` and SwiftBar.

## Install

    git clone https://github.com/<you>/claude-voice
    cd claude-voice
    ./install.sh

The installer creates its own virtual environment, writes a small shim, and wires the hooks
into every Claude Code config directory it finds, backing up each `settings.json` first.

## Modes

| Mode | Behaviour |
| --- | --- |
| `off` | Silent |
| `notify` | macOS banner only |
| `voice` | Spoken only |
| `both` | Banner and speech |

Set them per scope — the most specific one wins:

    cv mode voice                          # everywhere
    cv mode off --scope alias              # this Claude alias
    cv mode both --scope project           # this directory

## Everyday commands

    cv status          cv snooze 30       cv resume
    cv history         cv play <id>       cv replay
    cv skip            cv shut            cv doctor

## Voices

Speech goes through `edge-tts` (Azure neural voices, no API key) and falls back to the
built-in macOS synthesiser when the network is unavailable. Pick a voice in
`~/.claude-voice/config.toml`.

## How it works

One machine-wide lock guarantees a single utterance at a time, so several Claude aliases
running in parallel never talk over each other. Questions jump ahead of summaries.
Everything reported is kept in `history.jsonl` and can be replayed later.
```

`LICENSE`: the standard MIT text.

`CONTRIBUTING.md`: one page — run `pip install -e ".[dev]"`, run `pytest`, no network in
tests, new languages go in `src/claude_voice/i18n/` and must pass the completeness test.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest -v`
Expected: PASS, the whole suite green

- [ ] **Step 5: Commit**

```bash
git add README.md LICENSE CONTRIBUTING.md tests/test_readme.py
git commit -m "docs: README, licence and contributing guide"
```

- [ ] **Step 6: Switch over from the prototype**

Only after everything above is green:

```bash
./install.sh --language uk
~/.claude-voice/bin/cv-hook migrate
~/.claude-voice/bin/cv-hook doctor
```

Then remove the old hooks by hand from each `settings.json` (they point at
`~/.claude-tts/bin/`), and keep `~/.claude-tts` on disk as the rollback until the new
installation has survived a few days of real use.

---

## Notes for the implementer

- **Commits:** the plan shows a commit per task because each one is a coherent unit. If you
  prefer, batch them into a handful of logical commits at the end instead — the boundaries
  are the same either way.
- **No network in tests.** Every test that would reach `edge-tts` or `claude` replaces the
  subprocess call. If a test starts needing the network, the seam is in the wrong place.
- **Python version.** `tomllib` arrived in 3.11; `tomli` covers older interpreters and is
  already a dependency, so both work.

