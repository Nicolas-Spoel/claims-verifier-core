"""BM25 retrieval over sentence passages (pure Python, deterministic)."""

from __future__ import annotations

import math
from collections import Counter
from typing import Mapping, Protocol, Sequence

from .models import Passage
from .text import DEFAULT_SYNONYMS, content_terms

BM25_K1 = 1.5
BM25_B = 0.75


class Retriever(Protocol):
    """Anything that can rank passages for a set of query terms and expose term statistics."""

    def search(self, terms: Sequence[str], k: int) -> tuple[tuple[Passage, float], ...]: ...

    def idf(self, term: str) -> float: ...

    def document_frequency(self, term: str) -> int: ...


class Bm25Index:
    """Okapi BM25 over passage content stems (synonym-normalized)."""

    def __init__(self, passages: Sequence[Passage], synonyms: Mapping[str, str] = DEFAULT_SYNONYMS) -> None:
        self._passages = tuple(passages)
        self._term_counts = tuple(Counter(content_terms(p.text, synonyms)) for p in self._passages)
        self._lengths = tuple(sum(c.values()) for c in self._term_counts)
        self._average_length = (sum(self._lengths) / len(self._lengths)) if self._lengths else 0.0
        self._postings: dict[str, list[int]] = {}
        for index, counts in enumerate(self._term_counts):
            for term in counts:
                self._postings.setdefault(term, []).append(index)

    def document_frequency(self, term: str) -> int:
        return len(self._postings.get(term, ()))

    def idf(self, term: str) -> float:
        n = len(self._passages)
        df = self.document_frequency(term)
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def search(self, terms: Sequence[str], k: int) -> tuple[tuple[Passage, float], ...]:
        scores: dict[int, float] = {}
        for term in dict.fromkeys(terms):
            idf = self.idf(term)
            for index in self._postings.get(term, ()):
                tf = self._term_counts[index][term]
                norm = BM25_K1 * (1 - BM25_B + BM25_B * self._lengths[index] / (self._average_length or 1.0))
                scores[index] = scores.get(index, 0.0) + idf * tf * (BM25_K1 + 1) / (tf + norm)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:k]
        return tuple((self._passages[i], round(score, 4)) for i, score in ranked)
