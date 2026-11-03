"""Passage-level judgement: does this passage support, contradict or not address a claim?

The default ``LexicalJudge`` is deterministic and explainable: every stance is
backed by ``Signal`` codes (term coverage, number agreement, polarity, direction,
dates, hedging, quantifiers). Any other implementation of ``Judge`` (for example an
NLI model or an LLM) can be plugged into ``ClaimsVerifier`` instead.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Callable, Mapping, Protocol

from .corpus import Corpus
from .models import Claim, Passage, PassageAssessment, Signal, Stance
from .numbers import NumberKind, NumberMention, Qualifier, values_agree
from .signals import AnchoredNumber, Direction, SentenceSignals, analyze
from .safety import Effect, Guard, capitalized_stems, claim_entities, has_correction, run_guards
from .text import DEFAULT_SYNONYMS, DIRECTION_DOWN_TERM, DIRECTION_UP_TERM, fold, words

SIGNAL_CACHE_SIZE = 4096
RICH_ATTRIBUTE_TERMS = 4
"""An attribute described with this many terms may leave one (usually a verb) unmatched."""
_DIRECTION_LABELS = {Direction.UP: "an increase", Direction.DOWN: "a decrease"}
_DIRECTION_TERMS = frozenset({DIRECTION_UP_TERM, DIRECTION_DOWN_TERM})


class Code:
    """Signal codes emitted by the lexical judge."""

    NUMBER_MATCH = "NUMBER_MATCH"
    NUMBER_MISMATCH = "NUMBER_MISMATCH"
    NUMBER_NOT_FOUND = "NUMBER_NOT_FOUND"
    ATTRIBUTE_PARAPHRASE = "ATTRIBUTE_PARAPHRASE"
    DATE_MISMATCH = "DATE_MISMATCH"
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    NEGATION_MISMATCH = "NEGATION_MISMATCH"
    DIRECTION_MISMATCH = "DIRECTION_MISMATCH"
    HEDGED_EVIDENCE = "HEDGED_EVIDENCE"
    QUANTIFIER_OVERSTATED = "QUANTIFIER_OVERSTATED"
    MISSING_TERMS = "MISSING_TERMS"
    DIRECTION_NOT_STATED = "DIRECTION_NOT_STATED"
    WEAK_CONTRADICTION = "WEAK_CONTRADICTION"
    STATE_NOT_CURRENT = "STATE_NOT_CURRENT"
    LOW_RELEVANCE = "LOW_RELEVANCE"


@dataclass(frozen=True)
class JudgeConfig:
    relevance_min: float = 0.45
    """Below this term coverage a passage is considered unrelated."""
    topic_min: float = 0.6
    """Coverage required before a mismatch is treated as a contradiction."""
    support_min: float = 0.75
    """Coverage required for full support."""
    numeric_support_bonus: float = 0.1
    """Support threshold is lowered by this much when every claim number agrees."""
    context_weight: float = 0.5
    """Weight of a claim term found only in the title/heading/previous sentence."""


class Judge(Protocol):
    name: str

    def assess(self, claim: Claim, passage: Passage, retrieval_score: float) -> PassageAssessment: ...


@dataclass(frozen=True)
class _Coverage:
    relevance: float
    matched: tuple[str, ...]
    missing: tuple[str, ...]


class LexicalJudge:
    name = "lexical-v2-guarded"

    def __init__(
        self,
        corpus: Corpus,
        idf: Callable[[str], float],
        synonyms: Mapping[str, str] = DEFAULT_SYNONYMS,
        config: JudgeConfig = JudgeConfig(),
    ) -> None:
        self._idf = idf
        self._synonyms = synonyms
        self._config = config
        self._titles = {doc.doc_id: doc.title for doc in corpus.documents}
        self._corpus_entities = frozenset().union(
            *(capitalized_stems(p.text, synonyms, include_initial=False) for p in corpus.passages)
        )
        self._signals = lru_cache(maxsize=SIGNAL_CACHE_SIZE)(lambda text: analyze(text, synonyms))

    def signals(self, text: str) -> SentenceSignals:
        return self._signals(text)

    def _context(self, passage: Passage) -> SentenceSignals:
        return self._signals(" . ".join((self._titles.get(passage.doc_id, ""), passage.heading, passage.previous_text)))

    def _coverage(self, claim_stems: tuple[str, ...], passage: SentenceSignals, context: SentenceSignals) -> _Coverage:
        if not claim_stems:
            return _Coverage(0.0, (), ())
        total = sum(self._idf(t) for t in claim_stems)
        gained = 0.0
        matched, missing = [], []
        passage_stems, context_stems = frozenset(passage.stems), frozenset(context.stems)
        _, focal_direction = passage.focus(claim_stems)
        for term in claim_stems:
            if term in passage_stems or (term in _DIRECTION_TERMS and focal_direction is not None):
                # A change stated about the same subject (even the opposite one) is on topic;
                # the direction check decides whether it contradicts.
                gained += self._idf(term)
                matched.append(term)
            elif term in context_stems:
                gained += self._idf(term) * self._config.context_weight
                matched.append(term)
            else:
                missing.append(term)
        return _Coverage(round(gained / total, 4) if total else 0.0, tuple(matched), tuple(missing))

    def assess(self, claim: Claim, passage: Passage, retrieval_score: float) -> PassageAssessment:
        cs = self._signals(claim.text)
        ps = self._signals(passage.text)
        if passage.heading and self._signals(passage.heading).hedged and not ps.hedged:
            ps = replace(ps, hedged=True)  # a section headed "Borrador"/"Proyecciones" is tentative throughout
        ctx = self._context(passage)
        coverage = self._coverage(cs.stems, ps, ctx)
        # Entities must be named in the passage or its document title/heading, not merely nearby.
        topic = self._signals(" . ".join((self._titles.get(passage.doc_id, ""), passage.heading)))
        guards = run_guards(
            claim.text, passage.text, frozenset(topic.stems), self._corpus_entities, bool(cs.measures), self._synonyms,
            heading=passage.heading,
        )
        entities = claim_entities(claim.text, self._corpus_entities, self._synonyms)
        stance, signals = self._decide(
            cs, ps, ctx, coverage, guards, has_correction(words(fold(passage.text))), frozenset(topic.stems), entities
        )
        return PassageAssessment(
            passage=passage,
            stance=stance,
            relevance=coverage.relevance,
            retrieval_score=retrieval_score,
            signals=signals,
            matched_terms=coverage.matched,
            missing_terms=coverage.missing,
        )

    def _contradiction_or_abstain(
        self,
        cs: SentenceSignals,
        ps: SentenceSignals,
        coverage: _Coverage,
        contradictions: tuple[Signal, ...],
        weakening: tuple[Signal, ...],
    ) -> tuple[Stance, tuple[Signal, ...]]:
        """A contradiction must meet at least the standard of support: the passage covers the
        claim, is about the same population and actors, and the claim is a factual statement."""
        reasons = list(weakening)
        # Same bar as support: figures and dates lower it by the numeric bonus, polarity does not.
        factual = {Code.NUMBER_MISMATCH, Code.DATE_MISMATCH}
        bar = self._config.support_min
        if all(c.code in factual for c in contradictions):
            bar -= self._config.numeric_support_bonus
        if coverage.relevance < bar:
            reasons.append(Signal(Code.WEAK_CONTRADICTION, f"term coverage {coverage.relevance:.2f} is insufficient to refute"))
        if cs.hedged or cs.conditional:
            reasons.append(Signal(Code.WEAK_CONTRADICTION, "the claim is a plan or a possibility; the evidence does not refute it"))
        if reasons:
            return Stance.AMBIGUOUS, contradictions + tuple(reasons)
        return Stance.CONTRADICTS, contradictions

    def _decide(
        self,
        cs: SentenceSignals,
        ps: SentenceSignals,
        ctx: SentenceSignals,
        coverage: _Coverage,
        guards: tuple[Guard, ...] = (),
        corrected: bool = False,
        topic_terms: frozenset[str] = frozenset(),
        entities: frozenset[str] = frozenset(),
    ) -> tuple[Stance, tuple[Signal, ...]]:
        cfg = self._config
        if coverage.relevance < cfg.relevance_min:
            return Stance.NEUTRAL, (Signal(Code.LOW_RELEVANCE, f"term coverage {coverage.relevance:.2f}"),)
        by_effect = {effect: tuple(g.signal for g in guards if g.effect is effect) for effect in Effect}
        if by_effect[Effect.IGNORE]:
            return Stance.NEUTRAL, by_effect[Effect.IGNORE]
        if by_effect[Effect.ABSTAIN]:
            return Stance.AMBIGUOUS, by_effect[Effect.ABSTAIN]
        on_topic = coverage.relevance >= cfg.topic_min
        if corrected:
            ps = _latest_values(ps)

        scope = _scope_check(cs, ps.years | ctx.years, on_topic)
        if scope is not None and scope.code == Code.DATE_MISMATCH:
            return self._contradiction_or_abstain(cs, ps, coverage, (scope,), by_effect[Effect.WEAKEN])
        if scope is not None:
            return Stance.NEUTRAL, (scope,)

        contradictions = list(_polarity_conflicts(cs, ps)) if on_topic else []
        if on_topic and cs.months and ps.months and not cs.months & ps.months:
            contradictions.append(Signal(Code.DATE_MISMATCH, f"months {sorted(cs.months)} in the claim vs {sorted(ps.months)} in the evidence"))
        number_signals = [_check_number(n, ps, ctx, on_topic, topic_terms, entities) for n in cs.measures]
        proportion = _check_proportion(cs, ps, on_topic)
        if proportion is not None:
            number_signals.append(proportion)
        contradictions += [s for s in number_signals if s.code == Code.NUMBER_MISMATCH]
        contradictions += by_effect[Effect.CONTRADICT] if on_topic else ()
        if contradictions:
            return self._contradiction_or_abstain(cs, ps, coverage, tuple(contradictions), by_effect[Effect.WEAKEN])

        qualifiers = list(number_signals) + list(by_effect[Effect.WEAKEN]) + _weakening_signals(cs, ps)
        numbers_ok = all(s.code == Code.NUMBER_MATCH for s in number_signals)
        threshold = cfg.support_min - (cfg.numeric_support_bonus if number_signals and numbers_ok else 0.0)
        weakening = [s for s in qualifiers if s.code != Code.NUMBER_MATCH]
        if coverage.relevance >= threshold and not weakening:
            return Stance.SUPPORTS, tuple(qualifiers)
        if coverage.missing:
            qualifiers.append(Signal(Code.MISSING_TERMS, ", ".join(coverage.missing)))
        return Stance.PARTIAL, tuple(qualifiers)


def _weakening_signals(cs: SentenceSignals, ps: SentenceSignals) -> list[Signal]:
    """Reasons why an otherwise matching passage supports the claim only in part."""
    signals = []
    if (ps.hedged and not cs.hedged) or (ps.conditional and not cs.conditional):
        signals.append(Signal(Code.HEDGED_EVIDENCE, "the evidence is tentative, conditional or projected; "
                                                    "the claim states it with more certainty"))
    if cs.months and not ps.months:
        signals.append(Signal(Code.NUMBER_NOT_FOUND, "the month stated in the claim does not appear in this passage"))
    _, claim_direction = cs.focus(cs.stems)
    if claim_direction is not None and ps.focus(cs.stems)[1] is None:
        signals.append(Signal(Code.DIRECTION_NOT_STATED, "the evidence does not state the direction of the "
                                                         "change the claim asserts"))
    if cs.present_state and not ps.present_state and ps.past:
        signals.append(Signal(Code.STATE_NOT_CURRENT, "the claim describes a current situation; the evidence, "
                                                      "a past event or state"))
    if cs.universal and (ps.partial or ps.has_partial_percentage) and not ps.universal:
        signals.append(Signal(Code.QUANTIFIER_OVERSTATED, "the claim generalizes; the evidence covers only part"))
    return signals


def _scope_check(cs: SentenceSignals, evidence_years: frozenset[int], on_topic: bool) -> Signal | None:
    """Years in the claim vs the evidence: a different period, or a wrong date."""
    if not cs.years or not evidence_years:
        return None
    # Measures (figures or a stated proportion) only need an overlapping period; a dated event must match
    # every year it names.
    measured = bool(cs.measures) or cs.proportion is not None
    if (cs.years & evidence_years) if measured else (cs.years <= evidence_years):
        return None
    detail = f"years {sorted(cs.years)} in the claim vs {sorted(evidence_years)} in the evidence"
    if measured or not on_topic:
        return Signal(Code.SCOPE_MISMATCH, detail)
    return Signal(Code.DATE_MISMATCH, detail)


def _polarity_conflicts(cs: SentenceSignals, ps: SentenceSignals) -> list[Signal]:
    claim_negations, claim_direction = cs.focus(cs.stems)
    passage_negations, passage_direction = ps.focus(cs.stems)
    # Negated phrases present on both sides (Spanish "agua no facturada", unbilled water) are lexical,
    # not clause polarity.
    claim_negated = bool(claim_negations - passage_negations)
    passage_negated = bool(passage_negations - claim_negations)
    if claim_direction and passage_direction:
        if claim_direction == passage_direction and claim_negated != passage_negated:
            return [Signal(Code.NEGATION_MISMATCH, "same change with opposite polarity")]
        if claim_direction != passage_direction and not claim_negated and not passage_negated:
            return [Signal(Code.DIRECTION_MISMATCH, f"the claim states {_DIRECTION_LABELS[claim_direction]}, the evidence states {_DIRECTION_LABELS[passage_direction]}")]
        return []
    if claim_negated != passage_negated:
        side = "the claim" if claim_negated else "the evidence"
        return [Signal(Code.NEGATION_MISMATCH, f"only {side} is negated")]
    return []


def _align(number: AnchoredNumber, candidates: tuple[AnchoredNumber, ...]) -> AnchoredNumber | None:
    """Pick the evidence number of the same kind that talks about the same thing.

    The counted noun ("300 *admins*") must not disagree; among the rest, clause overlap
    decides and a tie is resolved in favour of an agreeing value.
    """
    same_kind = [c for c in candidates if c.mention.kind is number.mention.kind]
    if number.head:
        same_head = [c for c in same_kind if c.head == number.head]
        same_kind = same_head or same_kind
    if not same_kind:
        return None
    ranked = sorted(
        same_kind,
        key=lambda c: (len(c.context & number.context), values_agree(number.mention, c.mention)),
        reverse=True,
    )
    best = ranked[0]
    if len(same_kind) > 1 and not best.context & number.context:
        agreeing = [c for c in same_kind if values_agree(number.mention, c.mention)]
        return agreeing[0] if agreeing else None
    return best


def _measures_same_attribute(number: AnchoredNumber, evidence_terms: frozenset[str], entities: frozenset[str]) -> bool:
    """The evidence must name what the claim's figure measures ("revenue" vs "net profit");
    entity names and change verbs do not identify the attribute."""
    attribute = number.context - entities - _DIRECTION_TERMS
    tolerated = 1 if len(attribute) >= RICH_ATTRIBUTE_TERMS else 0
    return len(attribute - evidence_terms) <= tolerated


def _evidence_is_exact(claim: NumberMention, evidence: NumberMention) -> bool:
    """Evidence that can confirm the claim's figure: an exact value, or a qualified one of the same kind
    ("more than 700" for "more than 600"). An approximate or bounded figure cannot confirm an exact claim,
    nor a bound in the other direction a bounded one."""
    return evidence.qualifier is Qualifier.EXACT or evidence.qualifier is claim.qualifier


def _bounded_consistent(claim: NumberMention, evidence: NumberMention) -> bool:
    if evidence.qualifier is Qualifier.AT_LEAST:
        return claim.value >= evidence.value
    if evidence.qualifier is Qualifier.AT_MOST:
        return claim.value <= evidence.value
    return values_agree(claim, evidence)


def _check_number(
    number: AnchoredNumber,
    ps: SentenceSignals,
    ctx: SentenceSignals,
    on_topic: bool,
    topic_terms: frozenset[str] = frozenset(),
    entities: frozenset[str] = frozenset(),
) -> Signal:
    claim_raw = number.mention.raw
    aligned = _align(number, ps.measures)
    if aligned is not None:
        evidence_raw = aligned.mention.raw
        if not _measures_same_attribute(number, aligned.scope | topic_terms, entities):
            if values_agree(number.mention, aligned.mention) and _evidence_is_exact(number.mention, aligned.mention):
                # Same value, attribute worded differently: undecidable lexically (paraphrase or another metric).
                return Signal(Code.ATTRIBUTE_PARAPHRASE, f"{claim_raw} ≈ {evidence_raw}, but the attribute is named differently")
            return Signal(Code.NUMBER_NOT_FOUND, f"{claim_raw}: the figure {evidence_raw} measures another attribute")
        if number.years and aligned.years and not number.years & aligned.years:
            return Signal(Code.NUMBER_NOT_FOUND, f"{claim_raw}: the figure {evidence_raw} refers to another period")
        agree = values_agree(number.mention, aligned.mention)
        if agree and aligned.superseded:
            return Signal(Code.NUMBER_NOT_FOUND, f"{claim_raw} is the value before a change, not the current one")
        if agree and _evidence_is_exact(number.mention, aligned.mention):
            return Signal(Code.NUMBER_MATCH, f"{claim_raw} ≈ {evidence_raw}")
        if agree:
            # Consistent but of another kind ("about 600" vs "fewer than 590"): neither confirms nor refutes.
            return Signal(Code.NUMBER_NOT_FOUND, f"{claim_raw}: the evidence gives a figure of another kind ({evidence_raw})")
        if _bounded_consistent(number.mention, aligned.mention):
            return Signal(Code.NUMBER_NOT_FOUND, f"{claim_raw}: the evidence only gives an approximate value ({evidence_raw})")
        if on_topic:
            return Signal(Code.NUMBER_MISMATCH, f"claim {claim_raw} vs evidence {evidence_raw}")
    if any(values_agree(number.mention, c.mention) for c in ctx.measures if c.mention.kind is number.mention.kind):
        # A figure in a neighbouring sentence may belong to something else: never a match.
        return Signal(Code.NUMBER_NOT_FOUND, f"{claim_raw} appears only outside this passage")
    return Signal(Code.NUMBER_NOT_FOUND, f"{claim_raw} does not appear in this passage")


def _check_proportion(cs: SentenceSignals, ps: SentenceSignals, on_topic: bool) -> Signal | None:
    """Compare an implied share ("the majority") with the percentage the evidence gives for the same subject."""
    if cs.proportion is None or cs.measures:
        return None
    wanted = frozenset(cs.stems)
    percents = [n for n in ps.measures if n.mention.kind is NumberKind.PERCENT and n.context & wanted]
    if not percents:
        return None
    best = max(len(n.context & wanted) for n in percents)
    aligned = [n for n in percents if len(n.context & wanted) == best]
    word, low, high = cs.proportion
    inside = [n for n in aligned if low < n.mention.value < high]
    if inside:
        return Signal(Code.NUMBER_MATCH, f"'{word}' ≈ {inside[0].mention.raw}")
    if on_topic:
        return Signal(Code.NUMBER_MISMATCH, f"claim '{word}' vs evidence {aligned[0].mention.raw}")
    return None


def _latest_values(ps: SentenceSignals) -> SentenceSignals:
    """In a sentence that corrects a figure ("corrected from 40 to 34"), only the last value
    of each kind stands; earlier ones are superseded."""
    last = {}
    for number in ps.numbers:
        last[number.mention.kind] = number
    return replace(ps, numbers=tuple(n for n in ps.numbers if last[n.mention.kind] is n))
