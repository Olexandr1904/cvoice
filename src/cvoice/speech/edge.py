"""Azure neural voices through the endpoint Edge's Read Aloud uses.

No API key and no cost, but it needs the network - hence the fallback chain. Audio is
cached by a hash of text, voice and rate, so replaying a message is free and instant.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .base import SpeechError, SpeechInterrupted


def edge_binary() -> Optional[str]:
    """Locate edge-tts without relying on PATH.

    It is installed inside our own virtual environment, and that directory is not on
    PATH when hooks or the menu bar run us - so a plain shutil.which() silently reports
    the neural engine as unavailable and everything falls back to the built-in voice.
    """
    local = Path(sys.executable).with_name("edge-tts")
    if local.exists():
        return str(local)
    return shutil.which("edge-tts")


class EdgeEngine:
    name = "edge-tts"

    def __init__(self, voice: str, rate: str, cache_dir: Path) -> None:
        self.voice = voice
        self.rate = rate
        self.cache_dir = Path(cache_dir)

    def available(self) -> bool:
        return edge_binary() is not None

    def _cache_path(self, text: str) -> Path:
        digest = hashlib.md5(f"{text}|{self.voice}|{self.rate}".encode()).hexdigest()
        return self.cache_dir / f"{digest}.mp3"

    def _synthesise(self, text: str, target: Path) -> None:
        partial = target.with_suffix(".part")
        result = subprocess.run(
            [
                edge_binary() or "edge-tts",
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
        if result.returncode < 0:
            raise SpeechInterrupted("playback stopped")
        if result.returncode != 0:
            raise SpeechError(result.stderr.strip() or f"afplay exited {result.returncode}")
