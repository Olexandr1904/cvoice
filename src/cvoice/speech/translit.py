"""Last line of defence before the built-in macOS voice.

A voice tuned for one language reads latin letter by letter, which is unintelligible.
Known technical terms come from the language pack's dictionary; anything else is
converted phonetically. Neural engines do not need this - they pronounce English well
enough on their own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*")
_LATIN_RUN = re.compile(r"[A-Za-z]{3,}")
_CAMEL_PARTS = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z']*|[a-z']+")


@dataclass
class Table:
    terms: Dict[str, str] = field(default_factory=dict)
    digraphs: List[Tuple[str, str]] = field(default_factory=list)
    letters: Dict[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.letters


def has_latin_words(text: str) -> bool:
    return bool(_LATIN_RUN.search(text))


def _phonetic(word: str, table: Table) -> str:
    lowered = word.lower()
    if word.isupper() and len(word) <= 4:
        return "-".join(table.letters.get(char, char) for char in lowered)
    for source, target in table.digraphs:
        lowered = lowered.replace(source, target)
    return "".join(table.letters.get(char, char) for char in lowered)


def _one_word(word: str, table: Table) -> str:
    known = table.terms.get(word.lower())
    if known:
        return known
    parts = _CAMEL_PARTS.findall(word)
    if len(parts) > 1:
        return " ".join(table.terms.get(part.lower(), _phonetic(part, table)) for part in parts)
    return _phonetic(word, table)


def transliterate(text: str, table: Table) -> str:
    if table.empty:
        return text
    # Multi-word terms first, longest first, so "pull request" wins over "pull".
    for term in sorted((term for term in table.terms if " " in term), key=len, reverse=True):
        text = re.sub(re.escape(term), table.terms[term], text, flags=re.IGNORECASE)
    return _LATIN_WORD.sub(lambda match: _one_word(match.group(0), table), text)
