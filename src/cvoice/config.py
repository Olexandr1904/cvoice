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
    model: str = "sonnet"
    mute_while_mic_in_use: bool = True
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
        model=data.get("model", defaults.model),
        mute_while_mic_in_use=bool(data.get("mute_while_mic_in_use", defaults.mute_while_mic_in_use)),
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
        "model": config.model,
        "mute_while_mic_in_use": config.mute_while_mic_in_use,
        "edge": {"voice": config.edge_voice, "rate": config.edge_rate},
        "say": {"voice": config.say_voice, "rate": config.say_rate},
    }
    paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    paths.config_file.write_bytes(tomli_w.dumps(payload).encode())


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
