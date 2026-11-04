"""M5-C: offline, privacy-preserving expert review handoff and structural audit.

Never generates a legal label. M4 adjudicated schema is assembled *only* from
human-entered review files. Passing is structural, not proof of real people,
legal expertise, independence or correctness; no expert gold is minted here.
"""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any

from .m4_review import CONTRACT as M4_CONTRACT, AnnotationError, validate_annotation
from .m5_queue import _read_json, validate_candidates, _validate_source

CONTRACT = "keepmehonest-legal-es/m5-expert-review/v1"
REVIEW_CONTRACT = "keepmehonest-legal-es/m5-independent-review/v1"
ADJUDICATION_CONTRACT = "keepmehonest-legal-es/m5-adjudication/v1"
MAX_CASES = 50
MAX_INPUT_BYTES = 1_000_000
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
REVIEW_FIELDS = frozenset({"case_id", "case_sha256", "reviewer_id", "reviewed_on", "documentary_label",
                           "legal_support_label", "facts_available", "temporal_applicability_reviewed",
                           "reason", "evidence_locator"})
ADJ_FIELDS = frozenset({"case_id", "case_sha256", "adjudicator_id", "adjudicated_on", "documentary_label",
                        "legal_support_label", "conflicts_resolved", "reason", "evidence_locator"})


class ReviewError(ValueError):
    """Invalid packet, roles, hashes or procedural annotation."""


def _canonical(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _sha(obj: Any) -> str:
    return sha256(_canonical(obj)).hexdigest()


def _hex(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _safe_json(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ReviewError("missing, unsafe or oversized JSON input")
    return _read_json(path, max_bytes=MAX_INPUT_BYTES)


def _private_output(dest: Path):
    if not dest.is_absolute() or dest.exists() or dest.is_symlink() or not dest.parent.is_dir() or dest.parent.is_symlink():
        raise ReviewError("new absolute output directory under an existing safe parent required")
    if not (dest.parent.stat().st_mode & stat.S_IWUSR):
        raise ReviewError("parent directory not writable by owner")


def _atomic_private_dir(dest: Path, entries: dict[str, Any]) -> None:
    _private_output(dest)
    tmp = Path(tempfile.mkdtemp(prefix=f".{dest.name}.tmp-", dir=dest.parent))
    try:
        tmp.chmod(0o700)
        for relative, obj in entries.items():
            if not re.fullmatch(r"(?:reviewer_a|reviewer_b)/assignment\.json|(?:packet|adjudication_template|structural_audit|m4_candidate_DO_NOT_PUBLISH)\.json", relative):
                raise ReviewError("unsafe output file name")
            path = tmp / relative
            path.parent.mkdir(mode=0o700, exist_ok=True)
            fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
                f.flush()
                os.fsync(f.fileno())
        _private_output(dest)
        tmp.rename(dest)
    finally:
        if tmp.exists():
            import shutil
            shutil.rmtree(tmp)


def review_plan(corpus: dict) -> dict:
    summary = validate_candidates(corpus)
    return {"contract": CONTRACT, "mode": "OFFLINE_EXPERT_REVIEW_PLAN",
            "candidates": summary["total_candidates"],
            "source_section_clusters": summary["unique_source_section_clusters"],
            "reviewable_now": 0, "expert_gold_cases": 0, "legal_accuracy_measured": False,
            "requires_before_review": ["source publication and precise versions manually checked",
                "rights for INTERNAL_EXPERT_REVIEW_ONLY independently reviewed",
                "M5-A pending queue and matching attestation receipts generated",
                "two qualified independent reviewers and a distinct adjudicator actually recruited"],
            "note": "Planning alone neither attests rights nor creates expert labels."}


def _packet_cases(corpus: dict, pending: list, receipts_doc: dict) -> list[dict]:
    """Only accept a M5-A human-attested PENDING_EXPERT handoff."""
    validate_candidates(corpus)
    by_id = {c["case_id"]: c for c in corpus["cases"]}
    if not isinstance(pending, list) or not 1 <= len(pending) <= MAX_CASES:
        raise ReviewError("pending records required; no eligible material yet")
    if (not isinstance(receipts_doc, dict) or set(receipts_doc) != {
            "contract", "note", "staged_count", "expert_gold_cases", "legal_accuracy_measured", "receipts"}
            or receipts_doc["contract"] != "keepmehonest-legal-es/m5-stage-receipts/v1"
            or receipts_doc["expert_gold_cases"] != 0 or receipts_doc["legal_accuracy_measured"] is not False
            or receipts_doc["staged_count"] != len(pending) or not isinstance(receipts_doc["receipts"], list)):
        raise ReviewError("M5-A source attestation receipt invalid or missing")
    receipts = {r.get("case_id"): r for r in receipts_doc["receipts"] if isinstance(r, dict)}
    if len(receipts) != len(pending) or len(receipts_doc["receipts"]) != len(pending):
        raise ReviewError("receipts are duplicated, incomplete or unmatched")
    result = []
    seen = set()
    for record in pending:
        try:
            validate_annotation(record)
        except (AnnotationError, ValueError, TypeError) as e:
            raise ReviewError("M4 pending record invalid") from e
        cid = record["case_id"]
        if cid not in by_id or cid in seen or record["status"] != "PENDING_EXPERT":
            raise ReviewError("pending record not tied to a unique M5 candidate")
        seen.add(cid)
        case = by_id[cid]
        src = _validate_source(case["source"])
        receipt = receipts.get(cid)
        if not isinstance(receipt, dict) or set(receipt) != {
                "case_id", "official_url", "section_id", "evidence_sha256", "argument_sha256",
                "capture_checked_by", "capture_checked_on", "reuse_checked_by", "reuse_checked_on",
                "reuse_basis_url", "license_scope", "source_version_as_of", "decision_note", "not_gold",
                "original_capture_file"}:
            raise ReviewError("M5 source receipt schema invalid")
        if (receipt["official_url"] != src["official_url"] or
                receipt["section_id"] != src["section_id"] or
                receipt["original_capture_file"] != cid + ".txt" or
                receipt["evidence_sha256"] != record["evidence_sha256"] or
                receipt["argument_sha256"] != record["argument_sha256"] or
                record["source_kind"] != src["kind"] or
                receipt["license_scope"] != "INTERNAL_EXPERT_REVIEW_ONLY" or
                receipt["not_gold"] is not True or
                receipt["capture_checked_by"] == receipt["reuse_checked_by"] or
                not isinstance(receipt["capture_checked_by"], str) or
                not isinstance(receipt["reuse_checked_by"], str) or
                any(not _hex(record[k]) for k in ("evidence_sha256", "argument_sha256")) or
                record["argument_sha256"] != sha256(case["proposition"].encode("utf-8")).hexdigest()):
            raise ReviewError("capture rights/provenance or source mapping not established")
        payload = {"case_id": cid, "area": case["area"], "stress_dimension": case["stress_dimension"],
                   "proposition": case["proposition"], "fact_pattern": case["fact_pattern"],
                   "event_date": case["event_date"], "review_question": case["review_question"],
                   "source": src, "argument_sha256": record["argument_sha256"],
                   "evidence_sha256": record["evidence_sha256"],
                   "capture_receipt_sha256": _sha(receipt),
                   "source_version_as_of": receipt["source_version_as_of"],
                   "evidence_locator": f"{src['official_url']}#{src['section_id']}"}
        payload["case_sha256"] = _sha(payload)
        result.append(payload)
    return sorted(result, key=lambda c: c["case_id"])


def _empty_review(case: dict) -> dict:
    return {**{key: None for key in REVIEW_FIELDS if key not in ("case_id", "case_sha256")},
            "case_id": case["case_id"], "case_sha256": case["case_sha256"]}


def _empty_adjudication(case: dict) -> dict:
    return {**{key: None for key in ADJ_FIELDS if key not in ("case_id", "case_sha256")},
            "case_id": case["case_id"], "case_sha256": case["case_sha256"]}


def prepare(corpus: dict, pending: list, receipts: dict, out_dir: Path) -> dict:
    cases = _packet_cases(corpus, pending, receipts)
    manifest = {"contract": CONTRACT, "status": "NOT_YET_EXPERT_REVIEWED", "cases": cases,
                "candidate_corpus_sha256": validate_candidates(corpus)["corpus_sha256"],
                "rights_scope": "INTERNAL_EXPERT_REVIEW_ONLY", "expert_gold_cases": 0,
                "legal_accuracy_measured": False}
    packet_sha = _sha(manifest)
    packet = {**manifest, "packet_sha256": packet_sha}
    reviewer_packets = {}
    for role in ("reviewer_a", "reviewer_b"):
        reviewer_packets[f"{role}/assignment.json"] = {
            "contract": REVIEW_CONTRACT, "role": role, "packet_sha256": packet_sha,
            "assessments": [_empty_review(c) for c in cases],
        }
    adjud_template = {"contract": ADJUDICATION_CONTRACT, "packet_sha256": packet_sha,
                      "decisions": [_empty_adjudication(c) for c in cases]}
    # Do not give the adjudicator the other reviews until both are submitted.
    _atomic_private_dir(out_dir, {"packet.json": packet,
        **reviewer_packets, "adjudication_template.json": adjud_template})
    return {"contract": CONTRACT, "status": "EXPERT_FORMS_BLANK_NOT_GOLD", "packet_sha256": packet_sha,
            "pending_cases": len(cases), "expert_gold_cases": 0, "legal_accuracy_measured": False,
            "note": "Separate assignments; verify real reviewer credentials and source rights outside software."}


def _review_rows(doc, role, packet_sha, cases):
    if not isinstance(doc, dict) or set(doc) != {"contract", "role", "packet_sha256", "assessments"} or \
            doc["contract"] != REVIEW_CONTRACT or doc["role"] != role or \
            doc["packet_sha256"] != packet_sha or not isinstance(doc["assessments"], list):
        raise ReviewError("review file is not a valid independent submission")
    rows = doc["assessments"]
    if len(rows) != len(cases) or len({r.get("case_id") for r in rows if isinstance(r, dict)}) != len(cases):
        raise ReviewError("review submission has missing or duplicate cases")
    mapped = {}
    for r in rows:
        if not isinstance(r, dict) or set(r) != REVIEW_FIELDS or r["case_id"] not in cases or \
                r["case_sha256"] != cases[r["case_id"]]["case_sha256"]:
            raise ReviewError("reviewer changed case identity or left cases incomplete")
        mapped[r["case_id"]] = {k: v for k, v in r.items() if k not in ("case_id", "case_sha256")}
    return mapped


def validate_submissions(packet: dict, a: dict, b: dict, adjud: dict) -> tuple[list[dict], dict]:
    if not isinstance(packet, dict) or set(packet) != {
            "contract", "status", "cases", "candidate_corpus_sha256", "rights_scope", "expert_gold_cases",
            "legal_accuracy_measured", "packet_sha256"} or \
            packet["contract"] != CONTRACT or packet["status"] != "NOT_YET_EXPERT_REVIEWED" or \
            packet["rights_scope"] != "INTERNAL_EXPERT_REVIEW_ONLY" or \
            packet["expert_gold_cases"] != 0 or packet["legal_accuracy_measured"] is not False:
        raise ReviewError("invalid M5C packet")
    signed = {k: v for k, v in packet.items() if k != "packet_sha256"}
    packet_sha = _sha(signed)
    if packet["packet_sha256"] != packet_sha:
        raise ReviewError("packet hash does not match sealed metadata")
    records = packet["cases"]
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_CASES:
        raise ReviewError("invalid cases in review packet")
    cases = {}
    for row in records:
        if (not isinstance(row, dict) or not _hex(row.get("case_sha256")) or
                row["case_sha256"] != _sha({k: v for k, v in row.items() if k != "case_sha256"}) or
                row["case_id"] in cases):
            raise ReviewError("altered/duplicated case in packet")
        cases[row["case_id"]] = row
    review_a = _review_rows(a, "reviewer_a", packet_sha, cases)
    review_b = _review_rows(b, "reviewer_b", packet_sha, cases)
    if not isinstance(adjud, dict) or set(adjud) != {"contract", "packet_sha256", "decisions"} or \
            adjud["contract"] != ADJUDICATION_CONTRACT or adjud["packet_sha256"] != packet_sha or \
            not isinstance(adjud["decisions"], list) or len(adjud["decisions"]) != len(cases):
        raise ReviewError("invalid adjudicator submission")
    decisions = {}
    for d in adjud["decisions"]:
        if not isinstance(d, dict) or set(d) != ADJ_FIELDS or d["case_id"] not in cases or \
                d["case_sha256"] != cases[d["case_id"]]["case_sha256"] or d["case_id"] in decisions:
            raise ReviewError("adjudicator changed case identity or omitted/duplicated a decision")
        decisions[d["case_id"]] = {k: v for k, v in d.items() if k not in ("case_id", "case_sha256")}
    results = []
    disagreements = 0
    for cid in sorted(cases):
        row = cases[cid]
        ra, rb, rd = review_a[cid], review_b[cid], decisions[cid]
        if ra.get("documentary_label") != rb.get("documentary_label") or \
                ra.get("legal_support_label") != rb.get("legal_support_label"):
            disagreements += 1
        record = {"contract": M4_CONTRACT, "case_id": cid, "source_kind": row["source"]["kind"],
                  "evidence_sha256": row["evidence_sha256"], "argument_sha256": row["argument_sha256"],
                  "contains_confidential_data": False, "reuse_reviewed": True, "status": "ADJUDICATED",
                  "reviewer_a": ra, "reviewer_b": rb, "adjudication": rd}
        try:
            validate_annotation(record)
        except (AnnotationError, ValueError, TypeError) as exc:
            raise ReviewError(f"case {cid} failed M4 expert schema gate: {exc}") from exc
        results.append(record)
    return results, {"contract": CONTRACT, "status": "STRUCTURAL_ADJUDICATION_VALIDATED_PENDING_M5D",
                     "cases_checked": len(results), "reviewer_disagreements": disagreements,
                     "packet_sha256": packet_sha,
                     "submission_sha256": {"reviewer_a": _sha(a), "reviewer_b": _sha(b), "adjudication": _sha(adjud)},
                     "m4_candidate_sha256": _sha(results),
                     "expert_gold_cases": 0, "legal_accuracy_measured": False,
                     "human_identity_verified_by_software": False, "expert_credentials_verified_by_software": False,
                     "legal_correctness_verified_by_software": False,
                     "rights_and_independence_reaudit_required": True,
                     "note": "M4 adjudication-form checks only; M5-D must independently verify credentials, custody and decisions."}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="M5-C expert handoff / review form validation; no automatic legal labels")
    sub = parser.add_subparsers(dest="command", required=True)
    plan_p = sub.add_parser("plan", help="Offline plan, no labels or clearance")
    plan_p.add_argument("--candidates", type=Path, required=True)
    prep_p = sub.add_parser("prepare", help="Create strictly private blank reviewer forms from M5-A staged pending records")
    prep_p.add_argument("--candidates", type=Path, required=True)
    prep_p.add_argument("--pending", type=Path, required=True)
    prep_p.add_argument("--receipts", type=Path, required=True)
    prep_p.add_argument("--output-dir", type=Path, required=True)
    val_p = sub.add_parser("validate", help="Structural validation, NOT expert authentication or gold standard")
    val_p.add_argument("--packet", type=Path, required=True)
    val_p.add_argument("--reviewer-a", type=Path, required=True)
    val_p.add_argument("--reviewer-b", type=Path, required=True)
    val_p.add_argument("--adjudication", type=Path, required=True)
    val_p.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = review_plan(_safe_json(args.candidates))
        elif args.command == "prepare":
            result = prepare(_safe_json(args.candidates), _safe_json(args.pending),
                             _safe_json(args.receipts), args.output_dir)
        else:
            records, result = validate_submissions(_safe_json(args.packet), _safe_json(args.reviewer_a),
                                                   _safe_json(args.reviewer_b), _safe_json(args.adjudication))
            _atomic_private_dir(args.output_dir, {"structural_audit.json": result,
                "m4_candidate_DO_NOT_PUBLISH.json": records})
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (ReviewError, AnnotationError, OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        print(f"M5-C review error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
