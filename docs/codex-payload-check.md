# Confirming Codex's notify payload

Plan task 13. This is the one thing tests cannot settle: the exact arguments Codex passes
to its `notify` program were never observed directly, so the parser scans every argument
for JSON rather than reading a fixed position. One real turn confirms the shape.

**Currently armed.** `notify` points at `/tmp/record-notify.sh`, which writes down what it
receives and then hands over to Codex Computer Use, so nothing is lost while this is in
place. The original config is backed up at `/tmp/codex-config-backup.toml`.

## 1. Run one turn in Codex

Anything that takes a moment and finishes. Then:

```bash
cat /tmp/cvoice-codex-payload.log
```

Expect one `argv[N]:` line per argument. One of them should be JSON carrying the final
message.

## 2. Hand the log back

Paste it, or just say it is there — the log is read and acted on from the cvoice session.

What is being checked:

- **Is there JSON at all**, and in which argument. Position does not matter to the parser;
  this is only to confirm it exists.
- **Which key holds the message.** The parser accepts `last-assistant-message`,
  `last_agent_message` and `message`. Anything else needs adding to `MESSAGE_KEYS` in
  `src/cvoice/hooks/codex.py`, with a test.
- **Is there a turn id**, under `turn-id` or `turn_id`. Without one, a turn reported twice
  would be spoken twice.
- **Is there a working directory** (`cwd`, `workdir`, `working-directory`). Without it the
  project name falls back to the process's own directory, which for a desktop app is not
  the project.

## 3. Put cvoice in the slot

```bash
~/.cvoice/bin/cv-hook install-codex
~/.cvoice/bin/cv-hook doctor | grep codex
```

Then run one more turn in Codex and check it arrived:

```bash
~/.cvoice/bin/cv-hook history | tail -3
```

The newest entry should read `Codex, <project>`.

## If you want to stop half way

```bash
cp /tmp/codex-config-backup.toml ~/.codex/config.toml
```

That restores Computer Use exactly as it was, with cvoice out of the picture.
