"""Safety guards: conditions under which a passage must not decide a claim.

A lexical judge can see that a passage shares a claim's words, numbers and dates, but not
who did what to whom, whether something was only requested, whether "nothing was found"
is a finding or a gap, or whether the evidence covers the whole population. Each guard
detects one of these situations with surface cues and returns an ``Effect``:

- ``IGNORE``: the passage is about something else (e.g. another named entity).
- ``ABSTAIN``: related, but the verifier cannot safely decide from it.
- ``WEAKEN``: at most partial support.
- ``CONTRADICT``: an explicit opposite outcome (e.g. a request that was rejected).

Guards never add understanding the lexicons do not encode; when unsure they abstain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .lexicon import (
    ABSENCE_PHRASES,
    DETERMINERS,
    EPISTEMIC_PREFIXES,
    NEGATIONS,
    QUOTE_MARKS,
    REPORTING_VERBS,
    SOURCE_PHRASES,
    COMPLEMENTIZERS,
    NUMBER_WORDS,
    PARTIAL_QUANTIFIERS,
    SCOPE_OPERATOR_PHRASES,
    SCOPE_OPERATORS,
    SINGULAR_DETERMINERS,
    SUBPERIOD_WORDS,
    CORRECTION_WORDS,
    GRANT_WORDS,
    MONTHS,
    PASSIVE_AUXILIARIES,
    PASSIVE_AGENT_MARKERS,
    PILOT_WORDS,
    POPULATION_DETERMINERS,
    POPULATION_NOUNS,
    REJECT_WORDS,
    REPORTED_SPEECH_PHRASES,
    REQUEST_PHRASES,
    REQUEST_WORDS,
    ROLE_PREPOSITIONS,
    SEGMENT_WORDS,
    MODAL_AUXILIARIES,
    SEGMENT_IDIOMS,
    SUBPERIOD_PHRASES,
)
from .models import Signal
from .text import DEFAULT_SYNONYMS, content_stems, content_terms, fold, words

_CAPITALIZED_RE = re.compile(r"[^\W\d_][^\W_]*", re.UNICODE)


class Effect(str, Enum):
    IGNORE = "ignore"
    ABSTAIN = "abstain"
    WEAKEN = "weaken"
    CONTRADICT = "contradict"


class GuardCode:
    ENTITY_NOT_IN_EVIDENCE = "ENTITY_NOT_IN_EVIDENCE"
    ROLE_INVERSION = "ROLE_INVERSION"
    ABSENCE_OF_EVIDENCE = "ABSENCE_OF_EVIDENCE"
    STAGE_NOT_REACHED = "STAGE_NOT_REACHED"
    STAGE_CONFLICT = "STAGE_CONFLICT"
    EMBEDDED_STATEMENT = "EMBEDDED_STATEMENT"
    NONFINITE_PREDICATE = "NONFINITE_PREDICATE"
    SCOPE_OPERATOR = "SCOPE_OPERATOR"
    PERIOD_SUBSET = "PERIOD_SUBSET"
    VOICE_MISMATCH = "VOICE_MISMATCH"
    POPULATION_SUBSET = "POPULATION_SUBSET"
    REPORTED_SPEECH = "REPORTED_SPEECH"


@dataclass(frozen=True)
class Guard:
    effect: Effect
    signal: Signal


def capitalized_stems(text: str, synonyms: Mapping[str, str], include_initial: bool) -> frozenset[str]:
    """Stems of capitalized content words (proper-noun candidates); months excluded."""
    found = set()
    for index, match in enumerate(_CAPITALIZED_RE.finditer(text)):
        token = match.group(0)
        if not token[0].isupper() or (index == 0 and not include_initial) or fold(token) in MONTHS:
            continue
        found.update(content_stems(token, synonyms))
    return frozenset(found)


def claim_entities(
    claim_text: str, corpus_entities: frozenset[str], synonyms: Mapping[str, str] = DEFAULT_SYNONYMS
) -> frozenset[str]:
    """Named entities of a claim: mid-sentence capitals, plus a sentence-initial capital
    when the corpus uses that word as a proper noun elsewhere."""
    initial = capitalized_stems(claim_text, synonyms, include_initial=True)
    inner = capitalized_stems(claim_text, synonyms, include_initial=False)
    return inner | (initial & corpus_entities)


def _has_any(folded: str, tokens: tuple[str, ...], vocabulary: frozenset[str], phrases: tuple[str, ...] = ()) -> bool:
    return any(t in vocabulary for t in tokens) or any(p in folded for p in phrases)


def _first_positions(text: str, synonyms: Mapping[str, str]) -> dict[str, int]:
    positions: dict[str, int] = {}
    for index, term in enumerate(content_terms(text, synonyms)):
        positions.setdefault(term, index)
    return positions


def _is_passive(tokens: tuple[str, ...]) -> bool:
    aux = [i for i, t in enumerate(tokens) if t in PASSIVE_AUXILIARIES]
    return bool(aux) and any(t in PASSIVE_AGENT_MARKERS for t in tokens[aux[0]:])


def _role_markers(text: str, synonyms: Mapping[str, str]) -> dict[str, str]:
    """Preposition introducing each capitalized entity ("acquisition of X by Y" -> X: of, Y: by)."""
    tokens = _CAPITALIZED_RE.findall(text)
    markers: dict[str, str] = {}
    for index, token in enumerate(tokens):
        if not token[0].isupper() or index == 0:
            continue
        back = index - 1
        while back >= 0 and tokens[back][0].isupper():
            back -= 1
        if back < 0:
            continue
        marker = fold(tokens[back])
        if marker == "de" and back >= 2 and fold(f"{tokens[back - 2]} {tokens[back - 1]}") == "por parte":
            marker = "por"
        if marker in ROLE_PREPOSITIONS:
            for stem in content_stems(token, synonyms):
                markers.setdefault(stem, marker)
    return markers


def _marker_swap(claim_text: str, passage_text: str, synonyms: Mapping[str, str]) -> tuple[str, str, str] | None:
    claim_markers, passage_markers = _role_markers(claim_text, synonyms), _role_markers(passage_text, synonyms)
    swapped = [e for e in claim_markers if e in passage_markers and claim_markers[e] != passage_markers[e]]
    if not swapped:
        return None
    entity = swapped[0]
    return entity, claim_markers[entity], passage_markers[entity]


def role_inversion(
    claim_text: str, passage_text: str, synonyms: Mapping[str, str] = DEFAULT_SYNONYMS
) -> tuple[str, str, str] | None:
    """(x, pivot, y) when x and y sit on opposite sides of a shared pivot word in the claim
    and swap sides in the passage ("A bought B" vs "B bought A"). One-way movement of a
    phrase (e.g. a date moved to the front) is not a swap and is not reported."""
    if _is_passive(words(claim_text)) != _is_passive(words(passage_text)):
        return None
    claim_pos, passage_pos = _first_positions(claim_text, synonyms), _first_positions(passage_text, synonyms)
    shared = [t for t in claim_pos if t in passage_pos]
    # Only participants can swap roles: named entities and noun phrases with a determiner.
    participants = _participants(claim_text, synonyms) & _participants(passage_text, synonyms)
    for pivot in shared:
        before = [t for t in shared if t in participants
                  and claim_pos[t] < claim_pos[pivot] and passage_pos[t] > passage_pos[pivot]]
        after = [t for t in shared if t in participants
                 and claim_pos[t] > claim_pos[pivot] and passage_pos[t] < passage_pos[pivot]]
        if before and after:
            return before[0], pivot, after[0]
    return None


def _participants(text: str, synonyms: Mapping[str, str]) -> frozenset[str]:
    tokens = _CAPITALIZED_RE.findall(text)
    found = set(capitalized_stems(text, synonyms, include_initial=True))
    for previous, token in zip(tokens, tokens[1:]):
        if fold(previous) in DETERMINERS:
            found.update(content_stems(token, synonyms))
    return frozenset(found)


def _negated_finding(passage_folded: str) -> str | None:
    """A negation next to a verb of finding/reporting ("found no …", "no se registraron …")."""
    tokens = words(passage_folded)
    for index, token in enumerate(tokens):
        if token in NEGATIONS:
            window = tokens[max(0, index - 3):index + 4]
            hit = next((w for w in window if w.startswith(EPISTEMIC_PREFIXES)), None)
            if hit:
                return f"{token} … {hit}"
    return None


def _absence_guard(claim_stems: frozenset[str], passage_folded: str, synonyms: Mapping[str, str]) -> Guard | None:
    phrase = next((p for p in ABSENCE_PHRASES if p in passage_folded), None) or _negated_finding(passage_folded)
    if phrase is None:
        return None
    # "No observations were identified" does decide "the auditors identified observations"
    # (same act of finding); it says nothing about whether irregularities existed.
    if claim_stems & frozenset(content_stems(phrase, synonyms)):
        return None
    detail = f"the evidence states a lack of information (“{phrase}”), not a fact"
    return Guard(Effect.ABSTAIN, Signal(GuardCode.ABSENCE_OF_EVIDENCE, detail))


def _stage_guard(claim_tokens: tuple[str, ...], claim_folded: str, passage_tokens: tuple[str, ...],
                 passage_folded: str) -> Guard | None:
    passage_request = _has_any(passage_folded, passage_tokens, REQUEST_WORDS, REQUEST_PHRASES)
    claim_request = _has_any(claim_folded, claim_tokens, REQUEST_WORDS, REQUEST_PHRASES)
    passage_grant = any(t in GRANT_WORDS for t in passage_tokens)
    passage_reject = any(t in REJECT_WORDS for t in passage_tokens)
    claim_grant = any(t in GRANT_WORDS for t in claim_tokens)
    claim_reject = any(t in REJECT_WORDS for t in claim_tokens)
    if claim_grant and not claim_reject and not claim_request and passage_reject and not passage_grant:
        return Guard(Effect.CONTRADICT, Signal(GuardCode.STAGE_CONFLICT, "the evidence states a rejection or denial"))
    if claim_reject and not claim_grant and passage_grant and not passage_reject:
        return Guard(Effect.CONTRADICT, Signal(GuardCode.STAGE_CONFLICT, "the evidence states an approval or grant"))
    if passage_request and not claim_request and not passage_grant and not passage_reject:
        detail = "the evidence describes a request, proposal or administrative procedure, not its outcome"
        return Guard(Effect.ABSTAIN, Signal(GuardCode.STAGE_NOT_REACHED, detail))
    return None


def _population_stems(text: str, tokens: tuple[str, ...], synonyms: Mapping[str, str]) -> frozenset[str]:
    """Population nouns: known ones plus any plural after a determiner ("the pharmacies")."""
    nouns = {t for t in tokens if t in POPULATION_NOUNS}
    nouns |= {b for a, b in zip(tokens, tokens[1:]) if a in POPULATION_DETERMINERS and b.endswith("s") and len(b) > 3}
    return frozenset(content_stems(" ".join(sorted(nouns)), synonyms))


def _population_guard(
    claim_text: str, claim_stems: frozenset[str], claim_tokens: tuple[str, ...],
    passage_text: str, passage_tokens: tuple[str, ...], topic_stems: frozenset[str], synonyms: Mapping[str, str],
    heading: str = "",
) -> Guard | None:
    """Claim about a population (or an implementation) vs evidence about a subset or a pilot."""
    pilot = {t for t in passage_tokens + words(fold(heading)) if t in PILOT_WORDS} - set(claim_tokens)
    if pilot:
        detail = "the evidence describes a pilot or trial, not a general rollout"
        return Guard(Effect.WEAKEN, Signal(GuardCode.POPULATION_SUBSET, detail))
    claim_units = claim_stems - frozenset(content_stems(" ".join(_idiomatic_segment_words(claim_tokens)), synonyms))
    segments = {
        t for t in passage_tokens
        if t in SEGMENT_WORDS and not set(content_stems(t, synonyms)) & (claim_units | topic_stems)
    } - _idiomatic_segment_words(passage_tokens)
    specialized = _specialized_entities(claim_text, passage_text, claim_stems | topic_stems, synonyms)
    if segments or specialized:
        detail = "the evidence refers to a part: " + ", ".join(sorted(segments | specialized))
        return Guard(Effect.WEAKEN, Signal(GuardCode.POPULATION_SUBSET, detail))
    passage_stems = frozenset(content_stems(passage_text, synonyms))
    claim_population = _population_stems(claim_text, claim_tokens, synonyms)
    if not claim_population & passage_stems:
        return None
    named = capitalized_stems(passage_text, synonyms, include_initial=False) - claim_stems - topic_stems
    named -= capitalized_stems(claim_text, synonyms, include_initial=True)
    if not named:
        return None
    detail = "the evidence refers to a subset: " + ", ".join(sorted(named))
    return Guard(Effect.WEAKEN, Signal(GuardCode.POPULATION_SUBSET, detail))


def _phrase_count(tokens: tuple[str, ...], phrase: tuple[str, ...]) -> int:
    return sum(1 for i in range(len(tokens) - len(phrase) + 1) if tokens[i:i + len(phrase)] == phrase)


def _idiomatic_segment_words(tokens: tuple[str, ...]) -> set[str]:
    """Segment words that occur only inside idioms ("took office"), where they name no unit."""
    inside: dict[str, int] = {}
    for idiom in SEGMENT_IDIOMS:
        phrase = tuple(idiom.split())
        count = _phrase_count(tokens, phrase)
        for word in phrase:
            if count and word in SEGMENT_WORDS:
                inside[word] = inside.get(word, 0) + count
    return {word for word, count in inside.items() if tokens.count(word) <= count}


def _specialized_entities(
    claim_text: str, passage_text: str, allowed: frozenset[str], synonyms: Mapping[str, str]
) -> set[str]:
    """Capitalized words right after a claim entity in the passage ("Pucarumi *Norte*"):
    the passage talks about a part of that entity."""
    claim_named = capitalized_stems(claim_text, synonyms, include_initial=True)
    tokens = _CAPITALIZED_RE.findall(passage_text)
    extra = set()
    for index, token in enumerate(tokens[:-1]):
        following = tokens[index + 1]
        if set(content_stems(token, synonyms)) & claim_named and following[0].isupper():
            extra |= set(content_stems(following, synonyms)) - allowed - claim_named
    return extra


def _reported_guard(claim_folded: str, passage_folded: str, passage_text: str) -> Guard | None:
    claim_tokens = set(words(claim_folded))
    candidates = [p for p in REPORTED_SPEECH_PHRASES if p in passage_folded and p not in claim_folded]
    candidates += [t for t in words(passage_folded) if t in REPORTING_VERBS and t not in claim_tokens]
    candidates += [p for p in SOURCE_PHRASES if p in passage_folded and p not in claim_folded]
    candidates += [q for q in QUOTE_MARKS if q in passage_text and q not in claim_folded]
    phrase = candidates[0] if candidates else None
    if phrase is None:
        return None
    detail = f"the evidence attributes the information to a third party (“{phrase}”); the claim states it as fact"
    return Guard(Effect.WEAKEN, Signal(GuardCode.REPORTED_SPEECH, detail))


_DIGITS_RE = re.compile(r"\d[\d.,]*")
_INFINITIVE_RE = re.compile(r"(?:ar|er|ir|arse|erse|irse|ando|iendo)$")
_FRACTION_RE = re.compile(
    r"(?:\d[\d.,]*\s*%?|\b(?:" + "|".join(sorted(NUMBER_WORDS)) + r"))\s+(?:de|of)\s+(?:los|las|the|sus|their)?\s*\w+"
)


def _embedded_statement(claim_stems: frozenset[str], passage_text: str, allowed: frozenset[str],
                        synonyms: Mapping[str, str]) -> str | None:
    """Most of the claim sits inside a "que/that/whether" clause governed by material the claim lacks."""
    raw = _CAPITALIZED_RE.findall(passage_text)
    for index, token in enumerate(raw):
        if fold(token) not in COMPLEMENTIZERS:
            continue
        before = frozenset(content_stems(" ".join(raw[:index]), synonyms))
        after = frozenset(content_stems(" ".join(raw[index + 1:]), synonyms))
        matched = claim_stems & (before | after)
        frame = before - claim_stems - allowed
        if matched and len(claim_stems & after) * 5 >= len(matched) * 3 and frame:
            return " ".join(raw[max(0, index - 3):index + 1])
    return None


def _nonfinite_predicate(claim_text: str, passage_text: str, synonyms: Mapping[str, str]) -> str | None:
    """A verb stated as done in the claim ("built", Spanish "construyó") appears only as an
    infinitive or gerund in the evidence ("promised to build", "denies polluting", Spanish
    "prometió construir", "acusada de contaminar")."""
    claim_tokens = [t.lower() for t in _CAPITALIZED_RE.findall(claim_text)]
    passage_tokens = [t.lower() for t in _CAPITALIZED_RE.findall(passage_text)]
    for token in claim_tokens:
        if len(token) < 5 or _INFINITIVE_RE.search(fold(token)) or token.endswith("ing"):
            continue
        stem_set = set(content_stems(token, synonyms))
        forms = [(i, p) for i, p in enumerate(passage_tokens) if stem_set & set(content_stems(p, synonyms))]
        if not forms:
            continue
        nonfinite = [
            p for i, p in forms
            if p != token and (
                (_INFINITIVE_RE.search(fold(p)) and token not in {p + "s", p + "es"})
                or (p.endswith("ing") and not token.endswith("ing"))
                or (i > 0 and (passage_tokens[i - 1] in {"to", "haber", "having"}
                               or passage_tokens[i - 1] in MODAL_AUXILIARIES))
            )
        ]
        if len(nonfinite) == len(forms):
            return nonfinite[0]
    return None


def _scope_operators(claim_tokens: tuple[str, ...], claim_folded: str, passage_tokens: tuple[str, ...],
                     passage_folded: str, claim_has_numbers: bool) -> set[str]:
    claim_set = set(claim_tokens)
    found = {t for t in passage_tokens if t in SCOPE_OPERATORS | PARTIAL_QUANTIFIERS and t not in claim_set}
    found |= {p for p in SCOPE_OPERATOR_PHRASES if p in passage_folded and p not in claim_folded}
    claim_shape = _DIGITS_RE.sub("#", claim_folded)
    found |= {
        m.group(0) for m in _FRACTION_RE.finditer(passage_folded) if _DIGITS_RE.sub("#", m.group(0)) not in claim_shape
    }
    claim_plurals = {t for t in claim_tokens if t.endswith("s") and len(t) > 3}
    for determiner, noun in zip(passage_tokens, passage_tokens[1:]):
        if determiner in SINGULAR_DETERMINERS and any(p.startswith(noun) and p != noun for p in claim_plurals):
            found.add(f"{determiner} {noun}")
    return found


def _frame_guards(
    claim_text: str, claim_stems: frozenset[str], claim_tokens: tuple[str, ...], claim_folded: str,
    passage_text: str, passage_tokens: tuple[str, ...], passage_folded: str, topic_stems: frozenset[str],
    claim_has_numbers: bool, synonyms: Mapping[str, str],
) -> list[Guard]:
    """Closed-class and morphological cues that the evidence does not assert the claim as such."""
    guards = []
    embedded = _embedded_statement(claim_stems, passage_text, topic_stems, synonyms)
    if embedded:
        detail = f"the evidence embeds the content in another proposition (“{embedded}”)"
        guards.append(Guard(Effect.WEAKEN, Signal(GuardCode.EMBEDDED_STATEMENT, detail)))
    nonfinite = _nonfinite_predicate(claim_text, passage_text, synonyms)
    if nonfinite:
        detail = f"the action appears only as an intention, accusation or possibility (“{nonfinite}”)"
        guards.append(Guard(Effect.WEAKEN, Signal(GuardCode.NONFINITE_PREDICATE, detail)))
    operators = _scope_operators(claim_tokens, claim_folded, passage_tokens, passage_folded, claim_has_numbers)
    if operators:
        detail = "the evidence restricts or qualifies the scope: " + ", ".join(sorted(operators))
        guards.append(Guard(Effect.WEAKEN, Signal(GuardCode.SCOPE_OPERATOR, detail)))
    periods = {t for t in passage_tokens if t in SUBPERIOD_WORDS} - set(claim_tokens)
    periods |= {p for p in SUBPERIOD_PHRASES if _phrase_count(passage_tokens, tuple(p.split()))
                and not _phrase_count(claim_tokens, tuple(p.split()))}
    if periods:
        detail = "the evidence covers only part of the period: " + ", ".join(sorted(periods))
        guards.append(Guard(Effect.WEAKEN, Signal(GuardCode.PERIOD_SUBSET, detail)))
    return guards


def run_guards(
    claim_text: str,
    passage_text: str,
    context_stems: frozenset[str],
    corpus_entities: frozenset[str],
    claim_has_numbers: bool,
    synonyms: Mapping[str, str] = DEFAULT_SYNONYMS,
    heading: str = "",
) -> tuple[Guard, ...]:
    """All guards that fire for this claim/passage pair, strongest effect first."""
    claim_folded, passage_folded = fold(claim_text), fold(passage_text)
    claim_tokens, passage_tokens = words(claim_folded), words(passage_folded)
    claim_stems = frozenset(content_stems(claim_text, synonyms))
    passage_stems = frozenset(content_stems(passage_text, synonyms))
    guards: list[Guard] = []
    missing_entities = claim_entities(claim_text, corpus_entities, synonyms) - passage_stems - context_stems
    if missing_entities:
        detail = "claim entities absent from the passage: " + ", ".join(sorted(missing_entities))
        guards.append(Guard(Effect.IGNORE, Signal(GuardCode.ENTITY_NOT_IN_EVIDENCE, detail)))
    if _is_passive(claim_tokens) != _is_passive(passage_tokens) and len(claim_stems & passage_stems) >= 3:
        detail = "active vs passive voice: who does what cannot be compared"
        guards.append(Guard(Effect.WEAKEN, Signal(GuardCode.VOICE_MISMATCH, detail)))
    inversion = role_inversion(claim_text, passage_text, synonyms)
    swap = None if inversion else _marker_swap(claim_text, passage_text, synonyms)
    if inversion:
        detail = "roles reversed around “{1}”: “{0}” and “{2}” swap sides".format(*inversion)
        guards.append(Guard(Effect.ABSTAIN, Signal(GuardCode.ROLE_INVERSION, detail)))
    elif swap:
        detail = "“{0}” changes role: “{1} …” in the claim, “{2} …” in the evidence".format(*swap)
        guards.append(Guard(Effect.ABSTAIN, Signal(GuardCode.ROLE_INVERSION, detail)))
    for guard in (
        _absence_guard(claim_stems, passage_folded, synonyms),
        _stage_guard(claim_tokens, claim_folded, passage_tokens, passage_folded),
        _population_guard(claim_text, claim_stems, claim_tokens, passage_text, passage_tokens, context_stems, synonyms,
                          heading),
        _reported_guard(claim_folded, passage_folded, passage_text),
    ):
        if guard is not None:
            guards.append(guard)
    guards.extend(_frame_guards(claim_text, claim_stems, claim_tokens, claim_folded, passage_text, passage_tokens,
                                passage_folded, context_stems, claim_has_numbers, synonyms))
    order = [Effect.IGNORE, Effect.ABSTAIN, Effect.CONTRADICT, Effect.WEAKEN]
    return tuple(sorted(guards, key=lambda g: order.index(g.effect)))


def has_correction(passage_tokens: tuple[str, ...]) -> bool:
    return any(t in CORRECTION_WORDS for t in passage_tokens)
