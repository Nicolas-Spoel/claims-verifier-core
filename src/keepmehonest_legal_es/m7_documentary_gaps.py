"""M7-B: offline, text-free documentary gap and snapshot-divergence review.

M7-A remains the authority for M3 report consistency. M7-B adds *documentary*
readiness signals and detects differing supplied snapshots of the SAME
identified source section. This never assesses legal entailment, correctness,
applicability, authority, precedential weight, or substantive contradictions.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys

from .evidence import LegalEvidence, Origin, SourceKind
from .grounding import _canon_section
from .independent import verify_argument
from .m7_review_gate import (
    MAX_EVIDENCE_BYTES, MAX_TEXT_BYTES, ReviewGateError,
    _no_duplicate_keys, _read_file, _write_private, assess_report,
)

CONTRACT = "keepmehonest-legal-es/m7b-documentary-gaps/v1"

_WORKFLOW = {
    "LITERAL_QUOTE_LOCATED_NOT_LEGAL_SUPPORT": "QUOTE_LOCATED_DOCUMENTARY_ONLY",
    "QUOTATION_DISCREPANCY_REQUIRES_REVIEW": "QUOTATION_NOT_LOCATED_REVIEW",
    "CITED_SECTION_WITHOUT_VERIFIABLE_QUOTE": "SECTION_IDENTIFIED_QUOTE_UNVERIFIED",
    "CITATION_OR_SECTION_UNRESOLVED": "CITATION_OR_SECTION_MISSING_OR_AMBIGUOUS",
}

_SCOPE_CODES = frozenset({
    "ABSOLUTE_SCOPE_REQUIRES_REVIEW", "ASSERTED_TEMPORAL_SCOPE_UNVERIFIED",
    "CITED_SECTION_CONTAINS_SCOPE_QUALIFIER",
})


def _sha_json(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return sha256(canonical).hexdigest()


def _section_groups(entries: list[dict]) -> tuple[dict, list[dict]]:
    """Classify input *snapshots*, not truth or legal contradictions.

    Never emit identifiers, dates, source URLs or source text. A date is only
    source-supplied metadata; it is not an independently verified as-of date.
    """
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in entries:
        source = SourceKind(row["source"])
        canonical = _canon_section(source, row["section_id"])
        if canonical is None:
            raise ReviewGateError("unsupported section in evidence inventory")
        dated = row.get("version_date") if source == SourceKind.BOE else row.get("decision_date")
        if dated is not None:
            if type(dated) is not str or len(dated) != 10:
                raise ReviewGateError("invalid evidence snapshot date")
            try:
                date.fromisoformat(dated)
            except ValueError as exc:
                raise ReviewGateError("invalid evidence snapshot date") from exc
        groups.setdefault((row["source"], row["identifier"], canonical), []).append(row)

    # Only groups with different text hashes represent competing *snapshots*;
    # repeated identical bytes do not amount to divergence.
    divergent = []
    lookup: dict[tuple[str, str, str], dict] = {}
    for key, group in sorted(groups.items()):
        distinct = {r["sha256"] for r in group}
        if len(distinct) < 2:
            continue
        source = SourceKind(key[0])
        dates = [r.get("version_date") if source == SourceKind.BOE else r.get("decision_date")
                 for r in group]
        missing_date = any(d is None for d in dates)
        same_dated_snapshot = not missing_date and len(set(dates)) == 1
        group_row = {
            "group_number": len(divergent) + 1,
            "source_type": source.value,
            "snapshot_count": len(group),
            "distinct_content_hashes": len(distinct),
            "distinct_source_dates": len(set(d for d in dates if d is not None)),
            "date_metadata_missing": missing_date,
            "documentary_tension_code": (
                "SAME_DATE_DIFFERENT_SECTION_BYTES" if same_dated_snapshot
                else "MULTIPLE_OR_UNDATED_SECTION_SNAPSHOTS"
            ),
            "legal_contradiction_established": False,
        }
        divergent.append(group_row)
        lookup[key] = group_row
    return lookup, divergent


def assess_documentary_gaps(report: dict) -> dict:
    """Assess a freshly produced M3 report after M7-A consistency checks.

    In-memory input may be forged; neither M7-A nor M7-B independently
    authenticates downloaded source bytes or user-supplied snapshot dates.
    """
    gate = assess_report(report)  # Fail closed on M3 internal inconsistencies.
    groups, divergent = _section_groups(report["evidence"])
    rows = []
    counts = {
        "literal_quotes_located_documentary_only": 0,
        "unlocated_quotations": 0,
        "section_without_verifiable_quote": 0,
        "unresolved_citations_or_sections": 0,
        "claims_with_competing_source_section_snapshots": 0,
        "claims_with_scope_review_cues": 0,
        "claims_with_sentence_only_citation": 0,
        "claims_with_missing_date_metadata": 0,
    }
    count_field = {
        "QUOTE_LOCATED_DOCUMENTARY_ONLY": "literal_quotes_located_documentary_only",
        "QUOTATION_NOT_LOCATED_REVIEW": "unlocated_quotations",
        "SECTION_IDENTIFIED_QUOTE_UNVERIFIED": "section_without_verifiable_quote",
        "CITATION_OR_SECTION_MISSING_OR_AMBIGUOUS": "unresolved_citations_or_sections",
    }
    inventory = {e["evidence_key"]: e for e in report["evidence"]}

    for claim, prior in zip(report["claims"], gate["queue"], strict=True):
        stage = _WORKFLOW[prior["documentary_workflow"]]
        counts[count_field[stage]] += 1
        grounding = claim["documentary_grounding"]
        codes = set()
        if stage == "QUOTE_LOCATED_DOCUMENTARY_ONLY":
            codes.add("LITERAL_MATCH_DOES_NOT_PROVE_PROPOSITION")
        elif stage == "QUOTATION_NOT_LOCATED_REVIEW":
            codes.add("QUOTATION_DISCREPANCY_NOT_LEGAL_FALSITY")
        elif stage == "SECTION_IDENTIFIED_QUOTE_UNVERIFIED":
            codes.add("SECTION_RETRIEVED_NOT_SUBSTANTIVE_SUPPORT")
        else:
            codes.add("SOURCE_OR_SECTION_COVERAGE_GAP_NOT_LEGAL_FALSITY")

        evidence_key = prior["linked_evidence_key"]
        if evidence_key is not None:
            linked = inventory[evidence_key]
            source, identifier = linked["source"], linked["identifier"]
            section = _canon_section(SourceKind(source), linked["section_id"])
            version = linked.get("version_date") if source == "BOE" else linked.get("decision_date")
            if version is None:
                codes.add("SOURCE_DATE_METADATA_MISSING")
                counts["claims_with_missing_date_metadata"] += 1
        else:
            identifier = grounding.get("source_identifier")
            section = grounding.get("cited_section_id")
            source = "BOE" if type(identifier) is str and identifier.startswith("BOE-A-") else (
                "TC" if type(identifier) is str and identifier.startswith("ECLI:ES:TC:") else None
            )
        match = groups.get((source, identifier, section))
        if match is not None:
            codes.add(match["documentary_tension_code"])
            counts["claims_with_competing_source_section_snapshots"] += 1
        if source == "BOE":
            codes.add("BOE_TEMPORAL_APPLICABILITY_NOT_ESTABLISHED")
        elif source == "TC":
            codes.add("TC_DOCTRINAL_CONTEXT_NOT_ESTABLISHED")
        if prior["sibling_citation_not_inherited"]:
            codes.add("ADJACENT_CLAUSE_CITATION_NOT_INHERITED")
            counts["claims_with_sentence_only_citation"] += 1
        if set(prior["scope_review_signal_codes"]) & _SCOPE_CODES:
            codes.add("SCOPE_CONDITIONS_REQUIRE_HUMAN_REVIEW")
            counts["claims_with_scope_review_cues"] += 1
        codes.add("SOURCE_AUTHENTICITY_NOT_INDEPENDENTLY_VERIFIED")
        rows.append({
            "claim_number": prior["claim_number"],
            "claim_sha256": prior["claim_sha256"],
            "documentary_review_stage": stage,
            "linked_evidence_key": evidence_key,
            "competing_section_group_number": match["group_number"] if match else None,
            "review_reason_codes": sorted(codes),
            "human_review_required": True,
            "documentary_sufficiency": "NOT_DETERMINED",
            "legal_support": "NOT_ASSESSED",
            "legal_applicability": "NOT_ASSESSED",
            "legal_contradiction_established": False,
            "legal_truth_verdict": "NOT_PRODUCED",
        })

    return {
        "contract": CONTRACT,
        "mode": "OFFLINE_DOCUMENTARY_GAPS_AND_SNAPSHOT_DIVERGENCE_NOT_LEGAL_VERDICT",
        "m3_report_sha256": gate["input_m3_report_sha256"],
        "m7a_review_sha256": _sha_json(gate),
        "claims_queued": len(rows),
        "evidence_sections_listed": len(inventory),
        "unchecked_segments_count": gate["unchecked_segments_count"],
        "counts": counts,
        "competing_section_snapshot_groups": divergent,
        "queue": rows,
        "coverage_exhaustive": False,
        "source_authenticity_independently_verified": False,
        "legal_support_assessed": False,
        "legal_applicability": "NOT_ASSESSED",
        "documentary_sufficiency_measured": False,
        "legal_accuracy_measured": False,
        "expert_gold_cases": 0,
        "rights_cleared": False,
        "network_used": False,
        "client_text_in_report": False,
        "source_text_in_report": False,
        "limitations": [
            "Different hashes for one cited section are competing snapshots, not proven legal contradictions.",
            "Source version dates come from input metadata and have not been authenticated by this audit.",
            "A literal quote or complete documentary trace cannot establish legal entailment or sufficiency.",
            "Missing sources, discrepancies, or unsupported claims do not establish falsity.",
            "Context, exceptions, applicability, later jurisprudence and substantive legal quality are unassessed.",
            "The available source universe is non-exhaustive; CENDOJ automated access is disabled.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M7-B offline documentary gaps, not legal support")
    parser.add_argument("--text-file", required=True, type=Path)
    parser.add_argument("--evidence-json", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        text = _read_file(args.text_file, MAX_TEXT_BYTES).decode("utf-8")
        evidence = []
        if args.evidence_json is not None:
            records = json.loads(_read_file(args.evidence_json, MAX_EVIDENCE_BYTES).decode("utf-8"),
                                 object_pairs_hook=_no_duplicate_keys)
            if not isinstance(records, list) or len(records) > 30:
                raise ReviewGateError("local evidence must have <=30 entries")
            for record in records:
                if not isinstance(record, dict):
                    raise ReviewGateError("local evidence entry must be an object")
                allowed = {"source", "identifier", "section_id", "text", "official_url", "title",
                           "origin", "decision_date", "version_date", "retrieved_at"}
                if set(record) - allowed:
                    raise ReviewGateError("unexpected local evidence field")
                fields = dict(record)
                fields["source"] = SourceKind(fields["source"])
                fields["origin"] = Origin.USER_SUPPLIED
                evidence.append(LegalEvidence(**fields))
        result = assess_documentary_gaps(verify_argument(text, evidence))
        _write_private(args.output, result)
        print(json.dumps({
            "mode": result["mode"], "claims_queued": result["claims_queued"],
            "competing_section_groups": len(result["competing_section_snapshot_groups"]),
            "legal_support_assessed": False, "output_created": True,
        }, sort_keys=True))
        return 0
    except (OSError, TypeError, ValueError, UnicodeError, KeyError) as exc:
        print(f"M7-B review error ({type(exc).__name__}); no legal verdict produced", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
