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
    on_unavailable: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """Try each engine in order. Returns the name of the one that spoke, or None."""
    for engine in engines:
        try:
            if not engine.available():
                # Silent degradation is the failure mode this whole design exists to avoid.
                if on_unavailable is not None:
                    on_unavailable(engine.name)
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
