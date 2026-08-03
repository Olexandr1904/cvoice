# claude-voice — design

Date: 2026-08-03
Status: approved, ready for planning

## 1. Context

A working prototype exists at `~/.claude-tts`: ~985 lines of bash plus one Python
transliterator, wired into several Claude Code config directories through hooks. It speaks a
short summary when a turn ends, announces questions and permission prompts, keeps a history
that can be replayed, and renders a SwiftBar menu-bar item. It is used daily.

Its weaknesses are not features but foundations: it is not under version control, has no
tests, and fails silently — if `jq`, `edge-tts` or the network breaks, the result is silence
with no explanation. It also contains Ukrainian comments, personal defaults, and assumptions
about one machine, so it cannot be handed to anyone else as-is.

## 2. Goals

1. **Reliability first.** No silent failure. Every degradation is recorded and surfaced.
2. **Publishable.** A public GitHub repository: English code, comments, README and commit
   messages; MIT licence; neutral defaults; speech language chosen by configuration.
3. **Safe migration.** The live installation keeps working untouched during development.
   Switching over is a single command with a backup and a documented rollback.

## 3. Non-goals (explicitly out of scope for v1)

- Linux or Windows support. macOS only, stated plainly in the README.
- Auto-mute driven by microphone or calendar state.
- Global hotkeys.
- Voice input / dictation.

These are recorded so the first release stays finishable, not because they are bad ideas.

## 4. Approach

Python core with thin bash shims. Hooks stay tiny shell wrappers because `settings.json`
needs a stable path; all logic lives in an importable, testable Python package.

Rejected alternatives:

- **Disciplined bash + bats.** Lower install friction (`curl | bash`), but the primary goal
  is reliability, and shell resists the unit testing that reliability depends on. Also keeps
  BSD-specific traps (`md5 -q`, `tail -r`, `sed -i ''`).
- **Minimal fix** (git + doctor + README only). Half a day of work, but the repository would
  be public in name only: Ukrainian comments, personal defaults, no tests.

The install-friction argument against Python is answered by `install.sh`, which creates the
virtual environment itself. The user still runs one command.

## 5. Repository layout

```
claude-voice/
  install.sh                  bootstrap: venv, package, hooks, menu-bar plugin
  uninstall.sh                remove hooks by marker; leave user data
  pyproject.toml              package metadata, console entry point
  LICENSE                     MIT
  README.md                   what it is, install, configuration, screenshots
  src/claude_voice/
    cli.py                    single entry point: claude-voice <subcommand>
    config.py                 layered configuration and scope cascade
    state.py                  paths, snooze, seen marker, lock location
    queue.py                  speech queue and machine-wide lock
    summarize.py              wrapper around `claude -p` (haiku)
    history.py                JSONL history: append, filter, dedupe, trim
    health.py                 failure journal and doctor checks
    speech/
      base.py                 Engine protocol and fallback chain
      edge.py                 edge-tts engine with audio cache
      macos_say.py            built-in `say` engine
      translit.py             latin -> target-script transliteration
    notify/macos.py           terminal-notifier with osascript fallback
    hooks/
      stop.py                 end of turn -> TLDR
      question.py             AskUserQuestion / ExitPlanMode
      notification.py         permission requests and idle nudges
      prompt_submit.py        drop this session's pending speech
    i18n/
      en.toml  uk.toml        static phrases and the summarizer prompt
    menubar/plugin.sh         SwiftBar plugin; calls `claude-voice menubar`
  tests/                      pytest
  docs/
```

Runtime data stays outside the repository, in `~/.claude-voice/`: `config.toml`, `queue/`,
`lock/`, `cache/`, `history.jsonl`, `health.json`, `scopes/`. The repository never contains
user data.

## 6. Module contracts

| Module | Public contract | Depends on |
| --- | --- | --- |
| `config` | `resolve_mode(scopes) -> Mode`, `load() -> Config` | nothing (paths injected) |
| `state` | `paths()`, `snoozed_until()`, `seen_marker()`, lock location | nothing |
| `queue` | `enqueue(item)`, `drain(speaker)` | `state`, `health` |
| `speech.base` | `Engine.speak(text)`, `Engine.available()`, `speak_with_fallback(text)` | `health` |
| `summarize` | `run(text, language) -> str \| None` | `subprocess` |
| `history` | `add(entry)`, `recent(n)`, `get(id)` | nothing (path injected) |
| `health` | `record(component, error)`, `checks() -> list[Check]`, `clear()` | nothing |
| `notify.macos` | `send(title, body, group)` | `health` |

`config` and `speech.translit` are pure and testable without touching the filesystem. The
rest take their paths as arguments so tests can point them at `tmp_path`.

### Why a shim

`settings.json` hook entries must reference a path that never changes:

```
~/.claude-voice/bin/cv-hook stop
```

`cv-hook` is three lines of bash: resolve the virtual environment, then `exec` the Python
entry point with the same argument. It is written once at install time and is the only file
whose path the hooks know about. Upgrading the package never rewrites `settings.json`.

## 7. Behaviour to preserve

Everything the prototype already does correctly is a requirement, not a rewrite target:

- One machine-wide speech queue shared by every Claude Code alias, so parallel agents never
  talk over each other. Lock via atomic `mkdir` with the owner pid inside; a dead owner's
  lock is reclaimed. Priority ordering puts questions ahead of summaries. After the queue
  drains, it is checked once more before the lock is released.
- Mode and snooze state are re-read **before every utterance**, not once when the worker
  starts.
- Output modes `off | notify | voice | both`, resolved by cascade: project > alias > global,
  most specific explicit value wins.
- `snooze N` with automatic expiry; an explicit replay overrides both mode and snooze.
- End-of-turn summary: a reply is read verbatim only when it is under 300 characters, contains
  no latin word of three or more letters, and passes the language check; anything else goes to
  the summarizer. The language check is supplied by the i18n pack as two optional character-class
  patterns, `requires` and `forbids` (Ukrainian, for example, requires `[іїєґ]` and forbids
  `[ыэъё]`). A pack that declares neither always summarizes, which is the safe default. The reply is embedded **inside** the prompt between
  explicit markers, never piped on stdin — piping makes the model answer the instructions
  instead of summarizing. Recursion is prevented by `CLAUDE_VOICE_CHILD=1`, on which every
  hook exits immediately, and by disabling hooks in the child invocation.
- Hooks return control immediately; the summarizer runs detached.
- History stores summaries and questions but not idle "waiting for input" nudges, and
  collapses consecutive duplicates.
- Transliteration applies only on the `say` path, immediately before synthesis. Banners and
  history always keep the readable original.
- Synthesised audio is cached by a hash of text, voice and rate.

## 8. Data flow — end of turn

```
Claude Code --(JSON on stdin)--> ~/.claude-voice/bin/cv-hook stop
  -> claude_voice.hooks.stop
       guard CLAUDE_VOICE_CHILD  -> exit 0
       mode == off               -> exit 0
       spawn detached child, return immediately
     [child]
       read transcript_path, take last main-thread assistant message
       strip markdown
       if short and already in target language -> use verbatim
       else summarize.run(...)      failure -> health.record + i18n fallback phrase
       history.add(kind="tldr")
       if mode in (notify, both) -> notify.send(...)
       if mode in (voice, both)  -> queue.enqueue(priority=1); spawn worker
```

## 9. Failure policy

Every failure is recorded through `health.record(component, error)` and then degraded, never
raised to the user as a crash:

```
edge-tts fails      -> macOS say
say fails           -> banner only
banner fails        -> menu bar only (a file read; cannot fail)
summarizer fails    -> generic phrase from the i18n pack; the message is still delivered
```

When `health.json` is non-empty, the menu-bar icon becomes ⚠️ and the menu shows the
component, the reason and the time, plus a **Run doctor** item.

`claude-voice doctor` checks, and prints pass/fail with a remedy for each:

1. Dependencies present and runnable: the virtual environment, `edge-tts`, `terminal-notifier`,
   the `claude` CLI. (`jq` is no longer a dependency — JSON is parsed in Python.)
2. Network reachability for the neural engine.
3. Hooks installed in every detected Claude config directory, and pointing at an existing shim.
4. No stale lock and no orphaned queue entries.
5. Notification permission actually granted, and whether Focus is currently suppressing banners.
6. Menu-bar plugin installed and executable.

Check 5 exists because the single most confusing failure so far was banners being delivered
but suppressed by Do Not Disturb, which looks identical to the feature being broken.

## 10. Configuration and i18n

`~/.claude-voice/config.toml`:

```toml
language     = "en"          # speech language; selects the i18n pack
mode         = "notify"      # neutral public default
engine       = "edge"        # edge | say
[edge]
voice = "en-US-AriaNeural"
rate  = "+0%"
[say]
voice = "Samantha"
rate  = 180
```

Scope overrides live in `~/.claude-voice/scopes/` — one file per project path or alias —
so project-level settings never touch the user's repositories.

i18n packs hold both the static phrases (`question.single`, `question.many`,
`plan.ready`, `permission.needed`, `waiting`, `summary.fallback`) and the summarizer prompt
template. A test asserts every key present in `en.toml` exists in every other pack, so a new
language cannot ship half-translated.

Ukrainian ships alongside English as the reference second pack, proving the design is not
English-shaped.

## 11. Testing

Run with `pytest`; no network access in any test.

- **Unit:** scope cascade resolution; queue ordering and dead-lock reclaim; history filters,
  dedupe and trimming; transliteration including CamelCase splitting; i18n key completeness.
- **Integration:** a fixture transcript file drives the stop hook end to end with `claude -p`
  and `edge-tts` replaced by stubs; assertions on the resulting history entry, queue file and
  notification call.
- **Concurrency:** N parallel `enqueue` calls with a fake speaker that records overlapping
  intervals; assert the maximum concurrency observed is exactly 1.
- **Failure paths:** each engine forced to fail; assert the fallback chain is followed and
  `health` contains the expected component.
- **Performance:** the hook entry point returns in under 200 ms. Heavy imports (`edge-tts`)
  must be lazy, and this test is what enforces it.

CI: GitHub Actions on `macos-latest`, running `pytest` on every push and pull request.

## 12. Install, migration, rollback

`install.sh`:

1. Create `~/.claude-voice/` and a virtual environment inside it.
2. `pip install` the package into that environment.
3. Write `~/.claude-voice/bin/cv-hook`.
4. Detect every `~/.claude*` config directory, back up each `settings.json`, and add hook
   entries. Ownership is recognised by the command path containing `.claude-voice/bin/cv-hook`
   rather than by an injected marker key, because `settings.json` is validated against a
   published schema and unknown keys must not be introduced. Installation is idempotent: an
   entry whose command already points at the shim is left alone.
5. Optionally symlink the SwiftBar plugin.
6. Ask for the speech language and write the initial `config.toml`.

`claude-voice migrate` imports history and settings from an existing `~/.claude-tts` and
leaves that directory untouched, so the old installation remains a working fallback.

`uninstall.sh` removes only the marked hook entries and leaves user data in place.

Development happens in this repository while `~/.claude-tts` keeps running. Switching over is
the last step, and rolling back means running the old installer's hooks again from the backup.

## 13. Public-repository hygiene

- MIT licence.
- README: what it does, a screenshot of the menu, install in one command, configuration
  table, supported platforms stated honestly, and a short section on how the queue works.
- No personal defaults: language `en`, mode `notify`, no hard-coded paths beyond `$HOME`.
- English throughout: code, comments, docs, commit messages.
- `CONTRIBUTING.md` kept to a page.

## 14. Delivery order

The pieces depend on each other, so the plan should follow this order. Each step ends with
tests passing, and nothing touches the live installation until the last one.

1. Package skeleton, `pyproject.toml`, CI running an empty test suite.
2. `config`, `state`, `history`, `health` — the pure and near-pure modules, with their unit tests.
3. `queue` and the lock, including the concurrency test. This is the riskiest logic and the
   reason the prototype needed rewriting, so it comes before anything that uses it.
4. `speech` engines and the fallback chain; `notify`; transliteration.
5. `summarize`, then the four hooks, with the fixture-transcript integration tests and the
   sub-200 ms performance test.
6. i18n packs (`en`, `uk`) and the key-completeness test.
7. `doctor`, then the menu-bar plugin that renders its output.
8. `install.sh`, `uninstall.sh`, `migrate`, README — and only then the switch-over from
   `~/.claude-tts`.
