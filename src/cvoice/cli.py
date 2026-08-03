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
    parser = argparse.ArgumentParser(prog="cvoice")
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

    installer = sub.add_parser("install-hooks")
    installer.add_argument("config_dirs", nargs="+", type=Path)
    remover = sub.add_parser("remove-hooks")
    remover.add_argument("config_dirs", nargs="+", type=Path)

    migration = sub.add_parser("migrate")
    migration.add_argument("--from", dest="old_root", type=Path, default=Path.home() / ".claude-tts")

    language = sub.add_parser("language")
    language.add_argument("value")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        # argparse exits the process on an unrecognised subcommand; callers of
        # main() expect a return code instead, never a raised SystemExit.
        return error.code if isinstance(error.code, int) else 2
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

    if args.command == "migrate":
        from .migrate import migrate

        count = migrate(args.old_root, paths)
        print(f"imported {count} history entries; {args.old_root} was left untouched")
        return 0

    if args.command == "language":
        from .i18n import available_languages

        if args.value not in available_languages():
            print(f"unknown language {args.value!r}; available: {', '.join(available_languages())}", file=sys.stderr)
            return 1
        config.language = args.value
        config_module.save(paths, config)
        print(args.value)
        return 0

    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
