"""Claim-level verdicts from passage assessments, with explicit uncertainty."""

from __future__ import annotations

from datetime import date
from typing import Mapping, NamedTuple, Sequence

from .judge import Code
from .safety import GuardCode
from .models import Claim, ClaimResult, PassageAssessment, Signal, Stance, Verdict

MAX_SCORE = 0.99
SUPPORT_SCORE_SCALE = 0.9
CORROBORATION_BONUS = 0.05
MAX_CORROBORATING_SOURCES = 2
PARTIAL_SCORE_SCALE = 0.7
WEAK_MATCH_MARGIN = 0.1
CONTRADICTION_WEIGHTS: Mapping[str, float] = {
    Code.NUMBER_MISMATCH: 0.95,
    Code.DATE_MISMATCH: 0.9,
    Code.DIRECTION_MISMATCH: 0.85,
    Code.NEGATION_MISMATCH: 0.8,
}
_FACTUAL_CONTRADICTION_CODES = frozenset({Code.NUMBER_MISMATCH, Code.DATE_MISMATCH, GuardCode.STAGE_CONFLICT})
_STANCE_ORDER = {Stance.CONTRADICTS: 0, Stance.SUPPORTS: 1, Stance.AMBIGUOUS: 2, Stance.PARTIAL: 3, Stance.NEUTRAL: 4}


class Uncertainty:
    """Claim-level uncertainty codes."""

    CONFLICTING_SOURCES = "CONFLICTING_SOURCES"
    CERTAINTY_OVERSTATED = "CERTAINTY_OVERSTATED"
    QUANTIFIER_OVERSTATED = "QUANTIFIER_OVERSTATED"
    DETAIL_NOT_FOUND = "DETAIL_NOT_FOUND"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    WEAK_MATCH = "WEAK_MATCH"
    CLAIM_HEDGED = "CLAIM_HEDGED"
    NO_EVIDENCE = "NO_EVIDENCE"
    OUT_OF_CORPUS_SCOPE = "OUT_OF_CORPUS_SCOPE"
    OTHER_PERIOD_ONLY = "OTHER_PERIOD_ONLY"


_PARTIAL_CODE_MAP: Mapping[str, str] = {
    GuardCode.POPULATION_SUBSET: GuardCode.POPULATION_SUBSET,
    GuardCode.REPORTED_SPEECH: GuardCode.REPORTED_SPEECH,
    Code.HEDGED_EVIDENCE: Uncertainty.CERTAINTY_OVERSTATED,
    Code.QUANTIFIER_OVERSTATED: Uncertainty.QUANTIFIER_OVERSTATED,
    Code.NUMBER_NOT_FOUND: Uncertainty.DETAIL_NOT_FOUND,
    Code.ATTRIBUTE_PARAPHRASE: Uncertainty.DETAIL_NOT_FOUND,
    Code.DIRECTION_NOT_STATED: Uncertainty.DETAIL_NOT_FOUND,
    Code.STATE_NOT_CURRENT: Code.STATE_NOT_CURRENT,
    GuardCode.EMBEDDED_STATEMENT: GuardCode.EMBEDDED_STATEMENT,
    GuardCode.NONFINITE_PREDICATE: GuardCode.NONFINITE_PREDICATE,
    GuardCode.SCOPE_OPERATOR: GuardCode.SCOPE_OPERATOR,
    GuardCode.PERIOD_SUBSET: GuardCode.PERIOD_SUBSET,
    GuardCode.VOICE_MISMATCH: GuardCode.VOICE_MISMATCH,
    Code.MISSING_TERMS: Uncertainty.DETAIL_NOT_FOUND,
}


def _ranked(assessments: Sequence[PassageAssessment]) -> list[PassageAssessment]:
    return sorted(
        assessments,
        key=lambda a: (_STANCE_ORDER[a.stance], -a.relevance, -a.retrieval_score, a.passage.passage_id),
    )


def _docs(assessments: Sequence[PassageAssessment]) -> list[str]:
    return list(dict.fromkeys(a.passage.doc_id for a in assessments))


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _newest(doc_ids: Sequence[str], dates: Mapping[str, str | None]) -> str | None:
    """Most recent document by ISO date (YYYY-MM-DD); undated or unparseable ones are ignored."""
    dated = [(parsed, d) for d in doc_ids if (parsed := _parse_date(dates.get(d))) is not None]
    return max(dated)[1] if dated else None


def _conflict_signal(
    supports: list[PassageAssessment], contradicts: list[PassageAssessment], dates: Mapping[str, str | None]
) -> Signal:
    pro, con = _docs(supports), _docs(contradicts)
    detail = f"for: {', '.join(pro)}; against: {', '.join(con)}"
    newest = _newest(pro + con, dates)
    if newest:
        side = "for" if newest in pro else "against"
        detail += f"; most recent source: {newest} ({dates[newest]}, {side})"
    return Signal(Uncertainty.CONFLICTING_SOURCES, detail)


def _partial_uncertainty(best: PassageAssessment) -> list[Signal]:
    signals = []
    for signal in best.signals:
        code = _PARTIAL_CODE_MAP.get(signal.code)
        if code and all(s.code != code for s in signals):
            signals.append(Signal(code, signal.detail))
    return signals


class _Decision(NamedTuple):
    verdict: Verdict
    score: float | None
    uncertainty: tuple[Signal, ...]
    rationale: str


def _not_enough(ranked: list[PassageAssessment], absent_terms: tuple[str, ...]) -> _Decision:
    best_relevance = max((a.relevance for a in ranked), default=0.0)
    signals = []
    if absent_terms:
        signals.append(Signal(Uncertainty.OUT_OF_CORPUS_SCOPE, "terms absent from the corpus: " + ", ".join(absent_terms)))
    other_period = [a for a in ranked if any(s.code == Code.SCOPE_MISMATCH for s in a.signals)]
    if other_period:
        signals.append(Signal(Uncertainty.OTHER_PERIOD_ONLY, other_period[0].signals[0].detail))
    signals.append(Signal(Uncertainty.NO_EVIDENCE, f"best term coverage {best_relevance:.2f}"))
    rationale = "No evidence was found in the corpus that supports or refutes the claim."
    return _Decision(Verdict.NOT_ENOUGH_EVIDENCE, None, tuple(signals), rationale)


def _conflicting(
    supports: list[PassageAssessment], contradicts: list[PassageAssessment], dates: Mapping[str, str | None]
) -> _Decision:
    return _Decision(
        Verdict.CONFLICTING,
        None,
        (_conflict_signal(supports, contradicts, dates),),
        "The sources disagree: some support the claim and others contradict it. Requires human review.",
    )


def _contradicted(contradicts: list[PassageAssessment]) -> _Decision:
    best = contradicts[0]
    weight = max(CONTRADICTION_WEIGHTS.get(s.code, 0.75) for s in best.signals)
    reasons = "; ".join(s.detail for s in best.signals)
    return _Decision(
        Verdict.CONTRADICTED, best.relevance * weight, (), f"The evidence contradicts the claim ({reasons})."
    )


def _supported(supports: list[PassageAssessment], support_min: float) -> _Decision:
    sources = _docs(supports)
    corroboration = CORROBORATION_BONUS * min(len(sources) - 1, MAX_CORROBORATING_SOURCES)
    signals = []
    if len(sources) == 1:
        signals.append(Signal(Uncertainty.SINGLE_SOURCE, f"supported only by {sources[0]}"))
    if supports[0].relevance < support_min + WEAK_MATCH_MARGIN:
        signals.append(Signal(Uncertainty.WEAK_MATCH, f"term coverage {supports[0].relevance:.2f}"))
    return _Decision(
        Verdict.SUPPORTED,
        supports[0].relevance * SUPPORT_SCORE_SCALE + corroboration,
        tuple(signals),
        f"Supported by {len(supports)} passage(s) in {len(sources)} document(s).",
    )


def _partially_supported(partials: list[PassageAssessment]) -> _Decision:
    return _Decision(
        Verdict.PARTIALLY_SUPPORTED,
        partials[0].relevance * PARTIAL_SCORE_SCALE,
        tuple(_partial_uncertainty(partials[0])),
        "The evidence supports only part of the claim, or supports it with less certainty.",
    )


def _inconclusive(ambiguous: list[PassageAssessment]) -> _Decision:
    signals = tuple(dict.fromkeys(s for a in ambiguous for s in a.signals))
    reasons = "; ".join(dict.fromkeys(s.detail for s in signals))
    return _Decision(
        Verdict.INCONCLUSIVE,
        None,
        signals,
        f"There is related evidence, but it does not allow a confident decision ({reasons}). Requires human review.",
    )


def _decide(
    ranked: list[PassageAssessment],
    dates: Mapping[str, str | None],
    absent_terms: tuple[str, ...],
    support_min: float,
    topic_min: float,
) -> _Decision:
    supports = [a for a in ranked if a.stance is Stance.SUPPORTS]
    contradicts = [a for a in ranked if a.stance is Stance.CONTRADICTS]
    partials = [a for a in ranked if a.stance is Stance.PARTIAL]
    ambiguous = [a for a in ranked if a.stance is Stance.AMBIGUOUS]
    # A weakened passage that still states the claimed figure disagrees with a contradiction.
    figure_support = [a for a in partials if any(s.code == Code.NUMBER_MATCH for s in a.signals)]
    # A contradiction the judge declined to assert still disagrees with any support found.
    doubted = [
        a for a in ambiguous
        if a.relevance >= topic_min and any(s.code in _FACTUAL_CONTRADICTION_CODES for s in a.signals)
    ]
    if contradicts and (supports or figure_support):
        return _conflicting(supports or figure_support, contradicts, dates)
    if supports and doubted:
        return _conflicting(supports, doubted, dates)
    if contradicts:
        return _contradicted(contradicts)
    if supports:
        return _supported(supports, support_min)
    if ambiguous:
        # A related passage that cannot be decided outweighs weak partial overlap elsewhere.
        return _inconclusive(ambiguous)
    if partials:
        return _partially_supported(partials)
    return _not_enough(ranked, absent_terms)


def aggregate(
    claim: Claim,
    assessments: Sequence[PassageAssessment],
    dates: Mapping[str, str | None],
    absent_terms: tuple[str, ...] = (),
    claim_hedged: bool = False,
    support_min: float = 0.75,
    max_evidence: int = 4,
    topic_min: float = 0.6,
) -> ClaimResult:
    """Combine passage stances into one verdict, heuristic score and list of uncertainty reasons."""
    ranked = _ranked(assessments)
    supports = [a for a in ranked if a.stance is Stance.SUPPORTS]
    contradicts = [a for a in ranked if a.stance is Stance.CONTRADICTS]
    ambiguous = [a for a in ranked if a.stance is Stance.AMBIGUOUS]
    decision = _decide(ranked, dates, absent_terms, support_min, topic_min)
    hedge = (Signal(Uncertainty.CLAIM_HEDGED, "the claim itself is tentative or opinion-based"),) if claim_hedged else ()
    if supports or contradicts:
        shown = {Stance.SUPPORTS, Stance.CONTRADICTS}
    else:
        shown = {Stance.AMBIGUOUS} if ambiguous else {Stance.PARTIAL}
    return ClaimResult(
        claim=claim,
        verdict=decision.verdict,
        score=None if decision.score is None else round(min(decision.score, MAX_SCORE), 2),
        rationale=decision.rationale,
        evidence=tuple(a for a in ranked if a.stance in shown)[:max_evidence],
        uncertainty=decision.uncertainty + hedge,
        terms_absent_from_corpus=absent_terms,
        examined=tuple(a.passage.passage_id for a in assessments),
        examined_documents=tuple(dict.fromkeys(a.passage.doc_id for a in assessments)),
    )
