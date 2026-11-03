"""Linguistic signals extracted from a sentence: polarity, direction, hedging, quantifiers, dates.

Polarity and direction are tracked per clause so that a negation in an unrelated
sub-clause ("The company, which is not listed, reported...") does not flip the
meaning of the clause a claim is actually about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable, Mapping

from .lexicon import (
    AMBIGUOUS_MONTHS,
    COMPARISON_MARKERS,
    CONDITIONAL_FALSE_FRIENDS,
    CONDITIONAL_WORDS,
    HEDGE_PHRASES,
    HEDGE_WORDS,
    MONTHS,
    NEGATION_FALSE_FRIENDS,
    NEGATIONS,
    PARTIAL_QUANTIFIERS,
    PAST_STATE_WORDS,
    PRESENT_STATE_WORDS,
    PROPORTION_RANGES,
    UNIVERSAL_QUANTIFIERS,
)
from .numbers import NumberKind, NumberMention, extract_numbers
from .text import (
    DEFAULT_SYNONYMS,
    DIRECTION_DOWN_TERM,
    DIRECTION_UP_TERM,
    content_stems,
    direction_term,
    fold,
    stated_proportion,
    stem,
    words,
)

FULL_PERCENT = 100.0
_PAST_VERB_RE = re.compile(r"\b\w{3,}(?:ó|aron|ieron)\b|\b\w{3,}ed\b")
_FUTURE_RE = re.compile(r"\b\w{2,}(?:ará|erá|irá)n?\b|\b(?:will|shall)\b")
_CONDITIONAL_RE = re.compile(r"\b\w{2,}(?:aría|ería|iría)n?\b")
_BASELINE_RE = re.compile(
    r"(?:que en|que el|respecto (?:a|al|de|del)|frente (?:a|al)|comparado con|than in|than|compared (?:with|to)|"
    r"versus|vs\.?|over)\s*(?:el |the |de )?(?:ano |year |ejercicio )?$"
)
_YEAR_RANGE_RE = re.compile(r"(?:entre|between|from|de|desde)\s+(\d{4})\s*(?:y|and|to|a|al|hasta|-|–)\s*(\d{4})")
_FROM_RE = re.compile(r"(?:\bde|\bdesde|\bfrom)\s*(?:s/\.?|usd|us\$|\$|€)?\s*$")
_TO_RE = re.compile(r"^\s*+%?\s*+(?:a|al|hasta|to)\s*+(?:s/\.?|usd|us\$|\$|€)?\s*+$")
_IF_RE = re.compile(r"(?:^|[\s,;(])(?:si|if)\s")  # Spanish: unaccented "si" is "if"; "sí" means "yes"
_COMPARATIVES = frozenset("mas menos mayor menor more less fewer higher lower".split())
_COMPARATIVE_UP_RE = re.compile(r"\b(?:mas|more|higher|mayor)\s+(?:que|than)\b|%\s*(?:mas|more)\b")
_COMPARATIVE_DOWN_RE = re.compile(r"\b(?:menos|less|fewer|lower|menor)\s+(?:que|than)\b|%\s*(?:menos|less|fewer)\b")
_CLAUSE_BOUNDARY_RE = re.compile(
    r"[;:]|,\s|\s(?:y|e|and|pero|but|mientras|while|aunque|although|frente|versus|vs)\s"
)


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"


@dataclass(frozen=True)
class AnchoredNumber:
    """A number plus the content stems of the clause it appears in (its local subject)."""

    mention: NumberMention
    context: frozenset[str]
    head: str | None = None
    """Content stem right after the number: what it counts ("300 admins" -> "admin")."""
    scope: frozenset[str] = frozenset()
    """Stems of its clause and the clause before it (where its subject usually is)."""
    years: frozenset[int] = frozenset()
    """Years named in the same clause: the period this figure refers to."""
    superseded: bool = False
    """The starting value of a change ("from 8% to 5%"): no longer the current value."""


@dataclass(frozen=True)
class ClauseSignals:
    stems: frozenset[str]
    negations: frozenset[str]
    """Negation cue plus the word it modifies, e.g. "not decreased", Spanish "no disminuyo"."""
    direction: Direction | None

    @property
    def negated(self) -> bool:
        return bool(self.negations)


@dataclass(frozen=True)
class SentenceSignals:
    stems: tuple[str, ...]
    clauses: tuple[ClauseSignals, ...]
    numbers: tuple[AnchoredNumber, ...]
    hedged: bool
    universal: bool
    partial: bool
    months: frozenset[int]
    proportion: tuple[str, float, float] | None = None
    conditional: bool = False
    """Conditional mood or an "if" clause ("would start if approved", Spanish "comenzarían si se aprueba")."""
    present_state: bool = False
    """States a current situation ("is", "has", Spanish "es", "tiene")."""
    past: bool = False
    """Narrates a past event or former state ("was", "resigned", Spanish "fue", "renunció")."""
    """Implied share, e.g. ("majority", 50, 100.01) for "the majority"."""

    @property
    def negated(self) -> bool:
        return any(c.negated for c in self.clauses)

    @property
    def direction(self) -> Direction | None:
        return _merge_directions(c.direction for c in self.clauses)

    @property
    def years(self) -> frozenset[int]:
        return frozenset(int(n.mention.value) for n in self.numbers if n.mention.kind is NumberKind.YEAR)

    @property
    def measures(self) -> tuple[AnchoredNumber, ...]:
        """Numbers other than years (amounts, counts, percentages)."""
        return tuple(n for n in self.numbers if n.mention.kind is not NumberKind.YEAR)

    @property
    def has_partial_percentage(self) -> bool:
        return any(
            n.mention.kind is NumberKind.PERCENT and n.mention.value < FULL_PERCENT for n in self.numbers
        )

    def focus(self, stems: Iterable[str]) -> tuple[frozenset[str], Direction | None]:
        """Negation phrases and direction of the clauses that best overlap ``stems``."""
        wanted = frozenset(stems)
        overlaps = [len(c.stems & wanted) for c in self.clauses]
        best = max(overlaps, default=0)
        # Every clause that shares a substantial part of the claim is in focus: the predicate
        # ("the auditors did not identify…") may sit apart from the longest overlapping clause.
        focal = [c for c, o in zip(self.clauses, overlaps) if o * 2 >= best] if best else list(self.clauses)
        negations = frozenset().union(*(c.negations for c in focal))
        return negations, _merge_directions(c.direction for c in focal)


def _merge_directions(directions: Iterable[Direction | None]) -> Direction | None:
    found = {d for d in directions if d is not None}
    return found.pop() if len(found) == 1 else None


def _without_false_friends(folded: str) -> str:
    for phrase in NEGATION_FALSE_FRIENDS:
        folded = folded.replace(phrase, " " * len(phrase))
    return folded


def _single_direction(up: bool, down: bool) -> Direction | None:
    if up == down:
        return None
    return Direction.UP if up else Direction.DOWN


def _verb_direction(tokens: tuple[str, ...]) -> Direction | None:
    terms = {direction_term(t) for t in tokens}
    return _single_direction(DIRECTION_UP_TERM in terms, DIRECTION_DOWN_TERM in terms)


def _comparative_direction(folded_clause: str) -> Direction | None:
    return _single_direction(
        bool(_COMPARATIVE_UP_RE.search(folded_clause)), bool(_COMPARATIVE_DOWN_RE.search(folded_clause))
    )


def _clause_directions(folded: str, spans: list[tuple[int, int]]) -> list[Direction | None]:
    """Direction per clause; a verbless comparative ("…, 6% less than in 2023") also
    applies to the clause it is attached to, i.e. the previous one."""
    directions = []
    for index, (start, end) in enumerate(spans):
        verb = _verb_direction(words(folded[start:end]))
        comparative = _comparative_direction(folded[start:end])
        directions.append(verb or comparative)
        if comparative and not verb and index > 0 and directions[index - 1] is None:
            directions[index - 1] = comparative
    return directions


def _negations(tokens: tuple[str, ...]) -> frozenset[str]:
    phrases = set()
    for index, token in enumerate(tokens):
        if token in NEGATIONS:
            following = stem(tokens[index + 1]) if index + 1 < len(tokens) else ""
            phrases.add(f"{token} {following}".strip())
    return frozenset(phrases)


def _is_hedged(folded: str, tokens: tuple[str, ...], text: str) -> bool:
    """Tentative, projected or future statements ("is estimated", "will open", Spanish future "abrirá")."""
    return (
        any(t in HEDGE_WORDS for t in tokens)
        or any(p in folded for p in HEDGE_PHRASES)
        or bool(_FUTURE_RE.search(text.lower()))
    )


def _is_conditional(tokens: tuple[str, ...], text: str) -> bool:
    lowered = text.lower()
    verbs = [m.group(0) for m in _CONDITIONAL_RE.finditer(lowered)]
    return (
        any(v not in CONDITIONAL_FALSE_FRIENDS for v in verbs)
        or bool(_IF_RE.search(lowered))
        or any(t in CONDITIONAL_WORDS for t in tokens)
    )


def _implied_trend(folded: str, numbers: list[AnchoredNumber]) -> Direction | None:
    """"3.1% in 2025, compared with 3.6% in 2024": the first figure is compared with a baseline."""
    if not any(marker in folded for marker in COMPARISON_MARKERS):
        return None
    for kind in (NumberKind.PERCENT, NumberKind.QUANTITY):
        values = [n.mention.value for n in numbers if n.mention.kind is kind]
        if len(values) == 2 and values[0] != values[1]:
            return Direction.UP if values[0] > values[1] else Direction.DOWN
    return None


def _months(tokens: tuple[str, ...]) -> frozenset[int]:
    return frozenset(MONTHS[t] for t in tokens if t in MONTHS and t not in AMBIGUOUS_MONTHS)


def _clause_spans(folded: str) -> list[tuple[int, int]]:
    cuts = [0, *(m.start() for m in _CLAUSE_BOUNDARY_RE.finditer(folded)), len(folded)]
    return [(a, b) for a, b in zip(cuts, cuts[1:]) if b > a]


def _head(text_after: str, synonyms: Mapping[str, str]) -> str | None:
    """The word immediately after a number, when it is a content noun ("300 admins")."""
    following = words(text_after)[:1]
    if not following or following[0] in _COMPARATIVES:
        return None
    terms = content_stems(following[0], synonyms)
    return terms[0] if terms else None


def _period_of(folded: str, mention: NumberMention, mentions: tuple[NumberMention, ...]) -> frozenset[int]:
    """Years a figure refers to: the nearest year that is not a comparison baseline
    ("6% less than in 2023"), widened to the whole range when it is part of one
    ("between 2022 and 2023")."""
    candidates = [
        m for m in mentions
        if m.kind is NumberKind.YEAR and not _BASELINE_RE.search(folded[max(0, m.start - 16):m.start])
    ]
    if not candidates:
        return frozenset()
    nearest = min(candidates, key=lambda m: min(abs(m.start - mention.end), abs(mention.start - m.end)))
    for match in _YEAR_RANGE_RE.finditer(folded):
        if match.start() <= nearest.start < match.end():
            return frozenset(range(int(match.group(1)), int(match.group(2)) + 1))
    return frozenset({int(nearest.value)})


def _is_starting_value(folded: str, mention: NumberMention, mentions: tuple[NumberMention, ...]) -> bool:
    """True for X in "from X to Y" (Spanish "de X a Y") when Y is a figure of the same kind."""
    if not _FROM_RE.search(folded[max(0, mention.start - 12):mention.start]):
        return False
    following = [m for m in mentions if m.start > mention.end and m.kind is mention.kind]
    return bool(following) and bool(_TO_RE.match(folded[mention.end:following[0].start]))


def analyze(text: str, synonyms: Mapping[str, str] = DEFAULT_SYNONYMS) -> SentenceSignals:
    """Extract all signals the judge needs from one sentence or claim."""
    folded = _without_false_friends(fold(text))
    spans = _clause_spans(folded)
    clauses = [
        ClauseSignals(
            stems=frozenset(content_stems(text[start:end], synonyms)),
            negations=_negations(words(folded[start:end])),
            direction=direction,
        )
        for (start, end), direction in zip(spans, _clause_directions(folded, spans))
    ]
    numbers = []
    mentions = extract_numbers(text)
    for mention in mentions:
        index = next(i for i, (s, e) in enumerate(spans) if s <= mention.start < e)
        clause_end = spans[index][1]
        previous = clauses[index - 1].stems if index else frozenset()
        clause_years = _period_of(folded, mention, mentions)
        numbers.append(AnchoredNumber(
            mention, clauses[index].stems, _head(text[mention.end:clause_end], synonyms),
            clauses[index].stems | previous, clause_years, _is_starting_value(folded, mention, mentions),
        ))
    trend = _implied_trend(folded, numbers)
    if trend is not None and numbers:
        first = next(i for i, (s, e) in enumerate(spans) if s <= numbers[0].mention.start < e)
        if clauses[first].direction is None:
            clauses[first] = replace(clauses[first], direction=trend)
    tokens = words(folded)
    return SentenceSignals(
        stems=content_stems(text, synonyms),
        clauses=tuple(clauses),
        numbers=tuple(numbers),
        hedged=_is_hedged(folded, tokens, text),
        conditional=_is_conditional(tokens, text),
        present_state=any(t in PRESENT_STATE_WORDS for t in tokens),
        past=any(t in PAST_STATE_WORDS for t in tokens) or bool(_PAST_VERB_RE.search(text.lower())),
        universal=any(t in UNIVERSAL_QUANTIFIERS for t in tokens),
        partial=any(t in PARTIAL_QUANTIFIERS for t in tokens),
        months=_months(tokens),
        proportion=(word, *PROPORTION_RANGES[word]) if (word := stated_proportion(tokens)) else None,
    )
