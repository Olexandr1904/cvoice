"""Language packs: spoken phrases, the summarizer prompt, and language detection.

Everything the user can hear lives in a pack, so adding a language never means touching
logic. A test asserts every pack carries every required key, which stops a language from
shipping half-translated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

from ..speech.translit import Table

PACKS_DIR = Path(__file__).parent

REQUIRED_PHRASES = (
    "question.single",
    "question.with_text",
    "question.many",
    "plan.ready",
    "permission.tool",
    "permission.generic",
    "waiting",
    "summary.fallback",
    "voice.enabled",
    "test.phrase",
)


@dataclass
class Pack:
    language: str
    name: str
    phrases: Dict[str, str]
    summary_prompt: str
    requires: Optional[str] = None
    forbids: Optional[str] = None
    translit_table: Table = field(default_factory=Table)

    def phrase(self, key: str, **kwargs: object) -> str:
        template = self.phrases.get(key, key)
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            # A missing argument must never take the message down.
            return re.sub(r"\{[^}]*\}", "", template).strip()

    def matches_language(self, text: str) -> bool:
        """True when the text can be spoken as-is by this pack's voice."""
        if self.forbids and re.search(self.forbids, text):
            return False
        if not self.requires:
            return False  # a pack that declares nothing always summarizes
        return bool(re.search(self.requires, text))


def available_languages() -> List[str]:
    return sorted(path.stem for path in PACKS_DIR.glob("*.toml"))


def load(language: str) -> Pack:
    path = PACKS_DIR / f"{language}.toml"
    if not path.exists():
        raise LookupError(f"no language pack for {language!r}")
    data = tomllib.loads(path.read_text())
    detect = data.get("detect", {})
    translit = data.get("translit", {})
    return Pack(
        language=data["language"],
        name=data.get("name", data["language"]),
        phrases=data.get("phrases", {}),
        summary_prompt=data["summary_prompt"],
        requires=detect.get("requires"),
        forbids=detect.get("forbids"),
        translit_table=Table(
            terms=translit.get("terms", {}),
            digraphs=[tuple(pair) for pair in translit.get("digraphs", [])],
            letters=translit.get("letters", {}),
        ),
    )
