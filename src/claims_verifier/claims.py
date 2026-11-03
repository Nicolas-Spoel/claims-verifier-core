"""Splitting an AI-generated answer into atomic, checkable claims.

Every claim keeps its character span in the original answer; segments that are
not checked (questions, pleasantries, headings, content-free text) are returned
as ``SkippedSegment`` with a reason instead of being silently dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator

from .lexicon import NON_CHECKABLE_PATTERNS
from .models import Claim, SkippedSegment
from .numbers import extract_numbers
from .text import content_stems, fold, split_sentences, strip_markdown

MIN_CONTENT_TERMS = 2
FACTUAL_MIN_TERMS = 3
"""Content left after removing a pleasantry that is verified as a claim."""
FACTUAL_MIN_TERMS_UNVERIFIED = 4
"""Questions and headings are not verified; with this much content they are reported as UNCHECKED."""
MAX_CLAIM_CHARS = 2_000
"""Longer claims are not analysed (bounded cost) and are reported as UNCHECKED."""
MAX_ANSWER_CHARS = 200_000

# Contrastive / clause-joining markers that separate independent assertions.
_CLAUSE_SPLIT_RE = re.compile(
    r"\s*;\s*|,\s+(?:pero|aunque|mientras que|sin embargo|but|although|whereas|while)\s+|"
    r"\s+(?:mientras que|whereas)\s+",
    re.IGNORECASE,
)
_LEADING_CONNECTOR_RE = re.compile(
    r"^(?:en resumen|ademas|por otro lado|asimismo|por ultimo|finalmente|en conclusion|"
    r"in summary|additionally|moreover|finally|overall)\s*,\s*",
)


class AnswerError(ValueError):
    """Raised when the answer to verify is empty or too large."""


@dataclass(frozen=True)
class Extraction:
    claims: tuple[Claim, ...]
    skipped: tuple[SkippedSegment, ...]


def _has_factual_content(text: str, min_terms: int) -> bool:
    return bool(extract_numbers(text)) or len(content_stems(text)) >= min_terms


def _without_pleasantries(folded: str) -> str:
    for pattern in NON_CHECKABLE_PATTERNS:
        folded = folded.replace(pattern, " ")
    return folded


def _skip_reason(text: str) -> tuple[str | None, bool]:
    """(reason to skip, segment still carries factual content). A pleasantry never hides a fact:
    once the pleasantry is removed, any remaining factual content is verified as a claim."""
    folded = fold(text).strip()
    if folded.endswith("?") or folded.startswith("¿"):
        return "question", _has_factual_content(text, FACTUAL_MIN_TERMS_UNVERIFIED)
    if any(pattern in folded for pattern in NON_CHECKABLE_PATTERNS):
        if _has_factual_content(_without_pleasantries(folded), FACTUAL_MIN_TERMS):
            return None, True
        return "conversational", False
    if len(content_stems(text)) < MIN_CONTENT_TERMS and not extract_numbers(text):
        return "no_factual_content", False
    return None, True


def _clauses(text: str, start: int, end: int) -> Iterator[tuple[int, int]]:
    segment = text[start:end]
    cursor = 0
    for match in _CLAUSE_SPLIT_RE.finditer(segment):
        yield start + cursor, start + match.start()
        cursor = match.end()
    yield start + cursor, end


def _lines(answer: str) -> Iterator[tuple[int, int, str]]:
    position = 0
    for line in answer.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        yield position, position + len(content), content
        position += len(line)


def _strip_connector(text: str) -> str:
    match = _LEADING_CONNECTOR_RE.match(fold(text))
    return text[match.end():] if match else text


def extract_claims(answer: str) -> Extraction:
    """Segment ``answer`` (plain text or Markdown) into claims and skipped segments."""
    if not answer.strip():
        raise AnswerError("answer is empty")
    if len(answer) > MAX_ANSWER_CHARS:
        raise AnswerError(f"answer exceeds {MAX_ANSWER_CHARS} characters")
    claims: list[Claim] = []
    skipped: list[SkippedSegment] = []
    for line_start, line_end, line in _lines(answer):
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            heading = strip_markdown(line).strip()
            factual = _has_factual_content(heading, FACTUAL_MIN_TERMS_UNVERIFIED)
            skipped.append(SkippedSegment(heading, line_start, line_end, "heading", factual))
            continue
        for sent_start, sent_end in split_sentences(line, line_start):
            for start, end in _clauses(answer, sent_start, sent_end):
                text = _strip_connector(strip_markdown(answer[start:end]).strip()).strip()
                if not text:
                    continue
                reason, factual = _skip_reason(text)
                if reason:
                    skipped.append(SkippedSegment(text, start, end, reason, factual))
                elif len(text) > MAX_CLAIM_CHARS:
                    skipped.append(SkippedSegment(text[:MAX_CLAIM_CHARS], start, end, "too_long", True))
                else:
                    claims.append(Claim(f"C{len(claims) + 1}", text, start, end))
    return Extraction(tuple(claims), tuple(skipped))


def claims_from_texts(texts: Iterable[str]) -> Extraction:
    """Wrap pre-extracted claim strings (e.g. from an upstream LLM extractor) without splitting.

    They have no position in any answer text, so their spans are ``None``.
    """
    stripped = [text.strip() for text in texts if text.strip()]
    if not stripped:
        raise AnswerError("no claims provided")
    accepted = [t for t in stripped if len(t) <= MAX_CLAIM_CHARS]
    claims = tuple(Claim(f"C{i}", text, None, None) for i, text in enumerate(accepted, start=1))
    skipped = tuple(SkippedSegment(t[:MAX_CLAIM_CHARS], 0, len(t), "too_long", True)
                    for t in stripped if len(t) > MAX_CLAIM_CHARS)
    return Extraction(claims, skipped)
