"""Independent verification of lawyer-authored or external-AI legal text.

Unchanged Core supplies lexical *triage*, not legal validity. Sources can be
explicitly requested from official origins or supplied locally. No legal claim
is upgraded to an autonomous legal-correctness verdict.
"""
from __future__ import annotations

import re
from typing import Iterable

from .citations import find_references
from .evidence import LegalEvidence
from .verification import review_claim, to_core_document


REPORT_VERSION = "keepmehonest-legal-es/0.2.0"

# The generic Core may label a standalone courtesy as a claim. Suppress only
# complete courtesy phrases; never suppress a sentence carrying legal content.
_COURTESY_ONLY = re.compile(
    r"(?:muchas\s+)?gracias(?:\s+por\s+(?:su|tu)\s+(?:atenci[oó]n|tiempo))?"
    r"|saludos(?:\s+cordiales)?|atentamente",
    re.IGNORECASE,
)


def _is_courtesy_only(text: str) -> bool:
    return bool(_COURTESY_ONLY.fullmatch(text.strip().rstrip(".! ").strip()))


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
    extracted = extract_claims(text)
    claims = tuple(claim for claim in extracted.claims if not _is_courtesy_only(claim.text))
    result["unchecked_segments"] = [
        {"text": s.text, "reason": s.reason, "factual": s.factual} for s in extracted.skipped
    ] + [
        {"text": claim.text, "reason": "standalone_courtesy", "factual": False}
        for claim in extracted.claims if _is_courtesy_only(claim.text)
    ]
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
        result["claims"].append({
            "claim": claim.text, "citations": citations, "linked_cited_sources": relevant,
            "lexical_verdict": core_result.verdict.value if core_result else "NOT_EVALUATED",
            "lexical_score_is_calibrated": False, "review_status": "HUMAN_REVIEW_REQUIRED",
            "passages_examined": passages,
            "coverage_warning": "No directly linked source for this citation" if citations and not relevant else None,
            "legal_support": "NOT_ASSESSED", "argument_quality": "NOT_ASSESSED",
        })
    provided_ids = {e.identifier for e in sources}
    cited_ids = {r.value for r in find_references(text)}
    result["coverage"]["unresolved_explicit_identifiers"] = sorted(cited_ids - provided_ids)
    result["coverage"]["sources_not_cited_in_argument"] = sorted(provided_ids - cited_ids)
    return result
