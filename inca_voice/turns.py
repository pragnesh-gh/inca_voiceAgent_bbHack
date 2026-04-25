from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


FILLER_WORDS = {
    "ah",
    "äh",
    "eh",
    "hm",
    "hmm",
    "mhm",
    "mm",
    "mmh",
    "mmhm",
    "mm-hmm",
    "uh",
    "uhh",
    "um",
    "ähm",
}

SHORT_MEANINGFUL = {"hello", "hi", "hallo", "guten tag", "moin"}
WORD_RE = re.compile(r"[\wÄÖÜäöüß']+", re.UNICODE)


@dataclass(frozen=True)
class TurnSettings:
    min_words: int = 2
    min_chars: int = 8
    settle_ms: int = 700
    max_wait_ms: int = 1800


@dataclass(frozen=True)
class CommittedTurn:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Fragment:
    text: str
    now_ms: float
    metadata: dict[str, Any]


class TurnManager:
    def __init__(self, settings: TurnSettings) -> None:
        self.settings = settings
        self._fragments: list[_Fragment] = []

    @property
    def pending_text(self) -> str:
        return merge_fragment_texts([fragment.text for fragment in self._fragments])

    def add_fragment(self, text: str, *, now_ms: float, metadata: dict[str, Any] | None = None) -> list[CommittedTurn]:
        clean = clean_fragment(text)
        if not clean:
            return []
        if is_filler(clean) and not self._fragments:
            return []
        if self._fragments and _same_or_replacement(self._fragments[-1].text, clean):
            self._fragments[-1] = _Fragment(clean, now_ms, metadata or {})
            return self.drain_ready(now_ms=now_ms)
        if self._fragments and _same_or_replacement(clean, self._fragments[-1].text):
            return self.drain_ready(now_ms=now_ms)

        self._fragments.append(_Fragment(clean, now_ms, metadata or {}))
        return self.drain_ready(now_ms=now_ms)

    def drain_ready(self, *, now_ms: float) -> list[CommittedTurn]:
        if not self._fragments:
            return []

        since_last_ms = now_ms - self._fragments[-1].now_ms
        total_wait_ms = now_ms - self._fragments[0].now_ms
        text = self.pending_text

        if is_filler(text):
            self.clear()
            return []

        if is_meaningful(text, self.settings):
            if since_last_ms >= self.settings.settle_ms:
                return [self._commit(now_ms, "settled")]
            return []

        if total_wait_ms >= self.settings.max_wait_ms:
            self.clear()
        return []

    def clear(self) -> None:
        self._fragments.clear()

    def _commit(self, now_ms: float, reason: str) -> CommittedTurn:
        fragments = list(self._fragments)
        text = self.pending_text
        self.clear()
        metadata = {
            "reason": "turn_committed",
            "commit_reason": reason,
            "fragment_count": len(fragments),
            "first_fragment_ms": fragments[0].now_ms,
            "last_fragment_ms": fragments[-1].now_ms,
            "committed_ms": now_ms,
            "fragments": [
                {"text": fragment.text, "metadata": fragment.metadata}
                for fragment in fragments
            ],
        }
        return CommittedTurn(text=text, metadata=metadata)


def clean_fragment(text: str) -> str:
    return " ".join((text or "").strip().split())


def merge_fragment_texts(texts: list[str]) -> str:
    merged = ""
    for text in texts:
        if not merged:
            merged = text
            continue
        separator = " "
        merged = f"{merged}{separator}{text}"
    return merged.strip()


def is_filler(text: str) -> bool:
    normalized = _normalize(text)
    return normalized in FILLER_WORDS


def is_meaningful(text: str, settings: TurnSettings) -> bool:
    normalized = _normalize(text)
    if normalized in SHORT_MEANINGFUL:
        return True
    words = WORD_RE.findall(text)
    return len(words) >= settings.min_words or len(text.strip()) >= settings.min_chars


def _normalize(text: str) -> str:
    lowered = text.casefold().strip()
    return re.sub(r"[^\wÄÖÜäöüß'-]+", " ", lowered).strip()


def _same_or_replacement(previous: str, new: str) -> bool:
    old = _normalize(previous)
    current = _normalize(new)
    if not old or not current:
        return False
    return current == old or current.startswith(old + " ")
