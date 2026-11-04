"""M3-A: auditable documentary grounding, deliberately NOT legal entailment.

Only an explicit BOE/ECLI/ROJ identifier, an unambiguous cited section,
section-specific evidence and a verbatim quotation may establish the narrow
DOCUMENTARY_QUOTE_MATCH status. That status never asserts that a proposition
is lawful, applicable, complete, authoritative or even semantically supported.

No network, LLM, legal inference, implicit 'art. 24 CE' identifier resolution,
or CENDOJ access. Human review remains mandatory for every claim.
"""
from __future__ import annotations

from hashlib import sha256
import re
from typing import Iterable
import unicodedata

from .citations import find_references, ReferenceKind
from .evidence import LegalEvidence, SourceKind
from .verification import QuoteCheck, verify_quote

CONTRACT = "legal-es/m3a-documentary-anchor/v1"

# Accept only numeric full-article / FJ references. Subsections, ordinal words,
# paragraph ranges, and multi-source mapping require human review.
_ARTICLE = re.compile(r"(?<!\w)(?:art[ií]culo|art\.)\s*(\d{1,4})(\.\d+)?(?!\d)", re.I)
_FJ = re.compile(r"(?<!\w)(?:FJ\.?|fundamento\s+jur[ií]dico)\s*(?:n[.º°]\s*)?(\d{1,3})(?!\d)", re.I)
_FALLO = re.compile(r"\bfallo\b", re.I)
_QUOTE = re.compile(r"«([^«»]{0,4000})»|“([^“”]{0,4000})”|\"([^\"\n]{0,4000})\"")


def _digest(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _canon_section(source: SourceKind, section: str) -> str | None:
    if source is SourceKind.BOE:
        match = re.fullmatch(r"(?:a|art(?:[ií]culo)?\s*)0*(\d{1,4})", section.strip(), re.I)
        return f"a{int(match.group(1))}" if match else None
    if source in (SourceKind.TC, SourceKind.ORDINARY_COURTS):
        if section.strip().upper() == "FALLO":
            return "FALLO"
        match = re.fullmatch(r"FJ\s*0*(\d{1,3})", section.strip(), re.I)
        return f"FJ{int(match.group(1))}" if match else None
    return None


def _claimed_section(text: str, source: SourceKind) -> tuple[str | None, str | None]:
    if source is SourceKind.BOE:
        matches = list(_ARTICLE.finditer(text))
        sections = {f"a{int(m.group(1))}" for m in matches}
        if any(m.group(2) for m in matches):
            return None, "SUBARTICLE_SCOPE_UNSUPPORTED"
    else:
        matches = list(_FJ.finditer(text))
        sections = {f"FJ{int(m.group(1))}" for m in matches}
        if _FALLO.search(text):
            sections.add("FALLO")
    if not sections:
        return None, "SECTION_NOT_EXPLICITLY_IDENTIFIED"
    if len(sections) > 1:
        return None, "MULTIPLE_SECTIONS_AMBIGUOUS"
    return sections.pop(), None


def _quoted_passage(text: str) -> tuple[str | None, str | None]:
    found = [next(g for g in m.groups() if g is not None) for m in _QUOTE.finditer(text)]
    if not found:
        return None, "NO_EXPLICIT_QUOTATION"
    if len(found) != 1:
        return None, "MULTIPLE_QUOTATIONS_AMBIGUOUS"
    quote = found[0]
    normalized = " ".join(unicodedata.normalize("NFC", quote).split())
    if len(normalized) < 12:
        return None, "QUOTATION_TOO_SHORT"
    if any(marker in quote for marker in ("…", "...", "[…]", "[...]")):
        return None, "QUOTATION_HAS_OMISSIONS"
    return quote, None


def _find_source_span(text: str, quote: str) -> list[int] | None:
    """Best-effort raw offsets; None if only Unicode normalization matches."""
    parts = quote.split()
    if not parts:
        return None
    pattern = r"\s+".join(re.escape(part) for part in parts)
    match = re.search(pattern, text)
    return [match.start(), match.end()] if match else None


def anchor_claim(claim: str, evidence: Iterable[LegalEvidence]) -> dict:
    """Build one fail-closed, nonsemantic provenance link for a claim.

    Status DOCUMENTARY_QUOTE_MATCH is *not* a legal-support finding. User
    supplied evidence is never promoted to an official source by this method.
    """
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("nonempty claim required")
    sources = tuple(evidence)
    if len(sources) > 30:
        raise ValueError("at most 30 evidence sections")
    refs = find_references(claim)
    answer: dict = {
        "contract": CONTRACT,
        "claim_sha256": _digest(claim),
        "anchor_status": "UNRESOLVED",
        "source_identifier": None,
        "cited_section_id": None,
        "evidence_key": None,
        "evidence_sha256": None,
        "source_origin": None,
        "quoted_passage_sha256": None,
        "quoted_passage_characters": None,
        "evidence_char_span": None,
        "quote_match_method": None,
        "review_flags": [],
        "legal_support": "NOT_ASSESSED",
        "legal_applicability": "NOT_ASSESSED",
        "argument_quality": "NOT_ASSESSED",
        "requires_human_review": True,
    }

    if not refs:
        answer["anchor_status"] = "NO_EXPLICIT_IDENTIFIER"
        return answer
    # A claim with multiple citations cannot be automatically mapped to
    # which section supports which proposition, even if both sources exist.
    if len(refs) != 1:
        answer["anchor_status"] = "MULTIPLE_IDENTIFIERS_REQUIRE_MAPPING"
        return answer
    ref = refs[0]
    answer["source_identifier"] = ref.value
    if ref.kind is ReferenceKind.BOE:
        kind = SourceKind.BOE
        answer["review_flags"].append("BOE_CONSOLIDATED_TEXT_IS_INFORMATIONAL")
        answer["review_flags"].append("BOE_TEMPORAL_APPLICABILITY_UNCHECKED")
    elif ref.kind is ReferenceKind.ECLI and ref.value.startswith("ECLI:ES:TC:"):
        kind = SourceKind.TC
        answer["review_flags"].append("TC_RATIO_AND_PROCEDURAL_CONTEXT_UNCHECKED")
    elif ref.kind is ReferenceKind.ROJ:
        kind = SourceKind.ORDINARY_COURTS
        answer["review_flags"].append("CENDOJ_AUTOMATED_RETRIEVAL_DISABLED")
    else:
        answer["anchor_status"] = "SOURCE_KIND_UNSUPPORTED"
        return answer

    section, section_error = _claimed_section(claim, kind)
    if section_error:
        answer["anchor_status"] = section_error
        return answer
    answer["cited_section_id"] = section

    candidate = [e for e in sources if e.identifier == ref.value and e.source is kind
                 and _canon_section(kind, e.section_id) == section]
    if not candidate:
        answer["anchor_status"] = "CITED_SECTION_NOT_SUPPLIED"
        return answer
    if len(candidate) != 1:
        answer["anchor_status"] = "MULTIPLE_EVIDENCE_VERSIONS_AMBIGUOUS"
        return answer
    found = candidate[0]
    answer["evidence_key"] = found.evidence_key
    answer["evidence_sha256"] = found.sha256
    answer["source_origin"] = found.origin.value
    answer["review_flags"].append("SOURCE_AUTHENTICITY_NOT_INDEPENDENTLY_VERIFIED")

    quote, quote_error = _quoted_passage(claim)
    if quote_error:
        answer["anchor_status"] = "SECTION_LOCATED_" + quote_error
        return answer
    answer["quoted_passage_sha256"] = _digest(quote)
    answer["quoted_passage_characters"] = len(quote)
    if verify_quote(found, quote) is not QuoteCheck.MATCH:
        answer["anchor_status"] = "QUOTED_PASSAGE_NOT_FOUND_IN_CITED_SECTION"
        return answer
    answer["anchor_status"] = "DOCUMENTARY_QUOTE_MATCH"
    answer["quote_match_method"] = "LITERAL_NFC_WHITESPACE_ONLY"
    answer["evidence_char_span"] = _find_source_span(found.text, quote)
    answer["review_flags"].append("QUOTE_DOES_NOT_ESTABLISH_LEGAL_ENTAILMENT")
    answer["review_flags"].append("SURROUNDING_CONTEXT_AND_EXCEPTIONS_NOT_ASSESSED")
    return answer
