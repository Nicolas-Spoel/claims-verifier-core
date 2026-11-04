"""Independent verification of lawyer-authored or external-AI legal text.

Unchanged Core supplies lexical *triage*, not legal validity. Sources can be
explicitly requested from official origins or supplied locally. No legal claim
is upgraded to an autonomous legal-correctness verdict.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Iterable

from .citations import find_references
from .evidence import LegalEvidence
from .grounding import anchor_claim
from .legal_context import context_for_claims, screen_legal_scope, sentence_frames
from .verification import review_claim, to_core_document


REPORT_VERSION = "keepmehonest-legal-es/0.3.1"

# The generic Core may label a standalone courtesy as a claim. Suppress only
# complete courtesy phrases; never suppress a sentence carrying legal content.
_COURTESY_ONLY = re.compile(
    r"(?:muchas\s+)?gracias(?:\s+por\s+(?:su|tu)\s+(?:atenci[oó]n|tiempo))?"
    r"|saludos(?:\s+cordiales)?|atentamente",
    re.IGNORECASE,
)


def _is_courtesy_only(text: str) -> bool:
    return bool(_COURTESY_ONLY.fullmatch(text.strip().rstrip(".! ").strip()))


# Generic Core splits sentences at "art. 24" and "FJ. 1" because they are not
# in its general abbreviation lexicon. Protect ONLY this legal numeric form,
# preserving character positions; restore the original before verification.
_LEGAL_ABBR = re.compile(r"(?<!\w)(art|FJ)\.(?=\s*\d)", re.I)
_LEGAL_MASK = re.compile(r"(?<!\w)(art|FJ)·(?=\s*\d)", re.I)


def _protect_legal_abbreviations(text: str) -> str:
    return _LEGAL_ABBR.sub(lambda m: m.group(1) + "·", text)


def _restore_legal_abbreviations(text: str) -> str:
    return _LEGAL_MASK.sub(lambda m: m.group(1) + ".", text)


def verify_argument(text: str, evidence: Iterable[LegalEvidence], *, attempted_sources: Iterable[dict] = ()) -> dict:
    """Report explicit source accounting, lexical leads, and unresolved legal issues.

    Does not call any network and does not send input to a model. Caller controls
    retrieval separately. Empty evidence means missing coverage, never falsity.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 200_000:
        raise ValueError("nonempty argument <=200000 chars required")
    sources = tuple(evidence)
    if len(sources) > 30 or len({e.evidence_key for e in sources}) != len(sources):
        raise ValueError("at most 30 distinct evidence sections")
    attempted = tuple(attempted_sources)
    result = {
        "schema_version": REPORT_VERSION,
        "product": "KeepMeHonest — Spanish Legal Edition",
        "scope": "independent_documentary_triage",
        "status": "READY_FOR_HUMAN_REVIEW" if sources else "SOURCES_REQUIRED",
        "legal_interpretation": "NOT_ASSESSED",
        "legal_argument_quality": "NOT_ASSESSED",
        "coverage": {
            "corpus_completeness": "UNVERIFIABLE",
            "sources_supplied_or_fetched": len(sources),
            "source_attempts": list(attempted),
            "ordinary_court_search": "NOT_PERFORMED_CENDOJ_DISABLED",
            "general_case_law_search": "NOT_PERFORMED",
            "limitations": [
                "No claim of exhaustive legislation or jurisprudence coverage.",
                "Insufficient/nonretrieved evidence does not establish falsity.",
                "BOE consolidated text is informational; legal temporal applicability unassessed.",
                "Sources identified by user-provided text may be fabricated or incomplete.",
            ],
        },
        "evidence": [
            {"identifier": e.identifier, "source": e.source.value, "section_id": e.section_id,
             "origin": e.origin.value, "evidence_key": e.evidence_key, "sha256": e.sha256,
             "source_url": e.official_url, "version_date": e.version_date,
             "decision_date": e.decision_date, "retrieved_at": e.retrieved_at,
             "authenticity": "UNVERIFIED_BY_INDEPENDENT_CHECK"}
            for e in sources
        ],
        "claims": [],
        "unchecked_segments": [],
    }
    # Use Core for extraction even when no documents have been supplied.
    from claims_verifier.claims import extract_claims
    extracted = extract_claims(_protect_legal_abbreviations(text))
    restored_claims = tuple(replace(c, text=_restore_legal_abbreviations(c.text)) for c in extracted.claims)
    claims = tuple(claim for claim in restored_claims if not _is_courtesy_only(claim.text))
    result["unchecked_segments"] = [
        {"text": _restore_legal_abbreviations(s.text), "reason": s.reason, "factual": s.factual}
        for s in extracted.skipped
    ] + [
        {"text": claim.text, "reason": "standalone_courtesy", "factual": False}
        for claim in restored_claims if _is_courtesy_only(claim.text)
    ]
    # Reconstruct parent sentence context from the same length-preserving
    # input used for Core extraction. A sibling citation is informational only:
    # it is NEVER inherited as documentary evidence by this claim.
    frames = sentence_frames(text, _protect_legal_abbreviations(text))
    contexts = context_for_claims(text, claims, frames)
    core_results = {}
    if sources and claims:
        from claims_verifier import ClaimsVerifier
        report = ClaimsVerifier.from_documents([to_core_document(e) for e in sources]).verify_claims(
            [c.text for c in claims]
        )
        core_results = {i: r for i, r in enumerate(report.results)}
    if not claims:
        result["status"] = "NO_CHECKABLE_CLAIMS"
    for index, claim in enumerate(claims):
        core_result = core_results.get(index)
        citations = [r.value for r in find_references(claim.text)]
        relevant = []
        for source in sources:
            if source.identifier in citations:
                check = review_claim(claim.text, source)
                relevant.append({"evidence_key": source.evidence_key, "identifier_check": check.identifier_check.value,
                                 "quote_check": check.quotation_check.value, "legal_applicability": check.legal_interpretation})
        passages = []
        if core_result:
            id_to_evidence = {f"legal-{e.evidence_key}": e for e in sources}
            for assessed in core_result.evidence:
                evidence_section = id_to_evidence.get(assessed.passage.doc_id)
                passages.append({"passage_id": assessed.passage.passage_id,
                                 "evidence_key": evidence_section.evidence_key if evidence_section else None,
                                 "text_excerpt": assessed.passage.text[:500],
                                 "text_truncated": len(assessed.passage.text) > 500,
                                 "stance": assessed.stance.value,
                                 "signals": [signal.code for signal in assessed.signals]})
        documentary = anchor_claim(claim.text, sources)
        legal_screen = screen_legal_scope(claim.text, contexts[index], documentary, sources, attempted)
        result["claims"].append({
            "claim": claim.text, "citations": citations, "linked_cited_sources": relevant,
            "lexical_verdict": core_result.verdict.value if core_result else "NOT_EVALUATED",
            "lexical_score_is_calibrated": False, "review_status": "HUMAN_REVIEW_REQUIRED",
            "passages_examined": passages,
            "documentary_grounding": documentary,
            "sentence_context": contexts[index],
            "legal_scope_screen": legal_screen,
            "coverage_warning": "No directly linked source for this citation" if citations and not relevant else None,
            "legal_support": "NOT_ASSESSED", "argument_quality": "NOT_ASSESSED",
        })
    provided_ids = {e.identifier for e in sources}
    cited_ids = {r.value for r in find_references(text)}
    result["coverage"]["unresolved_explicit_identifiers"] = sorted(cited_ids - provided_ids)
    result["coverage"]["sources_not_cited_in_argument"] = sorted(provided_ids - cited_ids)
    statuses = [record["documentary_grounding"]["anchor_status"] for record in result["claims"]]
    result["coverage"]["documentary_grounding"] = {
        "claims_examined": len(statuses),
        "claims_with_exact_documentary_quote": statuses.count("DOCUMENTARY_QUOTE_MATCH"),
        "claims_requiring_review": len(statuses),
        "note": "Documentary quotation matching is not legal support or applicability.",
    }
    # This is a deterministic review-indicator count, not a quality score.
    # Absence of a flagged cue is NOT evidence of legal soundness.
    result["coverage"]["m3b_legal_scope_screen"] = {
        "mode": "NON_SEMANTIC_REVIEW_CUES_ONLY",
        "claims_examined": len(result["claims"]),
        "sentence_contexts_mapped": sum(
            c["sentence_context"]["context_status"] == "SENTENCE_MAPPED"
            for c in result["claims"]),
        "claims_with_sibling_citations_not_inherited": sum(
            bool(c["sentence_context"]["sentence_only_identifiers"])
            for c in result["claims"]),
        "claims_with_review_cues": sum(bool(c["legal_scope_screen"]["issues"])
                                      for c in result["claims"]),
        "claims_with_explicit_scope_cues": sum(
            any(issue["code"] in {
                "ABSOLUTE_SCOPE_REQUIRES_REVIEW",
                "ASSERTED_TEMPORAL_SCOPE_UNVERIFIED",
                "CITED_SECTION_CONTAINS_SCOPE_QUALIFIER",
            } for issue in c["legal_scope_screen"]["issues"])
            for c in result["claims"]),
        "legal_support_assessed": 0,
        "source_completeness": "UNVERIFIABLE",
        "note": "No semantic/legal inference. No source or citation is inherited from another clause.",
    }
    return result
