"""Conservative verification layers; NEVER produce a legal-truth verdict."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import unicodedata

from .citations import find_references
from .evidence import LegalEvidence, Origin


class CitationCheck(str, Enum):
    MATCH = "MATCH"
    MISSING = "MISSING"
    DIFFERENT = "DIFFERENT"
    AMBIGUOUS = "AMBIGUOUS"


class QuoteCheck(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_REQUESTED = "NOT_REQUESTED"


@dataclass(frozen=True)
class LegalReview:
    identifier_check: CitationCheck
    quotation_check: QuoteCheck
    evidence_key: str
    evidence_sha256: str
    source_origin: Origin
    core_lexical_verdict: str | None
    status: str
    authenticity: str = "NOT_ASSESSED"
    temporal_applicability: str = "NOT_ASSESSED"
    legal_interpretation: str = "NOT_ASSESSED"


def _literal_normalize(text: str) -> str:
    # Normalize line wrapping, NOT accents, negations, punctuation or lexical meaning.
    return " ".join(unicodedata.normalize("NFC", text).split())


def verify_quote(evidence: LegalEvidence, quote: str | None) -> QuoteCheck:
    if quote is None:
        return QuoteCheck.NOT_REQUESTED
    if not isinstance(quote, str) or len(_literal_normalize(quote)) < 12:
        return QuoteCheck.MISMATCH
    needle, haystack = _literal_normalize(quote), _literal_normalize(evidence.text)
    return QuoteCheck.MATCH if needle in haystack else QuoteCheck.MISMATCH


def to_core_document(evidence: LegalEvidence):
    """Adapter for the unchanged claims_verifier 0.1.1 public API."""
    from claims_verifier import make_document

    return make_document(
        doc_id=f"legal-{evidence.evidence_key}",
        text=evidence.text,
        source_path=evidence.official_url,
        title=evidence.title,
        metadata={
            "source": evidence.source.value,
            "identifier": evidence.identifier,
            "section_id": evidence.section_id,
            "origin": evidence.origin.value,
            "official_url": evidence.official_url,
            "evidence_sha256": evidence.sha256,
            "date": evidence.date or "",
        },
    )


def review_claim(claim: str, evidence: LegalEvidence, *, quote: str | None = None, run_core: bool = False) -> LegalReview:
    """Check identifier and literal quote; optional lexical verdict is NOT legal verification.

    Each call handles exactly one evidence section. Missing citations or mismatch
    block any positive automated conclusion. A positive check only allows human review.
    """
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("claim is required")
    refs = find_references(claim)
    own = evidence.identifier
    unique_refs = {r.value for r in refs}
    if len(unique_refs) > 1:
        identifier_check = CitationCheck.AMBIGUOUS
    elif own in unique_refs:
        identifier_check = CitationCheck.MATCH
    elif refs:
        identifier_check = CitationCheck.DIFFERENT
    else:
        identifier_check = CitationCheck.MISSING
    quotation_check = verify_quote(evidence, quote)
    lexical: str | None = None
    if run_core:
        from claims_verifier import ClaimsVerifier
        report = ClaimsVerifier.from_documents([to_core_document(evidence)]).verify_claims([claim])
        lexical = report.results[0].verdict.value
    blocked = identifier_check != CitationCheck.MATCH or quotation_check == QuoteCheck.MISMATCH
    return LegalReview(
        identifier_check=identifier_check,
        quotation_check=quotation_check,
        evidence_key=evidence.evidence_key,
        evidence_sha256=evidence.sha256,
        source_origin=evidence.origin,
        core_lexical_verdict=lexical,
        status="BLOCKED" if blocked else "REVIEW_REQUIRED",
    )
