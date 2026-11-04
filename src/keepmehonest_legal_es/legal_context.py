"""M3-B: non-semantic context lineage and legal-scope review cues.

Context inherited from a sentence is NEVER evidence inherited by a clause.
Keywords are review triggers only, not legal findings. No external access,
models, legal interpretation or ordinary-court retrieval.
"""
from __future__ import annotations

from hashlib import sha256
import re
from typing import Iterable

from .citations import find_references
from .evidence import LegalEvidence, SourceKind

CONTRACT = "legal-es/m3b-context-and-scope-screen/v1"

# Keyword detection is purposely narrow. Avoid cues inside quoted material
# when examining the lawyer's own generalization; literal quote authenticity
# is already handled independently by documentary grounding.
_QUOTES = re.compile(r'«[^»]*»|“[^”]*”|"[^"\n]*"')
_ABSOLUTES = re.compile(
    r"\b(?:siempre|nunca|autom[aá]ticamente|inevitablemente|"
    r"sin\s+excepci[oó]n|en\s+(?:todos|cualesquiera)\s+los\s+casos|"
    r"en\s+cualquier\s+caso|bajo\s+ninguna\s+circunstancia)\b", re.I,
)
_TEMPORAL_CLAIM = re.compile(
    r"\b(?:vigent[ea]s?|derogad[oa]s?|retroactiv[oa]s?|"
    r"entr[oó]\s+en\s+vigor|en\s+vigor|en\s+(?:la\s+)?fecha\s+de|"
    r"a\s+fecha\s+de|aplicab(?:le|ilidad)\s+(?:desde|hasta|en))\b", re.I,
)
_CONDITIONS = re.compile(
    r"\b(?:salvo|excepto|sin\s+perjuicio\s+de|a\s+menos\s+que|"
    r"siempre\s+que|a\s+condici[oó]n\s+de|no\s+obstante|"
    r"[uú]nicamente\s+cuando|en\s+los\s+casos\s+en\s+que)\b", re.I,
)


def _hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _refs(text: str) -> list[str]:
    return sorted({r.value for r in find_references(text)})


def sentence_frames(original: str, protected: str) -> tuple[tuple[int, int], ...]:
    """Replay Core's sentence boundaries preserving original char offsets.

    `protected` is length-preserving and changes only `art.`/`FJ.` before
    numerals, exactly as M3-A extraction does. No sentence guess on failure.
    """
    if len(original) != len(protected):
        raise ValueError("sentence mask must preserve character offsets")
    from claims_verifier.text import split_sentences

    spans: list[tuple[int, int]] = []
    pos = 0
    for line in protected.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        spans.extend(split_sentences(content, pos))
        pos += len(line)
    return tuple(spans)


def context_for_claims(original: str, claims: tuple, frames: tuple[tuple[int, int], ...]) -> list[dict]:
    """Auditable sentence and sibling links; never transfer an anchor."""
    assignment: list[int | None] = []
    for claim in claims:
        a, b = claim.char_start, claim.char_end
        matches = [i for i, (start, end) in enumerate(frames)
                   if a is not None and b is not None and start <= a <= b <= end]
        assignment.append(matches[0] if len(matches) == 1 else None)

    contexts = []
    for index, claim in enumerate(claims):
        frame = assignment[index]
        direct_refs = _refs(claim.text)
        base = {
            "contract": CONTRACT,
            "context_status": "SENTENCE_MAPPED" if frame is not None else "SPAN_UNRESOLVED",
            "claim_char_span": [claim.char_start, claim.char_end],
            "sentence_char_span": None,
            "sentence_sha256": None,
            "sentence_text": None,
            "sibling_claim_numbers": [],
            "direct_identifiers": direct_refs,
            "sentence_identifiers": [],
            "sentence_only_identifiers": [],
            "inherit_documentary_anchor": False,
        }
        if frame is not None:
            start, end = frames[frame]
            sentence = original[start:end]
            full_refs = _refs(sentence)
            base.update({
                "sentence_char_span": [start, end],
                "sentence_sha256": _hash(sentence),
                "sentence_text": sentence,
                "sibling_claim_numbers": [j + 1 for j, other in enumerate(assignment)
                                          if other == frame and j != index],
                "sentence_identifiers": full_refs,
                "sentence_only_identifiers": [r for r in full_refs if r not in direct_refs],
            })
        contexts.append(base)
    return contexts


def _issue(code: str, basis: str) -> dict:
    return {"code": code, "basis": basis}


def screen_legal_scope(claim: str, context: dict, anchor: dict,
                       evidence: Iterable[LegalEvidence], attempted_sources: Iterable[dict] = ()) -> dict:
    """Produce limitations, never a semantic yes/no about the legal proposition.

    Evidence must be linked by M3-A's exact key (identifier + section).
    A same-sentence citation, Core lexical score, or matching quote cannot
    make an independent legal-support determination.
    """
    sources = tuple(evidence)
    attempts = tuple(attempted_sources)
    matched = [s for s in sources if anchor.get("evidence_key") == s.evidence_key]
    source = matched[0] if len(matched) == 1 else None
    issues = []

    def flag(code: str, basis: str) -> None:
        if code not in {i["code"] for i in issues}:
            issues.append(_issue(code, basis))

    if context.get("context_status") != "SENTENCE_MAPPED":
        flag("SENTENCE_CONTEXT_UNRESOLVED", "EXTRACTION_SPANS")
    if context.get("sentence_only_identifiers"):
        flag("OTHER_CLAUSE_CITATION_NOT_INHERITED", "SENTENCE_CONTEXT")
    if anchor.get("anchor_status") != "DOCUMENTARY_QUOTE_MATCH":
        flag("DOCUMENTARY_SUPPORT_NOT_ESTABLISHED", "M3A_ANCHOR")
    else:
        flag("EXACT_QUOTE_DOES_NOT_PROVE_PROPOSITION", "M3A_ANCHOR")
    if not source:
        flag("EXACT_SOURCE_SECTION_NOT_LINKED", "M3A_ANCHOR")

    own_text = _QUOTES.sub(" ", claim)
    if _ABSOLUTES.search(own_text):
        flag("ABSOLUTE_SCOPE_REQUIRES_REVIEW", "NONQUOTED_CLAIM_TEXT")
    if _TEMPORAL_CLAIM.search(own_text):
        flag("ASSERTED_TEMPORAL_SCOPE_UNVERIFIED", "NONQUOTED_CLAIM_TEXT")

    source_scope = None
    if source is not None:
        flag("EVIDENCE_AUTHENTICITY_NOT_INDEPENDENTLY_VERIFIED", "EVIDENCE_PROVENANCE")
        if source.source is SourceKind.BOE:
            flag("BOE_VIGENCIA_AND_APPLICABILITY_NOT_ESTABLISHED", "BOE_VERSION_METADATA")
            attempts_for_source = [a for a in attempts if a.get("source") == "BOE"
                                   and a.get("identifier") == source.identifier
                                   and a.get("status") == "FETCHED"]
            as_of_dates = sorted({a.get("requested_as_of") for a in attempts_for_source
                                  if isinstance(a.get("requested_as_of"), str)})
            source_scope = {"source": "BOE", "evidence_key": source.evidence_key,
                            "version_date": source.version_date,
                            "request_date_candidates": as_of_dates,
                            "request_date_scope": "IDENTIFIER_LEVEL_NOT_VERIFIED_FOR_SECTION",
                            "temporal_applicability": "NOT_ASSESSED"}
        elif source.source is SourceKind.TC:
            flag("TC_RATIO_PROCEDURAL_FIT_AND_LATER_CASES_UNCHECKED", "TC_EVIDENCE")
            source_scope = {"source": "TC", "evidence_key": source.evidence_key,
                            "decision_date": source.decision_date,
                            "temporal_applicability": "NOT_ASSESSED"}
        else:
            flag("ORDINARY_COURTS_COVERAGE_NOT_SEARCHED", "EVIDENCE_ORIGIN")
            source_scope = {"source": "ORDINARY_COURTS", "evidence_key": source.evidence_key,
                            "temporal_applicability": "NOT_ASSESSED"}
        if _CONDITIONS.search(source.text):
            flag("CITED_SECTION_CONTAINS_SCOPE_QUALIFIER", "EVIDENCE_SECTION_TEXT")

    return {
        "contract": CONTRACT,
        "screen_status": "HUMAN_LEGAL_REVIEW_REQUIRED",
        "legal_support": "NOT_ASSESSED",
        "legal_applicability": "NOT_ASSESSED",
        "argument_quality": "NOT_ASSESSED",
        "issues": issues,
        "linked_source_temporal_metadata": source_scope,
        "not_checked": ["legal_entailment", "exceptions_applicability", "hierarchy_or_jurisdiction",
                        "procedural_facts", "later_amendments_or_cases", "completeness"],
        "requires_human_review": True,
    }
