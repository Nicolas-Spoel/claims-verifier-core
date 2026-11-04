"""M4 expert-annotation quality gate; no automatic legal conclusion.

Pending records are not gold. Adjudicated records require two independent
submitted assessments, auditable public-source references and a distinct
adjudicator. This is procedural provenance, not a guarantee of expertise.
"""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

CONTRACT = "keepmehonest-legal-es/m4-human-review/v1"
LABELS = frozenset({"DIRECT_SUPPORT", "PARTIAL_SUPPORT", "NO_SUPPORT",
                    "CONTRADICTED", "CONTEXT_DEPENDENT", "INSUFFICIENT_EVIDENCE"})
DOC_LABELS = frozenset({"EXACT_QUOTE", "INCORRECT_QUOTE", "SOURCE_MISSING", "UNDETERMINED"})


class AnnotationError(ValueError):
    pass


def _digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _date(value: Any) -> bool:
    try:
        return isinstance(value, str) and len(value) == 10 and date.fromisoformat(value) <= date.today()
    except ValueError:
        return False


def validate_annotation(record: Any) -> dict:
    if not isinstance(record, dict) or set(record) != {
        "contract", "case_id", "source_kind", "evidence_sha256", "argument_sha256",
        "contains_confidential_data", "reuse_reviewed", "status", "reviewer_a", "reviewer_b",
        "adjudication"}:
        raise AnnotationError("invalid review schema")
    if record["contract"] != CONTRACT:
        raise AnnotationError("unexpected human review contract")
    if not isinstance(record["case_id"], str) or not record["case_id"].startswith("PUB-"):
        raise AnnotationError("only public legal materials can enter the M4 expert queue")
    if record["source_kind"] not in ("BOE", "TC"):
        raise AnnotationError("CENDOJ and private evidence are out of scope")
    if record["contains_confidential_data"] is not False:
        raise AnnotationError("private or sensitive legal matter data forbidden")
    if record["reuse_reviewed"] is not True:
        raise AnnotationError("public-source reuse rights have not been reviewed")
    if not _digest(record["argument_sha256"]) or not _digest(record["evidence_sha256"]):
        raise AnnotationError("input and evidence text hashes required")
    state = record["status"]
    if state == "PENDING_EXPERT":
        if any(record[k] is not None for k in ("reviewer_a", "reviewer_b", "adjudication")):
            raise AnnotationError("pending record cannot contain final labels")
        return record
    if state != "ADJUDICATED":
        raise AnnotationError("unsupported review status")
    reviewers = []
    for field in ("reviewer_a", "reviewer_b"):
        r = record[field]
        if not isinstance(r, dict) or set(r) != {
            "reviewer_id", "reviewed_on", "documentary_label", "legal_support_label",
            "facts_available", "temporal_applicability_reviewed", "reason", "evidence_locator"}:
            raise AnnotationError(f"{field} has incomplete labels")
        if (not isinstance(r["reviewer_id"], str) or not r["reviewer_id"].strip()
                or not _date(r["reviewed_on"])
                or r["documentary_label"] not in DOC_LABELS
                or r["legal_support_label"] not in LABELS
                or not isinstance(r["facts_available"], bool)
                or not isinstance(r["temporal_applicability_reviewed"], bool)
                or not isinstance(r["reason"], str) or len(r["reason"].strip()) < 30
                or not isinstance(r["evidence_locator"], str) or len(r["evidence_locator"].strip()) < 8):
            raise AnnotationError(f"{field} has invalid/unsupported assessment")
        if not r["facts_available"] and r["legal_support_label"] in ("DIRECT_SUPPORT", "CONTRADICTED"):
            raise AnnotationError(f"{field}: case-specific conclusion without facts")
        reviewers.append(r)
    if reviewers[0]["reviewer_id"] == reviewers[1]["reviewer_id"]:
        raise AnnotationError("two independent reviewers required")
    adjud = record["adjudication"]
    if (not isinstance(adjud, dict) or set(adjud) != {
            "adjudicator_id", "adjudicated_on", "documentary_label", "legal_support_label",
            "conflicts_resolved", "reason", "evidence_locator"}):
        raise AnnotationError("adjudication data incomplete")
    if (not isinstance(adjud["adjudicator_id"], str) or
            adjud["adjudicator_id"] in {r["reviewer_id"] for r in reviewers} or
            not _date(adjud["adjudicated_on"]) or
            adjud["adjudicated_on"] < max(r["reviewed_on"] for r in reviewers) or
            adjud["documentary_label"] not in DOC_LABELS or
            adjud["legal_support_label"] not in LABELS or
            adjud["conflicts_resolved"] is not True or
            not isinstance(adjud["reason"], str) or len(adjud["reason"].strip()) < 30 or
            not isinstance(adjud["evidence_locator"], str) or len(adjud["evidence_locator"].strip()) < 8):
        raise AnnotationError("adjudication requirements not met")
    if (not all(r["facts_available"] for r in reviewers) and
            adjud["legal_support_label"] in ("DIRECT_SUPPORT", "CONTRADICTED")):
        raise AnnotationError("cannot award a case-specific label without available case facts")
    return record


def summarize_review_queue(records: list[dict]) -> dict:
    if not isinstance(records, list) or len(records) > 500:
        raise AnnotationError("invalid review queue")
    seen = set()
    for r in records:
        validate_annotation(r)
        if r["case_id"] in seen:
            raise AnnotationError("duplicate expert case id")
        seen.add(r["case_id"])
    return {"total": len(records), "pending": sum(r["status"] == "PENDING_EXPERT" for r in records),
            "adjudicated": sum(r["status"] == "ADJUDICATED" for r in records),
            "note": "This validates annotation provenance; it does not evaluate legal model accuracy."}


def _unique_pairs(pairs):
    output = {}
    for key, val in pairs:
        if key in output:
            raise AnnotationError(f"duplicate JSON key: {key}")
        output[key] = val
    return output


def main(argv=None) -> int:
    import argparse
    import sys
    parser = argparse.ArgumentParser(description="Validate pending/adjudicated public legal annotation records")
    parser.add_argument("--queue", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.queue.stat().st_size > 1_000_000:
            raise AnnotationError("review file too large")
        records = json.loads(args.queue.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
        print(json.dumps(summarize_review_queue(records), ensure_ascii=False, indent=2))
        return 0
    except (AnnotationError, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"M4 review error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
