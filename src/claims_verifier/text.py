"""Text normalization, tokenization, sentence splitting and light stemming (es/en)."""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Iterator, Mapping

from .lexicon import (
    AMBIGUOUS_MONTHS,
    APPROX_MARKERS,
    MONTHS,
    DIRECTION_DOWN_PREFIXES,
    DIRECTION_EXCEPTIONS,
    DIRECTION_UP_PREFIXES,
    LOW_INFORMATION_WORDS,
    HALF_PERIOD_ORDINALS,
    PROPORTION_RANGES,
    SHORT_LY_ADVERBS,
    NEGATIONS,
    PARTIAL_QUANTIFIERS,
    STEM_COLLISIONS,
    STOPWORDS,
    SYNONYM_GROUPS,
    UNIVERSAL_QUANTIFIERS,
)

STEM_LENGTH = 5
MIN_STEMMABLE_LENGTH = 4
ABBREVIATION_WINDOW = 16
MAX_SENTENCE_CHARS = 1000
"""Longer run-on segments are split: bounds the per-passage analysis cost."""

_WORD_RE = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+", re.UNICODE)
# Anchored at the start of a punctuation run and possessive: linear on long runs such as "!!!!…".
_SENTENCE_END_RE = re.compile(r"(?<![.!?])[.!?]++[\"'”)\]]*+\s+")
_ABBREVIATIONS = frozenset(
    "sr sra srta dr dra ing lic av jr nro num etc aprox ej p s.a s.a.c s.r.l e.g i.e vs inc ltd co u.s".split()
)
_COMPANY_SUFFIXES = frozenset("s.a s.a.c s.a.a s.r.l e.i.r.l inc ltd co corp llc".split())
_MARKDOWN_INLINE_RE = re.compile(r"(\*\*|__|\*|`|~~)")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")

_NON_CONTENT = (
    STOPWORDS | LOW_INFORMATION_WORDS | NEGATIONS | UNIVERSAL_QUANTIFIERS | PARTIAL_QUANTIFIERS
    | (frozenset(MONTHS) - AMBIGUOUS_MONTHS)
)


@lru_cache(maxsize=None)
def _fold_char(ch: str) -> str:
    folded = "".join(c for c in unicodedata.normalize("NFKD", ch.lower()) if not unicodedata.combining(c))
    if len(folded) == 1:
        return folded
    lowered = ch.lower()
    return lowered if len(lowered) == 1 else ch


def fold(text: str) -> str:
    """Lowercase and strip diacritics so 'Aumentó' and 'aumento' (Spanish) compare equal.

    Length-preserving (one output character per input character) so offsets found in
    folded text are valid in the original; characters that would expand ("ﬁ", "½", "ß")
    are kept as a single character instead.
    """
    if text.isascii():
        return text.lower()
    return "".join(_fold_char(ch) for ch in text)


def words(text: str) -> tuple[str, ...]:
    """Folded word and number tokens, in order."""
    return tuple(_WORD_RE.findall(fold(text)))


def stem(word: str) -> str:
    """Plural/-ed/-ing stripping plus prefix truncation; crude but language-agnostic for es/en."""
    if len(word) > MIN_STEMMABLE_LENGTH + 2 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > MIN_STEMMABLE_LENGTH + 1 and word.endswith("ed"):
        word = word[:-2]
    elif len(word) > MIN_STEMMABLE_LENGTH + 1 and word.endswith("es"):
        word = word[:-2]
    elif len(word) > MIN_STEMMABLE_LENGTH and word.endswith("s"):
        word = word[:-1]
    return word[:STEM_LENGTH]


def _build_synonym_map(groups: tuple[tuple[str, ...], ...]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for group in groups:
        canonical = stem(fold(group[0]))
        for member in group:
            mapping[stem(fold(member))] = canonical
    return mapping


DEFAULT_SYNONYMS: Mapping[str, str] = _build_synonym_map(SYNONYM_GROUPS)


def synonym_map(extra_groups: tuple[tuple[str, ...], ...] = ()) -> Mapping[str, str]:
    """Default synonym map extended with caller-provided groups."""
    if not extra_groups:
        return DEFAULT_SYNONYMS
    return {**DEFAULT_SYNONYMS, **_build_synonym_map(extra_groups)}


def is_number_token(token: str) -> bool:
    return token[:1].isdigit()


def stated_proportion(tokens: tuple[str, ...]) -> str | None:
    """The proportion word a text states ("the majority"); "half" after an ordinal ("first half") is a period."""
    for index, token in enumerate(tokens):
        if token in PROPORTION_RANGES and not (index and tokens[index - 1] in HALF_PERIOD_ORDINALS):
            return token
    return None


def base_form(token: str) -> str:
    """Base word for six-letter "-ly" adverbs, whose four-letter base the five-letter stem would miss
    ("mainly" -> "main")."""
    if token in SHORT_LY_ADVERBS:
        return token[:-2]
    return token


# Every directional word ("aumentó", "bajaron", "fell", ...) collapses to one of two terms.
DIRECTION_UP_TERM = stem("crecimiento")
DIRECTION_DOWN_TERM = stem("disminucion")


def direction_term(token: str) -> str | None:
    """Canonical up/down term for a folded token, or None if it is not directional."""
    if token in DIRECTION_EXCEPTIONS:
        return None
    if token.startswith(DIRECTION_UP_PREFIXES):
        return DIRECTION_UP_TERM
    if token.startswith(DIRECTION_DOWN_PREFIXES):
        return DIRECTION_DOWN_TERM
    return None


# Approximation markers before a figure ("close to 5,000") belong to the figure, which is compared on its own;
# they are not terms the evidence must repeat. Up to two articles or a currency may stand between marker and
# figure. Bound markers ("more than", "menos de") stay required terms: whether a bound holds is not decided
# lexically for every form ("no more than", ranges, a bound in the evidence).
_FIGURE_QUALIFIERS: dict[str, tuple[tuple[str, ...], ...]] = {}
for _phrase in sorted({tuple(_WORD_RE.findall(fold(m))) for m in APPROX_MARKERS} - {()}, key=len, reverse=True):
    _FIGURE_QUALIFIERS[_phrase[0]] = _FIGURE_QUALIFIERS.get(_phrase[0], ()) + (_phrase,)
_FIGURE_GAP_WORDS = frozenset("de del un una el la los las the s usd us pen eur".split())
_MAX_FIGURE_GAP = 2


def _figure_qualifier_positions(tokens: tuple[str, ...]) -> set[int]:
    positions: set[int] = set()
    for index, token in enumerate(tokens):
        for phrase in _FIGURE_QUALIFIERS.get(token, ()):
            end = index + len(phrase)
            if tokens[index:end] != phrase:
                continue
            gap = end
            while gap < len(tokens) and gap - end < _MAX_FIGURE_GAP and tokens[gap] in _FIGURE_GAP_WORDS:
                gap += 1
            if gap < len(tokens) and is_number_token(tokens[gap]):
                positions.update(range(index, end))
            break
    return positions


def _term(token: str, synonyms: Mapping[str, str]) -> str:
    if token in STEM_COLLISIONS:
        # Its stem belongs to a default synonym of another meaning; a caller-provided group still applies.
        base = STEM_COLLISIONS[token]
        mapped = synonyms.get(stem(base))
        return mapped if mapped is not None and mapped != DEFAULT_SYNONYMS.get(stem(base)) else base
    canonical = direction_term(token) or stem(base_form(token))
    return synonyms.get(canonical, canonical)


def content_terms(text: str, synonyms: Mapping[str, str] = DEFAULT_SYNONYMS) -> tuple[str, ...]:
    """Canonical stems of the content words in ``text``, in order, with repetitions."""
    tokens = words(text)
    qualifiers = _figure_qualifier_positions(tokens)
    terms = []
    for index, token in enumerate(tokens):
        if token in _NON_CONTENT or is_number_token(token) or len(token) < 2 or index in qualifiers:
            continue  # dates and figures are compared by their own signals, not as terms
        terms.append(_term(token, synonyms))
    return tuple(terms)


def content_stems(text: str, synonyms: Mapping[str, str] = DEFAULT_SYNONYMS) -> tuple[str, ...]:
    """Ordered, de-duplicated canonical stems of the content words in ``text``."""
    return tuple(dict.fromkeys(content_terms(text, synonyms)))


def strip_markdown(line: str) -> str:
    """Remove inline markdown and list/heading/quote/table markers from a single line."""
    stripped = _MARKDOWN_LINK_RE.sub(r"\1", line)
    stripped = _MARKDOWN_INLINE_RE.sub("", stripped)
    stripped = re.sub(r"^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)", "", stripped)
    if stripped.strip().startswith("|"):
        cells = [c.strip() for c in stripped.strip().strip("|").split("|")]
        stripped = " — ".join(c for c in cells if c and not set(c) <= set("-: "))
    return stripped


def _ends_with_abbreviation(text: str, next_char: str = "") -> bool:
    """True when the period closes an abbreviation rather than the sentence. A company
    suffix ("S.A.", "Inc.") followed by a capitalized word ends the sentence."""
    tail = text[-ABBREVIATION_WINDOW:].rstrip().rstrip(".").split()
    if not tail:
        return False
    last = fold(tail[-1]).strip("(\"'")
    if last in _COMPANY_SUFFIXES:
        return not next_char.isupper()
    return last in _ABBREVIATIONS or (len(last) == 1 and last.isalpha())


def split_sentences(text: str, offset: int = 0) -> Iterator[tuple[int, int]]:
    """Yield (start, end) spans of sentences in ``text``, shifted by ``offset``.

    Splits after terminal punctuation followed by whitespace, unless the preceding
    word is a known abbreviation (e.g. "S.A.C.", "Dr.") or a single initial.
    """
    start = 0
    for match in _SENTENCE_END_RE.finditer(text):
        candidate_end = match.end()
        window = text[max(start, match.start() - ABBREVIATION_WINDOW):match.start() + 1]
        if _ends_with_abbreviation(window, text[candidate_end:candidate_end + 1]):
            continue
        yield from _trimmed_span(text, start, candidate_end, offset)
        start = candidate_end
    yield from _trimmed_span(text, start, len(text), offset)


def _trimmed_span(text: str, start: int, end: int, offset: int) -> Iterator[tuple[int, int]]:
    """Trimmed span; overly long run-on segments are cut at whitespace into bounded pieces."""
    segment = text[start:end]
    if not segment.strip():
        return
    left = len(segment) - len(segment.lstrip())
    right = len(segment.rstrip())
    piece_start, stop = start + left, start + right
    while stop - piece_start > MAX_SENTENCE_CHARS:
        cut = text.rfind(" ", piece_start + 1, piece_start + MAX_SENTENCE_CHARS) or piece_start + MAX_SENTENCE_CHARS
        if cut <= piece_start:
            cut = piece_start + MAX_SENTENCE_CHARS
        yield (offset + piece_start, offset + cut)
        piece_start = cut + 1
    yield (offset + piece_start, offset + stop)
