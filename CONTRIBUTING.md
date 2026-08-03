# Contributing

## Setup

    pip install -e ".[dev]"

## Running tests

    .venv/bin/python -m pytest

No test should reach the network. Anything that would call `edge-tts` or the `claude`
CLI replaces the subprocess call instead — if a test starts needing network access, the
seam for faking it is in the wrong place; fix that rather than allowing the call through.

## Adding a language

Language packs live in `src/claude_voice/i18n/*.toml`. Copy an existing pack, translate
every phrase, and fill in `summary_prompt` and the `detect`/`translit` tables. A new pack
must define every key in `REQUIRED_PHRASES` (`src/claude_voice/i18n/__init__.py`) —
`tests/test_i18n.py` checks every pack for completeness, so a half-translated language
fails CI rather than shipping silently broken.

## Style

- English only: code, comments, docstrings, commit messages.
- Every component degrades through the fallback chain instead of raising at the user;
  record failures via `claude_voice.health` rather than printing a traceback.
