# Codex Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Report end-of-turn summaries from Codex through the same queue, history, speech and menu bar that already serve Claude Code.

**Architecture:** Codex's single `notify` slot is already taken by Codex Computer Use, so our shim takes the slot and chains to the stored original before doing anything of its own. Everything downstream of the hook is reused unchanged; the new code is one hook module, an agent label, an installer step and a doctor check.

**Tech Stack:** Python 3.9+, pytest, `tomli`/`tomli_w` for Codex's `config.toml`.

**Spec:** `docs/superpowers/specs/2026-08-07-codex-support-design.md`

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/cvoice/agents.py` | Which agent a message came from, and the label spoken for it |
| `src/cvoice/codex.py` | Reading Codex's own files: config path, `notify`, rollout transcripts |
| `src/cvoice/hooks/codex.py` | The notify entry point: chain, parse, gate, emit |
| `src/cvoice/history.py` (modify) | An `agent` field on stored entries |
| `src/cvoice/hooks/common.py` (modify) | Carry the agent through the context and into the label |
| `src/cvoice/cli.py` (modify) | `hook codex`, `install-codex`, `remove-codex` |
| `src/cvoice/doctor.py` (modify) | Is `notify` still ours |
| `install.sh`, `uninstall.sh` (modify) | Call the two new subcommands |

Codex file access is deliberately separate from the hook: `codex.py` knows the layout of
`~/.codex`, `hooks/codex.py` knows what to do when a turn ends. Neither needs the other's
internals, and only the first needs a temporary directory in its tests.

---

## Task 1: The agent a message came from

**Files:**
- Create: `src/cvoice/agents.py`
- Test: `tests/test_agents.py`

- [ ] **Step 1: Write the failing test**

`tests/test_agents.py`:

```python
from cvoice.agents import CLAUDE, CODEX, label_for


def test_claude_is_labelled_by_project_alone():
    """The label people already hear must not change for Claude."""
    assert label_for(CLAUDE, "billing-api") == "billing-api"


def test_codex_is_named_in_the_label():
    assert label_for(CODEX, "billing-api") == "Codex, billing-api"


def test_a_missing_project_still_names_the_agent():
    assert label_for(CODEX, "") == "Codex"


def test_a_missing_project_for_claude_is_empty():
    assert label_for(CLAUDE, "") == ""


def test_an_unknown_agent_is_treated_as_claude():
    """Old history entries have no agent field; they were all Claude."""
    assert label_for("", "billing-api") == "billing-api"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_agents.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cvoice.agents'`

- [ ] **Step 3: Write minimal implementation**

`src/cvoice/agents.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_agents.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/cvoice/agents.py tests/test_agents.py
git commit -m "Add the agent a message came from"
```

---

## Task 2: An agent field on history entries

**Files:**
- Modify: `src/cvoice/history.py`
- Test: `tests/test_history.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_history.py`:

```python
def test_the_agent_is_stored(tmp_path):
    paths = _paths(tmp_path)

    entry = add(paths, kind="tldr", label="app", text="Done.", agent="codex")

    assert entry.agent == "codex"
    assert recent(paths)[0].agent == "codex"


def test_the_agent_defaults_to_claude(tmp_path):
    """Every entry written before this field existed was Claude."""
    paths = _paths(tmp_path)

    assert add(paths, kind="tldr", label="app", text="Done.").agent == "claude"


def test_an_entry_without_an_agent_field_still_loads(tmp_path):
    import json

    paths = _paths(tmp_path)
    paths.history_file.write_text(
        json.dumps({"id": "1", "ts": 1, "kind": "tldr", "label": "app", "text": "old"}) + "\n"
    )

    assert recent(paths)[0].agent == "claude"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_history.py -v`
Expected: FAIL with `TypeError: add() got an unexpected keyword argument 'agent'`

- [ ] **Step 3: Write minimal implementation**

In `src/cvoice/history.py`, add the import and the field. Change the `Entry` dataclass:

```python
from .agents import CLAUDE


@dataclass
class Entry:
    id: str
    ts: float
    kind: str
    label: str
    text: str
    directory: str = ""
    namespace: str = ""
    agent: str = CLAUDE
```

Change the signature of `add` to accept it, and pass it into the constructed `Entry`:

```python
def add(
    paths: Paths,
    kind: str,
    label: str,
    text: str,
    directory: str = "",
    namespace: str = "",
    agent: str = CLAUDE,
    keep: int = KEEP_DEFAULT,
) -> Optional[Entry]:
```

and inside, where the entry is built:

```python
    entry = Entry(
        id=_new_id(),
        ts=time.time(),
        kind=kind,
        label=label,
        text=text,
        directory=directory,
        namespace=namespace,
        agent=agent,
    )
```

`_parse` needs no change: `Entry(**json.loads(line))` fills the default for old lines that
lack the key.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_history.py tests/test_migrate.py -v`
Expected: PASS. `test_migrate.py` is included because it filters old records against
`Entry.__dataclass_fields__`, which has just grown a member.

- [ ] **Step 5: Commit**

```bash
git add src/cvoice/history.py tests/test_history.py
git commit -m "Record which agent a history entry came from"
```

---

## Task 3: Carry the agent through the hook context

**Files:**
- Modify: `src/cvoice/hooks/common.py`
- Test: `tests/test_hooks_common.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hooks_common.py`:

```python
def test_the_context_defaults_to_claude(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/app")

    context = common.build_context({"session_id": "s"}, paths=Paths(root=tmp_path))

    assert context.agent == "claude"
    assert context.label == "app"


def test_a_codex_context_is_labelled_with_the_agent(tmp_path):
    context = common.build_context(
        {"session_id": "s"}, paths=Paths(root=tmp_path), agent="codex", project_dir="/work/app"
    )

    assert context.label == "Codex, app"


def test_an_explicit_project_overrides_the_environment(tmp_path, monkeypatch):
    """Codex tells us its working directory; there is no CLAUDE_PROJECT_DIR to read."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/work/wrong")

    context = common.build_context(
        {"session_id": "s"}, paths=Paths(root=tmp_path), agent="codex", project_dir="/work/right"
    )

    assert context.project_dir == "/work/right"


def test_the_agent_reaches_history(tmp_path):
    from cvoice.history import recent

    context = common.build_context(
        {"session_id": "s"},
        paths=Paths(root=tmp_path),
        agent="codex",
        project_dir="/work/app",
    )
    context.mode = "notify"

    common.emit(context, kind="tldr", text="Done.", notifier=lambda **kw: None, worker=lambda: None)

    assert recent(context.paths)[0].agent == "codex"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_hooks_common.py -v`
Expected: FAIL with `AttributeError: 'Context' object has no attribute 'agent'`

- [ ] **Step 3: Write minimal implementation**

In `src/cvoice/hooks/common.py`, import the agent helpers:

```python
from ..agents import CLAUDE, label_for
```

Give `Context` the field and rewrite its `label` property:

```python
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
```

Let `build_context` accept both, so a caller that already knows them does not have to lie
through environment variables:

```python
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
```

Finally pass the agent into history, inside `emit`:

```python
    history.add(
        context.paths,
        kind=kind,
        label=context.label,
        text=text,
        directory=context.project_dir,
        namespace=context.namespace,
        agent=context.agent,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, whole suite green

- [ ] **Step 5: Commit**

```bash
git add src/cvoice/hooks/common.py tests/test_hooks_common.py
git commit -m "Carry the agent through the hook context"
```

---

## Task 4: Reading Codex's config

**Files:**
- Create: `src/cvoice/codex.py`
- Test: `tests/test_codex.py`

- [ ] **Step 1: Write the failing test**

`tests/test_codex.py`:

```python
import cvoice.codex as codex


def _config(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_a_missing_config_means_codex_is_not_installed(tmp_path):
    assert codex.is_installed(tmp_path / "nowhere.toml") is False


def test_an_existing_config_means_it_is(tmp_path):
    assert codex.is_installed(_config(tmp_path, "")) is True


def test_the_notify_command_is_read(tmp_path):
    path = _config(tmp_path, 'notify = ["/opt/thing", "turn-ended"]\n')

    assert codex.read_notify(path) == ["/opt/thing", "turn-ended"]


def test_no_notify_key_reads_as_empty(tmp_path):
    assert codex.read_notify(_config(tmp_path, "model = \"gpt\"\n")) == []


def test_a_string_notify_is_read_as_one_word_command(tmp_path):
    """The key is documented as a list, but a plain string must not crash us."""
    path = _config(tmp_path, 'notify = "/opt/thing"\n')

    assert codex.read_notify(path) == ["/opt/thing"]


def test_a_malformed_config_reads_as_empty(tmp_path):
    assert codex.read_notify(_config(tmp_path, "notify = [broken\n")) == []


def test_writing_notify_leaves_other_settings_alone(tmp_path):
    path = _config(
        tmp_path,
        'notify = ["/opt/thing"]\n\n[plugins."browser@bundled"]\nenabled = true\n',
    )

    codex.write_notify(path, ["/new/shim", "hook", "codex"])

    assert codex.read_notify(path) == ["/new/shim", "hook", "codex"]
    assert 'browser@bundled' in path.read_text()
    assert "enabled = true" in path.read_text()


def test_writing_into_a_config_without_notify_adds_it(tmp_path):
    path = _config(tmp_path, 'model = "gpt"\n')

    codex.write_notify(path, ["/new/shim"])

    assert codex.read_notify(path) == ["/new/shim"]
    assert 'model = "gpt"' in path.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_codex.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cvoice.codex'`

- [ ] **Step 3: Write minimal implementation**

`src/cvoice/codex.py`:

```python
"""Codex's own files.

Only two things are needed: the `notify` slot in its config, and the rollout transcript of
a finished turn. Codex rewrites this config itself, so nothing of ours is ever stored in
it beyond the one key we own.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import List, Optional

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on older interpreters
    import tomli as tomllib

import tomli_w


def config_path() -> Path:
    home = os.environ.get("CODEX_HOME")
    return Path(home) / "config.toml" if home else Path.home() / ".codex" / "config.toml"


def sessions_dir() -> Path:
    home = os.environ.get("CODEX_HOME")
    return Path(home) / "sessions" if home else Path.home() / ".codex" / "sessions"


def is_installed(config: Optional[Path] = None) -> bool:
    return (config or config_path()).exists()


def _load(config: Path) -> dict:
    try:
        return tomllib.loads(config.read_text())
    except (FileNotFoundError, OSError, tomllib.TOMLDecodeError):
        return {}


def read_notify(config: Optional[Path] = None) -> List[str]:
    """The configured notify command, as a list. Empty when unset or unreadable."""
    value = _load(config or config_path()).get("notify")
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def write_notify(config: Path, command: List[str]) -> None:
    """Replace the notify command, preserving everything else in the file."""
    data = _load(config)
    data["notify"] = list(command)
    config.write_bytes(tomli_w.dumps(data).encode())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_codex.py -v`
Expected: PASS, 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/cvoice/codex.py tests/test_codex.py
git commit -m "Read and write Codex's notify slot"
```

---

## Task 5: Did the Codex turn do any work

**Files:**
- Modify: `src/cvoice/codex.py`
- Test: `tests/test_codex.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_codex.py`:

```python
import json


def _rollout(tmp_path, records, name="rollout-2026-08-07T12-00-00-abc.jsonl"):
    day = tmp_path / "sessions" / "2026" / "08" / "07"
    day.mkdir(parents=True, exist_ok=True)
    path = day / name
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return path


def _tool_call():
    return {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "shell"}}


def _user():
    return {"type": "event_msg", "payload": {"type": "user_message", "message": "do it"}}


def _complete(turn_id):
    return {
        "type": "event_msg",
        "payload": {"type": "task_complete", "turn_id": turn_id, "last_agent_message": "done"},
    }


def test_a_turn_that_called_a_tool_did_work(tmp_path):
    _rollout(tmp_path, [_user(), _tool_call(), _complete("t1")])

    assert codex.turn_used_tools("t1", tmp_path / "sessions") is True


def test_a_turn_that_only_talked_did_not(tmp_path):
    _rollout(tmp_path, [_user(), _complete("t1")])

    assert codex.turn_used_tools("t1", tmp_path / "sessions") is False


def test_only_the_named_turn_counts(tmp_path):
    """An earlier turn's tools must not make this one look busy."""
    _rollout(tmp_path, [_user(), _tool_call(), _complete("t1"), _user(), _complete("t2")])

    assert codex.turn_used_tools("t2", tmp_path / "sessions") is False


def test_an_unknown_turn_is_assumed_to_have_worked(tmp_path):
    """A missed summary is worse than a needless one, so silence is not the default."""
    _rollout(tmp_path, [_user(), _complete("t1")])

    assert codex.turn_used_tools("nope", tmp_path / "sessions") is True


def test_a_missing_sessions_directory_is_assumed_to_have_worked(tmp_path):
    assert codex.turn_used_tools("t1", tmp_path / "nowhere") is True


def test_a_corrupt_line_does_not_break_the_scan(tmp_path):
    path = _rollout(tmp_path, [_user(), _tool_call(), _complete("t1")])
    with path.open("a") as handle:
        handle.write("{not json\n")

    assert codex.turn_used_tools("t1", tmp_path / "sessions") is True


def test_the_newest_rollout_is_searched_first(tmp_path):
    import os
    import time

    old = _rollout(tmp_path, [_user(), _complete("t1")], name="rollout-old.jsonl")
    new = _rollout(tmp_path, [_user(), _tool_call(), _complete("t2")], name="rollout-new.jsonl")
    os.utime(old, (time.time() - 600, time.time() - 600))

    assert codex.turn_used_tools("t2", tmp_path / "sessions") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_codex.py -v`
Expected: FAIL with `AttributeError: module 'cvoice.codex' has no attribute 'turn_used_tools'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/cvoice/codex.py`:

```python
ROLLOUTS_SEARCHED = 5


def _rollout_files(sessions: Path) -> List[Path]:
    """Newest first. Only a handful: the turn that just ended is in a recent file."""
    try:
        files = [path for path in sessions.rglob("rollout-*.jsonl") if path.is_file()]
    except OSError:
        return []
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[:ROLLOUTS_SEARCHED]


def turn_used_tools(turn_id: str, sessions: Optional[Path] = None) -> bool:
    """Did this turn call a tool, or only talk?

    Returns True when we cannot tell. Unlike Claude Code there is no second source of
    truth here, and a missed summary is worse than an occasional needless one.
    """
    for path in _rollout_files(sessions or sessions_dir()):
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue

        used = False
        for line in lines:
            try:
                payload = json.loads(line).get("payload") or {}
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            kind = payload.get("type")
            if kind == "user_message":
                used = False  # a new turn starts here
            elif kind in ("custom_tool_call", "function_call", "local_shell_call"):
                used = True
            elif kind == "task_complete" and payload.get("turn_id") == turn_id:
                return used
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_codex.py -v`
Expected: PASS, 15 passed

- [ ] **Step 5: Commit**

```bash
git add src/cvoice/codex.py tests/test_codex.py
git commit -m "Tell whether a Codex turn called any tool"
```

---

## Task 6: Reading the notify payload

**Files:**
- Create: `src/cvoice/hooks/codex.py`
- Test: `tests/test_hook_codex.py`

- [ ] **Step 1: Write the failing test**

`tests/test_hook_codex.py`:

```python
import json

from cvoice.hooks.codex import parse_payload


def _payload(**overrides):
    data = {
        "type": "agent-turn-complete",
        "turn-id": "t1",
        "last-assistant-message": "Done, all tests pass.",
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def test_json_in_the_last_argument_is_found():
    parsed = parse_payload(["turn-ended", _payload()])

    assert parsed["message"] == "Done, all tests pass."
    assert parsed["turn_id"] == "t1"


def test_json_in_the_first_argument_is_found():
    """The argv layout was never observed directly, so position is not assumed."""
    parsed = parse_payload([_payload(), "turn-ended"])

    assert parsed["message"] == "Done, all tests pass."


def test_json_in_the_middle_is_found():
    parsed = parse_payload(["a", _payload(), "b"])

    assert parsed["message"] == "Done, all tests pass."


def test_the_snake_case_message_key_is_accepted():
    raw = json.dumps({"turn_id": "t2", "last_agent_message": "Done."})

    parsed = parse_payload([raw])

    assert parsed == {"message": "Done.", "turn_id": "t2"}


def test_the_plain_message_key_is_accepted():
    raw = json.dumps({"turn_id": "t3", "message": "Done."})

    assert parse_payload([raw])["message"] == "Done."


def test_no_arguments_parse_to_nothing():
    assert parse_payload([]) is None


def test_arguments_without_json_parse_to_nothing():
    assert parse_payload(["turn-ended", "--verbose"]) is None


def test_malformed_json_parses_to_nothing():
    assert parse_payload(["{not json"]) is None


def test_json_without_a_message_parses_to_nothing():
    assert parse_payload([json.dumps({"turn-id": "t1"})]) is None


def test_an_empty_message_parses_to_nothing():
    assert parse_payload([_payload(**{"last-assistant-message": "   "})]) is None


def test_a_missing_turn_id_is_survivable():
    raw = json.dumps({"last-assistant-message": "Done."})

    assert parse_payload([raw]) == {"message": "Done.", "turn_id": ""}


def test_a_json_array_is_not_mistaken_for_a_payload():
    assert parse_payload([json.dumps(["a", "b"])]) is None


def test_the_working_directory_is_read_when_present():
    raw = json.dumps({"turn_id": "t1", "message": "Done.", "cwd": "/work/app"})

    assert parse_payload([raw])["cwd"] == "/work/app"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_hook_codex.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cvoice.hooks.codex'`

- [ ] **Step 3: Write minimal implementation**

`src/cvoice/hooks/codex.py`:

```python
"""Codex has finished a turn.

Codex offers one notification slot, already occupied on a normal install, so this runs as
a chain: the stored original command goes first, then our own work. It reports summaries
only - Codex surfaces neither questions nor permission prompts as events.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional

MESSAGE_KEYS = ("last-assistant-message", "last_agent_message", "message")
TURN_KEYS = ("turn-id", "turn_id")
CWD_KEYS = ("cwd", "workdir", "working-directory")


def parse_payload(args: List[str]) -> Optional[Dict[str, str]]:
    """Pull the finished turn out of whatever Codex passed on the command line.

    Every argument is tried, because the exact layout is undocumented and has not been
    observed directly. A payload with no message is not worth reporting.
    """
    for argument in args:
        try:
            data = json.loads(argument)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue

        message = ""
        for key in MESSAGE_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                message = value.strip()
                break
        if not message:
            continue

        turn_id = ""
        for key in TURN_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value:
                turn_id = value
                break

        parsed = {"message": message, "turn_id": turn_id}
        for key in CWD_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value:
                parsed["cwd"] = value
                break
        return parsed
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_hook_codex.py -v`
Expected: PASS, 13 passed

- [ ] **Step 5: Commit**

```bash
git add src/cvoice/hooks/codex.py tests/test_hook_codex.py
git commit -m "Read the turn out of Codex's notify payload"
```

---

## Task 7: Chaining to the original notify command

**Files:**
- Modify: `src/cvoice/hooks/codex.py`
- Modify: `src/cvoice/config.py`
- Test: `tests/test_hook_codex.py` (append), `tests/test_config.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_the_original_codex_notify_is_stored(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()

    save(paths, Config(codex_original_notify=["/opt/thing", "turn-ended"]))

    assert load(paths).codex_original_notify == ["/opt/thing", "turn-ended"]


def test_no_stored_notify_by_default(tmp_path):
    paths = Paths(root=tmp_path)
    paths.ensure()

    assert load(paths).codex_original_notify == []
```

Append to `tests/test_hook_codex.py`:

```python
import cvoice.hooks.codex as codex_hook


class FakePopen:
    def __init__(self):
        self.calls = []
        self.kwargs = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        self.kwargs.append(kwargs)

        class Handle:
            pass

        return Handle()


def test_the_original_command_is_called_with_its_own_arguments(monkeypatch):
    popen = FakePopen()
    monkeypatch.setattr(codex_hook.subprocess, "Popen", popen)

    codex_hook.chain(["/opt/thing", "turn-ended"], ["turn-ended", "{}"])

    assert popen.calls == [["/opt/thing", "turn-ended", "turn-ended", "{}"]]


def test_the_chain_is_detached(monkeypatch):
    popen = FakePopen()
    monkeypatch.setattr(codex_hook.subprocess, "Popen", popen)

    codex_hook.chain(["/opt/thing"], [])

    assert popen.kwargs[0]["start_new_session"] is True


def test_no_stored_command_means_no_chain(monkeypatch):
    popen = FakePopen()
    monkeypatch.setattr(codex_hook.subprocess, "Popen", popen)

    codex_hook.chain([], ["anything"])

    assert popen.calls == []


def test_a_chain_that_cannot_start_is_survivable(monkeypatch):
    def explode(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(codex_hook.subprocess, "Popen", explode)

    codex_hook.chain(["/gone"], [])  # must not raise


def test_a_chain_that_cannot_start_is_recorded(tmp_path, monkeypatch):
    """The stored command can go missing - Computer Use may simply be uninstalled."""
    from cvoice.health import failures
    from cvoice.state import Paths

    paths = Paths(root=tmp_path)
    paths.ensure()

    def explode(argv, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(codex_hook.subprocess, "Popen", explode)

    codex_hook.chain(["/gone"], [], paths=paths)

    assert [failure.component for failure in failures(paths)] == ["codex-notify-chain"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_hook_codex.py tests/test_config.py -v`
Expected: FAIL with `TypeError: Config.__init__() got an unexpected keyword argument 'codex_original_notify'`

- [ ] **Step 3: Write minimal implementation**

In `src/cvoice/config.py`, add the field to the dataclass. Note it needs a factory, since a
mutable default is not allowed:

```python
from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class Config:
    language: str = "en"
    mode: str = "notify"
    engine: str = "edge"
    model: str = "sonnet"
    mute_while_mic_in_use: bool = True
    edge_voice: str = "en-US-AriaNeural"
    edge_rate: str = "+0%"
    say_voice: str = "Samantha"
    say_rate: int = 180
    codex_original_notify: List[str] = field(default_factory=list)
```

In `load`, read it:

```python
        codex_original_notify=[str(item) for item in data.get("codex_original_notify", [])],
```

and in `save`, write it:

```python
        "codex_original_notify": list(config.codex_original_notify),
```

Append the chain to `src/cvoice/hooks/codex.py`:

```python
import subprocess

from ..state import Paths


def chain(original: List[str], args: List[str], paths: Optional[Paths] = None) -> None:
    """Run the command our shim displaced, with its own arguments plus ours.

    This happens before any work of our own, so that a failure on our side cannot stop
    whatever was in the slot first - on a normal install, Codex Computer Use.

    Only a failure to start is visible from here: the process is detached on purpose, so
    whatever it does afterwards is its own business.
    """
    if not original:
        return
    try:
        subprocess.Popen(
            list(original) + list(args),
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as error:  # noqa: BLE001 - the chain must never take us down
        if paths is not None:
            from .. import health

            health.record(paths, "codex-notify-chain", str(error))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_hook_codex.py tests/test_config.py -v`
Expected: PASS, 17 and 13 passed respectively

- [ ] **Step 5: Commit**

```bash
git add src/cvoice/hooks/codex.py src/cvoice/config.py tests/test_hook_codex.py tests/test_config.py
git commit -m "Chain to the notify command our shim displaced"
```

---

## Task 8: The Codex hook end to end

**Files:**
- Modify: `src/cvoice/hooks/codex.py`
- Test: `tests/test_hook_codex.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hook_codex.py`:

```python
from cvoice.config import Config, save
from cvoice.history import recent
from cvoice.state import Paths


def _prepare(tmp_path, mode="both", original=None):
    paths = Paths(root=tmp_path / "home")
    paths.ensure()
    save(paths, Config(language="en", mode=mode, codex_original_notify=original or []))
    return paths


def _run(paths, args, monkeypatch, summary="Summarised.", used_tools=True):
    import cvoice.codex as codex_module

    monkeypatch.delenv("CVOICE_CHILD", raising=False)
    monkeypatch.setattr(codex_hook.summarize, "run", lambda text, pack, **kw: summary)
    monkeypatch.setattr(codex_module, "turn_used_tools", lambda turn_id, sessions=None: used_tools)
    sent = []
    codex_hook.handle(
        args,
        paths=paths,
        notifier=lambda **kw: sent.append(kw),
        worker=lambda: None,
    )
    return sent


def test_a_finished_turn_is_reported(tmp_path, monkeypatch):
    """The default payload is short English, so it is used verbatim - the summariser
    path has its own test below."""
    paths = _prepare(tmp_path)

    _run(paths, ["turn-ended", _payload()], monkeypatch, summary="unused")

    assert [entry.text for entry in recent(paths)] == ["Done, all tests pass."]


def test_a_long_turn_is_summarised(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)
    long_reply = _payload(**{"last-assistant-message": "word " * 200})

    _run(paths, [long_reply], monkeypatch, summary="Short summary.")

    assert [entry.text for entry in recent(paths)] == ["Short summary."]


def test_the_entry_is_marked_as_codex(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, [_payload()], monkeypatch)

    entry = recent(paths)[0]
    assert entry.agent == "codex"
    assert entry.label.startswith("Codex")


def test_the_same_turn_is_not_reported_twice(tmp_path, monkeypatch):
    """Codex may call notify more than once for one turn."""
    paths = _prepare(tmp_path)

    _run(paths, [_payload()], monkeypatch)
    _run(paths, [_payload()], monkeypatch)

    assert len(recent(paths)) == 1


def test_a_different_turn_is_reported(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, [_payload()], monkeypatch)
    _run(paths, [_payload(**{"turn-id": "t2", "last-assistant-message": "Second."})], monkeypatch)

    assert len(recent(paths)) == 2


def test_a_turn_that_did_nothing_is_not_reported(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)

    _run(
        paths,
        [_payload(**{"last-assistant-message": "Hi! What shall we work on?"})],
        monkeypatch,
        used_tools=False,
    )

    assert recent(paths) == []


def test_the_project_comes_from_the_payload(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)

    _run(paths, [_payload(cwd="/work/billing-api")], monkeypatch)

    assert recent(paths)[0].label == "Codex, billing-api"


def test_mode_off_reports_nothing(tmp_path, monkeypatch):
    paths = _prepare(tmp_path, mode="off")

    _run(paths, [_payload()], monkeypatch)

    assert recent(paths) == []


def test_the_chain_runs_even_when_the_mode_is_off(tmp_path, monkeypatch):
    """Being silent is our business; the displaced command still has its own."""
    popen = FakePopen()
    monkeypatch.setattr(codex_hook.subprocess, "Popen", popen)
    paths = _prepare(tmp_path, mode="off", original=["/opt/thing"])

    codex_hook.main(["turn-ended"], paths=paths)

    assert popen.calls == [["/opt/thing", "turn-ended"]]


def test_the_chain_runs_even_when_our_work_raises(tmp_path, monkeypatch):
    popen = FakePopen()
    monkeypatch.setattr(codex_hook.subprocess, "Popen", popen)
    monkeypatch.setattr(codex_hook, "handle", lambda *a, **kw: 1 / 0)
    paths = _prepare(tmp_path, original=["/opt/thing"])

    codex_hook.main(["turn-ended", _payload()], paths=paths)

    assert popen.calls == [["/opt/thing", "turn-ended", _payload()]]


def test_nothing_happens_inside_our_own_summariser(tmp_path, monkeypatch):
    paths = _prepare(tmp_path)
    monkeypatch.setenv("CVOICE_CHILD", "1")
    popen = FakePopen()
    monkeypatch.setattr(codex_hook.subprocess, "Popen", popen)

    codex_hook.main([_payload()], paths=paths)

    assert recent(paths) == []
    assert popen.calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_hook_codex.py -v`
Expected: FAIL with `AttributeError: module 'cvoice.hooks.codex' has no attribute 'handle'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/cvoice/hooks/codex.py`:

```python
from typing import Callable

from .. import codex as codex_files
from .. import config as config_module
from .. import summarize
from ..agents import CODEX
from . import common

VERBATIM_LIMIT = 300
MIN_SUMMARIZE = 40
MIN_CHATTER = 120


def handle(
    args: List[str],
    paths: Optional[Paths] = None,
    notifier: Optional[Callable[..., None]] = None,
    worker: Optional[Callable[[], None]] = None,
) -> None:
    parsed = parse_payload(args)
    if parsed is None:
        return

    context = common.build_context(
        {"session_id": parsed["turn_id"] or "codex"},
        paths=paths,
        agent=CODEX,
        project_dir=parsed.get("cwd"),
    )
    if context.mode == "off":
        return

    # Codex can call notify more than once for a turn; the id is what makes it one turn.
    if parsed["turn_id"]:
        seen = context.paths.state_dir / f"codex-{parsed['turn_id']}"
        if seen.exists():
            return
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text("")

    clean = summarize.strip_markdown(parsed["message"])
    if not clean:
        return

    if not codex_files.turn_used_tools(parsed["turn_id"]) and len(clean) < MIN_CHATTER:
        return

    if len(clean) < MIN_SUMMARIZE or (
        len(clean) <= VERBATIM_LIMIT and context.pack.matches_language(clean)
    ):
        spoken = summarize.condense(clean)
    else:
        spoken = summarize.run(clean, context.pack, model=context.config.model) or context.pack.phrase(
            "summary.fallback"
        )

    common.emit(context, kind="tldr", text=spoken, priority=1, notifier=notifier, worker=worker)


def main(args: List[str], paths: Optional[Paths] = None) -> None:
    """The notify entry point. The chain comes first, whatever happens afterwards."""
    if common.is_child():
        return

    paths = paths or Paths.default()
    paths.ensure()
    chain(config_module.load(paths).codex_original_notify, args, paths=paths)

    try:
        handle(args, paths=paths)
    except Exception:  # noqa: BLE001 - a hook that crashes must not surface to the user
        pass
```


- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_hook_codex.py -v`
Expected: PASS, 27 passed

- [ ] **Step 5: Commit**

```bash
git add src/cvoice/hooks/codex.py tests/test_hook_codex.py
git commit -m "Report a finished Codex turn"
```

---

## Task 9: Installing and removing the Codex hook

**Files:**
- Modify: `src/cvoice/install.py`
- Test: `tests/test_install.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_install.py`:

```python
from cvoice.codex import read_notify
from cvoice.config import Config, load, save
from cvoice.install import install_codex, remove_codex
from cvoice.state import Paths


def _home(tmp_path):
    paths = Paths(root=tmp_path / "home")
    paths.ensure()
    save(paths, Config())
    return paths


def _codex_config(tmp_path, text='notify = ["/opt/thing", "turn-ended"]\n'):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_the_shim_takes_the_slot(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)

    install_codex(config, paths, shim="/home/me/.cvoice/bin/cv-hook")

    assert read_notify(config) == ["/home/me/.cvoice/bin/cv-hook", "hook", "codex"]


def test_the_displaced_command_is_stored(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)

    install_codex(config, paths, shim="/shim/cv-hook")

    assert load(paths).codex_original_notify == ["/opt/thing", "turn-ended"]


def test_installing_twice_does_not_chain_to_itself(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)

    install_codex(config, paths, shim="/shim/cv-hook")
    install_codex(config, paths, shim="/shim/cv-hook")

    assert load(paths).codex_original_notify == ["/opt/thing", "turn-ended"]
    assert read_notify(config) == ["/shim/cv-hook", "hook", "codex"]


def test_an_empty_slot_is_taken_with_nothing_stored(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path, 'model = "gpt"\n')

    install_codex(config, paths, shim="/shim/cv-hook")

    assert read_notify(config) == ["/shim/cv-hook", "hook", "codex"]
    assert load(paths).codex_original_notify == []


def test_other_codex_settings_survive(tmp_path):
    paths = _home(tmp_path)
    config = _codex_config(
        tmp_path, 'notify = ["/opt/thing"]\n\n[plugins."browser@bundled"]\nenabled = true\n'
    )

    install_codex(config, paths, shim="/shim/cv-hook")

    assert "browser@bundled" in config.read_text()


def test_a_backup_is_written(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)

    install_codex(config, paths, shim="/shim/cv-hook")

    assert len(list(tmp_path.glob("config.toml.backup-*"))) == 1


def test_a_second_run_writes_no_second_backup(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)

    install_codex(config, paths, shim="/shim/cv-hook")
    install_codex(config, paths, shim="/shim/cv-hook")

    assert len(list(tmp_path.glob("config.toml.backup-*"))) == 1


def test_a_missing_codex_is_not_an_error(tmp_path):
    paths = _home(tmp_path)

    assert install_codex(tmp_path / "nowhere.toml", paths, shim="/shim/cv-hook") is False


def test_removal_restores_the_displaced_command(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)
    install_codex(config, paths, shim="/shim/cv-hook")

    remove_codex(config, paths)

    assert read_notify(config) == ["/opt/thing", "turn-ended"]
    assert load(paths).codex_original_notify == []


def test_removal_of_an_empty_original_clears_the_slot(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path, 'model = "gpt"\n')
    install_codex(config, paths, shim="/shim/cv-hook")

    remove_codex(config, paths)

    assert read_notify(config) == []


def test_removal_leaves_someone_elses_slot_alone(tmp_path):
    paths, config = _home(tmp_path), _codex_config(tmp_path)

    remove_codex(config, paths)

    assert read_notify(config) == ["/opt/thing", "turn-ended"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_install.py -v`
Expected: FAIL with `ImportError: cannot import name 'install_codex'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/cvoice/install.py`:

```python
from . import codex as codex_files
from . import config as config_module
from .state import Paths


def _is_ours(command: List[str]) -> bool:
    return bool(command) and SHIM_MARKER in command[0]


def install_codex(codex_config: Path, paths: Paths, shim: str) -> bool:
    """Take Codex's notify slot, remembering whatever was in it. Returns False when Codex
    is not installed.

    The displaced command is stored in our own config, never in Codex's: that file is
    rewritten by the app itself, so recovering the original must not depend on it.
    """
    codex_config = Path(codex_config)
    if not codex_config.exists():
        return False

    current = codex_files.read_notify(codex_config)
    ours = [shim, "hook", "codex"]
    if current == ours:
        return True  # already installed; installing twice must not chain to ourselves

    config = config_module.load(paths)
    if not _is_ours(current):
        config.codex_original_notify = current
        config_module.save(paths, config)

    _backup(codex_config)
    codex_files.write_notify(codex_config, ours)
    return True


def remove_codex(codex_config: Path, paths: Paths) -> bool:
    """Put back whatever we displaced, and forget it."""
    codex_config = Path(codex_config)
    if not codex_config.exists():
        return False
    if not _is_ours(codex_files.read_notify(codex_config)):
        return False  # not ours to restore

    config = config_module.load(paths)
    _backup(codex_config)
    codex_files.write_notify(codex_config, config.codex_original_notify)
    config.codex_original_notify = []
    config_module.save(paths, config)
    return True
```

`_backup` already exists in this module and names its copies `<file>.backup-<timestamp>`,
which is what the tests look for.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_install.py -v`
Expected: PASS, 25 passed

- [ ] **Step 5: Commit**

```bash
git add src/cvoice/install.py tests/test_install.py
git commit -m "Take and restore Codex's notify slot"
```

---

## Task 10: Wiring it into the command line

**Files:**
- Modify: `src/cvoice/cli.py`
- Test: `tests/test_cli.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_the_codex_hook_is_dispatched(tmp_path, monkeypatch):
    import cvoice.hooks.codex as codex_hook

    _home(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(codex_hook, "main", lambda args, paths=None: seen.append(args))

    cli.main(["hook", "codex", "turn-ended", '{"message": "Done."}'])

    assert seen == [["turn-ended", '{"message": "Done."}']]


def test_the_codex_hook_takes_arguments_that_look_like_flags(tmp_path, monkeypatch):
    """Codex chooses the arguments, not us; argparse must not try to interpret them."""
    import cvoice.hooks.codex as codex_hook

    _home(tmp_path, monkeypatch)
    seen = []
    monkeypatch.setattr(codex_hook, "main", lambda args, paths=None: seen.append(args))

    cli.main(["hook", "codex", "--verbose", "{}"])

    assert seen == [["--verbose", "{}"]]


def test_install_codex_reports_when_codex_is_absent(tmp_path, monkeypatch, capsys):
    _home(tmp_path, monkeypatch)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nowhere"))

    assert cli.main(["install-codex"]) == 0
    assert "not installed" in capsys.readouterr().out


def test_install_codex_takes_the_slot(tmp_path, monkeypatch, capsys):
    from cvoice.codex import read_notify

    paths = _home(tmp_path, monkeypatch)
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text('notify = ["/opt/thing"]\n')
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    assert cli.main(["install-codex"]) == 0

    assert read_notify(codex_home / "config.toml") == [
        str(paths.root / "bin" / "cv-hook"), "hook", "codex",
    ]


def test_remove_codex_restores_the_slot(tmp_path, monkeypatch):
    from cvoice.codex import read_notify

    _home(tmp_path, monkeypatch)
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    (codex_home / "config.toml").write_text('notify = ["/opt/thing"]\n')
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    cli.main(["install-codex"])

    assert cli.main(["remove-codex"]) == 0
    assert read_notify(codex_home / "config.toml") == ["/opt/thing"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL with `argument name: invalid choice: 'codex'`

- [ ] **Step 3: Write minimal implementation**

In `src/cvoice/cli.py`, import the new hook next to the others:

```python
from .hooks import codex as codex_hook
```

Codex's arguments are not ours to interpret, so `hook codex` is parsed separately from the
Claude hooks. In `build_parser()`, replace the existing `hook` subparser block with:

```python
    hook = sub.add_parser("hook")
    hook_kind = hook.add_subparsers(dest="name", required=True)
    for name in sorted(HOOKS):
        claude_hook = hook_kind.add_parser(name)
        claude_hook.add_argument("--payload", type=Path, default=None)
        claude_hook.add_argument("--detached", action="store_true")
    codex_parser = hook_kind.add_parser("codex")
    codex_parser.add_argument("args", nargs=argparse.REMAINDER)
```

and add the two installer subcommands:

```python
    sub.add_parser("install-codex")
    sub.add_parser("remove-codex")
```

In `main()`, handle the Codex hook before the Claude ones:

```python
    if args.command == "hook":
        if args.name == "codex":
            codex_hook.main(list(args.args), paths=paths)
            return 0
        HOOKS[args.name].main(common.read_payload(args.payload), detached=args.detached)
        return 0
```

and add the installer commands before the final `return 2`:

```python
    if args.command in ("install-codex", "remove-codex"):
        from .codex import config_path, is_installed
        from .install import install_codex, remove_codex

        codex_config = config_path()
        if not is_installed(codex_config):
            print("Codex is not installed; nothing to do")
            return 0
        shim = str(paths.root / "bin" / "cv-hook")
        if args.command == "install-codex":
            install_codex(codex_config, paths, shim=shim)
            print(f"Codex will report through {shim}")
        else:
            remove_codex(codex_config, paths)
            print("Codex notify restored")
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, whole suite green

- [ ] **Step 5: Commit**

```bash
git add src/cvoice/cli.py tests/test_cli.py
git commit -m "Expose the Codex hook and its installer"
```

---

## Task 11: Reporting the Codex hook in doctor

**Files:**
- Modify: `src/cvoice/doctor.py`
- Test: `tests/test_doctor.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_doctor.py`:

```python
def _codex(tmp_path, notify):
    codex_home = tmp_path / "codex"
    codex_home.mkdir(exist_ok=True)
    (codex_home / "config.toml").write_text(f"notify = {notify}\n")
    return codex_home


def test_an_installed_codex_hook_passes(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    monkeypatch.setenv("CODEX_HOME", str(_codex(tmp_path, '["/x/cv-hook", "hook", "codex"]')))

    results = {check.name: check for check in checks(_paths(tmp_path), Config())}

    assert results["codex"].ok is True


def test_a_displaced_codex_hook_is_reported(tmp_path, monkeypatch):
    """Codex rewrites its own config, so our slot can be taken back at any time."""
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    monkeypatch.setenv("CODEX_HOME", str(_codex(tmp_path, '["/opt/other"]')))

    results = {check.name: check for check in checks(_paths(tmp_path), Config())}

    assert results["codex"].ok is False
    assert "install.sh" in results["codex"].remedy


def test_an_absent_codex_is_not_reported_at_all(tmp_path, monkeypatch):
    _all_present(monkeypatch)
    monkeypatch.setattr(doctor_module, "hook_check", lambda: [])
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "nowhere"))

    assert "codex" not in {check.name for check in checks(_paths(tmp_path), Config())}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_doctor.py -v`
Expected: FAIL with `KeyError: 'codex'`

- [ ] **Step 3: Write minimal implementation**

In `src/cvoice/doctor.py`, add the check inside `checks()`, just before the Focus check:

```python
    from .codex import config_path as codex_config_path
    from .codex import is_installed as codex_installed
    from .codex import read_notify

    codex_config = codex_config_path()
    if codex_installed(codex_config):
        notify = read_notify(codex_config)
        installed = bool(notify) and "cv-hook" in notify[0]
        results.append(
            Check(
                name="codex",
                ok=installed,
                detail="reporting through cvoice"
                if installed
                else f"notify points elsewhere: {' '.join(notify) or 'unset'}",
                remedy="run ./install.sh again to take the slot back",
            )
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_doctor.py -v`
Expected: PASS, 12 passed

- [ ] **Step 5: Commit**

```bash
git add src/cvoice/doctor.py tests/test_doctor.py
git commit -m "Tell whether Codex still reports through us"
```

---

## Task 12: Installer, uninstaller and the README

**Files:**
- Modify: `install.sh`, `uninstall.sh`, `README.md`

- [ ] **Step 1: Write the failing check**

There is no unit test for a bootstrap script; it is verified by running it. Fix the
acceptance criteria first:

```bash
# From a clone, after Step 3. --no-hooks keeps this run away from the real ~/.claude*
# AND the real ~/.codex, so the Codex step is exercised directly rather than through
# install.sh - which is the only honest way to test it without a sandboxed HOME.
mkdir -p /tmp/cv-codex && printf 'notify = ["/opt/thing", "turn-ended"]\n' > /tmp/cv-codex/config.toml
CVOICE_HOME=/tmp/cv-test ./install.sh --no-hooks --no-menubar --language en

CODEX_HOME=/tmp/cv-codex CVOICE_HOME=/tmp/cv-test /tmp/cv-test/bin/cv-hook install-codex
grep notify /tmp/cv-codex/config.toml          # must point at /tmp/cv-test/bin/cv-hook
CODEX_HOME=/tmp/cv-codex CVOICE_HOME=/tmp/cv-test /tmp/cv-test/bin/cv-hook remove-codex
grep notify /tmp/cv-codex/config.toml          # must be /opt/thing again
```

Note what `--no-hooks` now covers: both agents. It means "do not wire me into anything",
and every sandboxed run depends on that. Wiring it to Claude only would let a run with a
scratch `CVOICE_HOME` still reach out and take the real Codex slot.

- [ ] **Step 2: Run it to verify it fails**

Run the block above.
Expected: FAIL — after install, `notify` still reads `/opt/thing`, because `install.sh` does
not know about Codex yet.

- [ ] **Step 3: Write minimal implementation**

In `install.sh`, after the block that installs the Claude hooks and before the menu-bar
block, add:

```bash
if [ "$INSTALL_HOOKS" = 1 ]; then
  # Codex offers one notification slot and it is usually taken, so we chain rather than
  # replace: whatever was there is stored and called first.
  "$HOME_DIR/bin/cv-hook" install-codex
fi
```

In `uninstall.sh`, before the plugin removal, add:

```bash
if [ "$REMOVE_HOOKS" = 1 ] && [ -x "$HOME_DIR/bin/cv-hook" ]; then
  "$HOME_DIR/bin/cv-hook" remove-codex || true
fi
```

`REMOVE_HOOKS` is the variable `uninstall.sh` already sets from `--no-hooks`; do not add a
second one.

In `README.md`, add a section after **Menu bar**:

```markdown
## Codex

Codex is supported alongside Claude Code, for end-of-turn summaries. It offers a single
notification slot, and on a normal install that slot is already used by Codex Computer Use,
so cvoice chains rather than replaces: whatever was configured is stored, called first, and
put back on uninstall.

You hear which agent is speaking only when it changes — "Codex, project-name" — the same way
project names already behave.

Codex surfaces neither questions nor permission prompts as events, so those are not
reported for it. Codex also rewrites its own config from time to time, which can take the
slot back; `cv doctor` says so when it happens, and re-running `./install.sh` restores it.
```

- [ ] **Step 4: Run it to verify it passes**

Run the acceptance block from Step 1 again.
Expected: after install, `notify` names `/tmp/cv-test/bin/cv-hook`; after uninstall it reads
`/opt/thing` again. Clean up with `rm -rf /tmp/cv-test /tmp/cv-codex`.

- [ ] **Step 5: Commit**

```bash
git add install.sh uninstall.sh README.md
git commit -m "Install the Codex hook alongside the Claude ones"
```

---

## Task 13: Confirming the payload against a real turn

This is the one thing that cannot be settled by tests: the exact argv layout of Codex's
`notify` was never observed directly. Everything above is written not to depend on it, but
it still has to be confirmed once.

**Files:**
- Create: `/tmp/cvoice-codex-payload.log` (temporary, deleted in Step 5)

- [ ] **Step 1: Record what Codex actually passes**

Point the slot at a recorder rather than at cvoice:

```bash
cat > /tmp/record-notify.sh <<'EOF'
#!/bin/sh
printf '%s\n' "$@" >> /tmp/cvoice-codex-payload.log
echo "---" >> /tmp/cvoice-codex-payload.log
EOF
chmod +x /tmp/record-notify.sh
~/.cvoice/.venv/bin/python -c "
from cvoice.codex import config_path, read_notify, write_notify
print('current:', read_notify())
write_notify(config_path(), ['/tmp/record-notify.sh'])
"
```

- [ ] **Step 2: Run one turn in Codex, then read the log**

Ask Codex anything that takes a moment, wait for it to finish, then:

```bash
cat /tmp/cvoice-codex-payload.log
```

Expected: one argument per line. Confirm that one of them is JSON and that it carries the
final message under one of `last-assistant-message`, `last_agent_message` or `message`.

- [ ] **Step 3: Adjust only if the recording disagrees**

If the message arrives under a key not in `MESSAGE_KEYS`, add it to that tuple in
`src/cvoice/hooks/codex.py` and add a test for it in `tests/test_hook_codex.py` following
the shape of `test_the_plain_message_key_is_accepted`. If the recording matches, change
nothing.

- [ ] **Step 4: Put cvoice back in the slot and verify for real**

```bash
~/.cvoice/bin/cv-hook install-codex
~/.cvoice/bin/cv-hook doctor | grep codex
```

Then run one more turn in Codex and check it arrived:

```bash
~/.cvoice/bin/cv-hook history | tail -3
```

Expected: the newest entry is labelled `Codex, <project>`.

- [ ] **Step 5: Clean up and commit anything that changed**

```bash
rm -f /tmp/record-notify.sh /tmp/cvoice-codex-payload.log
git add -A && git commit -m "Confirm the Codex notify payload against a real turn"
```

If nothing changed in Step 3, there is nothing to commit — say so rather than making an
empty commit.

---

## Notes for the implementer

- **Commits:** one per task is shown because each is a coherent unit. Batching them into a
  few logical commits at the end is equally fine; the boundaries are the same.
- **The chain comes first, always.** If a refactor moves `chain()` later in `main()`, the
  test `test_the_chain_runs_even_when_our_work_raises` is what will catch it. Do not
  weaken that test.
- **No test may read the real `~/.codex`** or invoke a real notify program. `CODEX_HOME`
  exists for exactly this.
