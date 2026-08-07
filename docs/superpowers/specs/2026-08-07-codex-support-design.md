# Codex support — design

Date: 2026-08-07
Status: approved, ready for planning

## 1. Context

cvoice reports what Claude Code is doing. The same person now also runs Codex, switching
between the two during a day, and wants the same reporting from both: a spoken summary when
a turn ends, the same history, the same queue, the same menu bar.

Everything downstream of the hook is already agent-agnostic — the queue, the machine-wide
lock, history, the speech engines, transliteration, snooze, the microphone mute and the
menu bar know nothing about Claude. Only the entry point is new.

## 2. What Codex offers, and what it does not

Established by reading the installed app's data, not from documentation:

- **`notify` in `~/.codex/config.toml`** — a program plus arguments, invoked on events. On
  this machine it currently reads
  `["…/SkyComputerUseClient", "turn-ended"]`.
- **Rollout transcripts** at `~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl`.
  The `task_complete` event carries both `turn_id` and `last_agent_message`, so the final
  text is available without parsing anything. `custom_tool_call` records show whether a turn
  actually did work.
- **No equivalent of `AskUserQuestion`, `PreToolUse` or `UserPromptSubmit`.** A question in
  Codex is ordinary prose, not a structured tool call.

Two constraints follow, and they shape everything below:

1. **The `notify` slot is single and already occupied.** Overwriting it breaks Codex
   Computer Use.
2. **The app rewrites `config.toml` itself** — the file was modified by Codex today and its
   `[marketplaces.*]` sections carry `last_updated` stamps. Anything written there may be
   replaced later.

## 3. Scope

**In:** end-of-turn summaries from Codex, in the existing history, queue and menu bar.

**Out:** questions and permission prompts. Codex does not surface them as events, and
guessing from prose ("does the text contain a question mark") would be unreliable in exactly
the situation where a false positive is most annoying. This is a deliberate omission, not an
oversight.

## 4. Approach

**Chain the `notify` slot.** Our shim becomes the `notify` target and invokes the stored
original command, with its original arguments, before doing anything else.

Rejected alternatives:

- **A launchd agent watching the sessions directory.** It never touches Codex's config, so
  it cannot break Computer Use. But it introduces a resident process, and its failure mode is
  the bad one: the agent stays alive while silently missing events, and the only symptom is
  silence. Every defect found in this project so far has been at the boundary with the
  operating system; adding a daemon adds a new class of them.
- **A hybrid** that chains when the slot is free and watches otherwise: the complexity of
  both mechanisms for no gain.

The decisive argument for chaining is the shape of its failure. If Codex rewrites `notify`,
it restores its own program — Computer Use keeps working, cvoice goes quiet, and `doctor`
reports it. Nothing is broken for the user; something merely stops.

## 5. Components

| File | Responsibility |
| --- | --- |
| `src/cvoice/hooks/codex.py` | Parse the notify payload, run the chained command, emit |
| `src/cvoice/agents.py` | The agent a message came from, and how it is labelled |
| `src/cvoice/install.py` (extended) | Read the current `notify`, store it, install the shim, restore on removal |
| `src/cvoice/doctor.py` (extended) | Is `notify` still pointing at us |
| `src/cvoice/cli.py` (extended) | `hook codex`, plus `install-codex` / `remove-codex` |

The original command is stored in **cvoice's own config**, never inside Codex's, so that
recovering it never depends on the file the app rewrites.

## 6. Data flow

```
Codex finishes a turn
  -> notify -> ~/.cvoice/bin/cv-hook hook codex <args…>
       1. spawn the stored original command with its original arguments, detached,
          failures ignored - this happens first, before any work of ours
       2. guards: CVOICE_CHILD set, mode off, turn_id already seen
       3. find the argument that parses as JSON; take last-assistant-message and turn id
       4. look up the rollout file for that turn: did it call any tool?
       5. from here the existing path: summarise -> emit -> history, banner, queue, speech
```

Step 1 is unconditional and comes first. If everything of ours fails afterwards, Computer
Use has already been called.

### The payload format is not assumed

The exact argv layout of `notify` has not been observed directly — Codex was not running
during design. The parser therefore scans **every** argument for one that parses as JSON,
rather than reading a fixed position, and pulls the message from any of
`last-assistant-message`, `last_agent_message` or `message`. A first real turn will confirm
the shape; this is the one place expected to need adjustment.

## 7. Telling the two agents apart

The user hears which agent is speaking **only when it changes**, exactly as project names
already behave.

This needs no new logic: the agent is folded into the existing label. For Claude the label
stays `kaaba`; for Codex it becomes `Codex, kaaba`. The speaker already announces a label
only when it differs from the previous utterance, so switching agents is announced, and a
run of turns from the same agent in the same project is not.

History entries additionally carry an `agent` field, so the menu bar can mark them without
affecting speech. Entries written before this change have no such field; it therefore
defaults to `claude`, which is what those entries in fact were.

## 8. Failure policy

Consistent with the rest of the tool: degrade, record, never raise.

| Situation | Behaviour |
| --- | --- |
| Stored original command missing or fails | Ignored; recorded in `health` |
| No JSON among the arguments | Exit quietly; nothing to say |
| Malformed JSON, or no message in it | Exit quietly |
| Rollout file unreadable | Treat the turn as having done work, rather than staying silent |
| Codex rewrote `notify` | Computer Use intact, cvoice silent, `doctor` says so and points at `install.sh` |

The rollout fallback deserves a note: when we cannot tell whether a turn did work, we report
it. A missed summary is worse than an occasional needless one, and unlike Claude Code this
gate has no second source of truth.

## 9. Installation

The editing itself lives in Python, as `cvoice install-codex` and `cvoice remove-codex`;
`install.sh` and `uninstall.sh` only call them. That keeps TOML rewriting testable and out
of shell.

`install.sh` gains a Codex step, skipped entirely when `~/.codex/config.toml` is absent:

1. Read the current `notify` value.
2. If it already points at our shim, do nothing — installing twice must not chain to itself.
3. Otherwise store the current value in `~/.cvoice/config.toml` as `codex_original_notify`
   and set `notify` to `["<home>/bin/cv-hook", "hook", "codex"]`.
4. Back up `config.toml` first, and only when something is actually being changed.

`uninstall.sh` restores the stored original, or removes the key when there was none.

## 10. Testing

No test runs Codex, reads the real `~/.codex`, or invokes a real notify program.

- **Payload parsing:** JSON in first, middle and last position; absent; malformed; present
  but with no message field; each of the three accepted message keys.
- **Chaining:** the original command is invoked with its original arguments; it is invoked
  even when the rest of the hook raises; a missing original is survivable.
- **Deduplication:** the same `turn_id` twice produces one entry.
- **Tool detection** against a fixture rollout file, including the unreadable-file fallback.
- **Labelling:** a Codex message is labelled distinctly; consecutive messages from the same
  agent and project are not re-announced; switching agents is.
- **Installation:** stores the original; is idempotent; never chains to itself; restores on
  removal; leaves `config.toml` untouched when there is nothing to change; absent Codex is
  not an error.

## 11. Out of scope, deliberately

Codex questions and permission prompts (see §3). Any use of the sessions directory beyond
reading one rollout file for tool detection. Windows or Linux, as before.
