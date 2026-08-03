"""The synthesiser built into macOS. Always available offline, sounds mechanical."""

from __future__ import annotations

import shutil
import subprocess
from typing import Optional

from .base import SpeechError
from .translit import Table, has_latin_words, transliterate


class SayEngine:
    name = "say"

    def __init__(self, voice: str, rate: int, table: Optional[Table] = None) -> None:
        self.voice = voice
        self.rate = rate
        self.table = table

    def available(self) -> bool:
        return shutil.which("say") is not None

    def speak(self, text: str) -> None:
        # This engine cannot pronounce latin at all, so it gets the transliterated text.
        # Banners and history keep the readable original.
        if self.table is not None and has_latin_words(text):
            text = transliterate(text, self.table)
        result = subprocess.run(
            ["say", "-v", self.voice, "-r", str(self.rate), "--", text],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SpeechError(result.stderr.strip() or f"say exited {result.returncode}")
