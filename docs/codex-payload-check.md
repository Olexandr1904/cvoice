# Codex's notify payload — confirmed

Plan task 13, settled against a real turn on 2026-08-11. Nothing in the parser needed
changing; this note records what was observed, and the one surprise that did need a fix.

## The payload

A single argument, holding JSON:

```json
{
  "type": "agent-turn-complete",
  "thread-id": "019fdba2-…",
  "turn-id": "019ff086-…",
  "cwd": "/Users/me/projects/example",
  "client": "Codex Desktop",
  "input-messages": ["…"],
  "last-assistant-message": "…"
}
```

Every key the hook looks for was present and first in its list of accepted spellings:
`last-assistant-message`, `turn-id`, `cwd`. The parser scans all arguments rather than a
fixed position, which turned out to be unnecessary here but costs nothing and still covers
a future change.

## The surprise: Codex chains too

Codex Desktop does not simply overwrite a foreign `notify`. It takes the slot back for its
own client and preserves what it displaced:

```
notify = ["…/SkyComputerUseClient", "turn-ended",
          "--previous-notify", "[\"/previous/command\"]"]
```

The displaced command is then still called — confirmed by timestamps: the slot was
reclaimed at 14:00:41 and the displaced program was called seven times afterwards.

Two consequences, both now handled:

- **A reclaimed slot must never be stored as "the original".** Our shim then sits inside
  `--previous-notify`, so a second install would store a command that calls us, and our
  chain would call it: an endless loop. `_is_ours` therefore looks for the shim anywhere in
  the command, not just at position 0.
- **A reclaimed slot is not a fault.** We are still reached through Codex's own chain, so
  `doctor` reports it as installed rather than crying wolf.

## Re-checking later

If Codex changes its payload, the symptom is silence from Codex turns while Claude keeps
working. To look again, point the slot at a recorder that hands over to the real target:

```sh
#!/bin/sh
printf '%s\n' "$@" >> /tmp/notify.log
exec "$(the real notify program)" "$@"
```
