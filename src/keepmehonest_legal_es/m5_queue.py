"""M5 pilot public-source candidate queue and controlled hand-off to M4.

No network, models, legal-support inference, or expert-label generation.
Candidates are author-generated hypotheses, not legal gold. A staged source
capture requires documented human checks and is STILL only PENDING_EXPERT.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit

from .m4_review import CONTRACT as M4_CONTRACT, summarize_review_queue

CONTRACT = "keepmehonest-legal-es/m5-public-candidates/v1"
CAPTURE_CONTRACT = "keepmehonest-legal-es/m5-capture-attestations/v1"
AREAS = frozenset({"CONSTITUCIONAL", "ADMINISTRATIVO", "LABORAL", "PROTECCION_DATOS", "JURISPRUDENCIA_TC"})
STRESS = frozenset({"SOURCE_SCOPE", "TEMPORAL", "EXCEPTION", "ABSOLUTE_CLAIM", "PROCEDURAL", "FACT_GAP", "CITATION_FIDELITY"})
CANDIDATE_FIELDS = frozenset({"case_id", "area", "proposition", "fact_pattern", "event_date", "review_question", "stress_dimension", "source", "status", "origin", "has_confidential_data", "expert_label", "evidence_sha256", "reuse_reviewed"})
SOURCE_FIELDS = frozenset({"kind", "identifier", "section_id", "official_url", "hj_document_id"})
ATTEST_FIELDS = frozenset({"case_id", "capture_file", "kind", "identifier", "section_id", "official_url", "capture_checked_by", "capture_checked_on", "reuse_checked_by", "reuse_checked_on", "reuse_basis_url", "license_scope", "source_version_as_of", "no_confidential_data_verified", "source_publication_checked", "decision_note"})
BOE = re.compile(r"BOE-A-\d{4}-\d{1,8}\Z")
TC = re.compile(r"ECLI:ES:TC:\d{4}:\d{1,6}\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
CASE_ID = re.compile(r"PUB-M5-\d{3}\Z")

class QueueError(ValueError):
    """Invalid or overclaimed M5 candidate/attestation data."""


def _no_duplicate_keys(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise QueueError(f"duplicate JSON key {k!r}")
        result[k] = v
    return result


def _read_json(path: Path, max_bytes=1_000_000):
    if path.stat().st_size > max_bytes:
        raise QueueError("JSON file too large")
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicate_keys)


def _exact_text(s, label, min_len=1, max_len=900):
    if not isinstance(s, str) or not min_len <= len(s.strip()) <= max_len or "\x00" in s:
        raise QueueError(f"invalid {label}")
    return s


def _date(s, label, nullable=False):
    if s is None and nullable:
        return None
    if not isinstance(s, str) or not DATE.fullmatch(s):
        raise QueueError(f"invalid {label}")
    try:
        parsed = date.fromisoformat(s)
    except ValueError as err:
        raise QueueError(f"invalid {label}") from err
    if parsed > date.today():
        raise QueueError(f"future {label} is not accepted")
    return s


def _check_https(url, *, exact_host=None):
    _exact_text(url, "URL", 15, 500)
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username is not None or
            parts.password is not None or parts.port is not None or parts.fragment or
            parts.hostname != parts.netloc or any(ord(c) < 33 for c in url)):
        raise QueueError("invalid HTTPS URL")
    if exact_host and parts.hostname != exact_host:
        raise QueueError("unapproved official source host")
    return url


def _validate_source(s):
    if not isinstance(s, dict) or set(s) != SOURCE_FIELDS:
        raise QueueError("invalid source locator schema")
    kind = s["kind"]
    identifier = s["identifier"]
    section = s["section_id"]
    if kind == "BOE":
        if not isinstance(identifier, str) or not BOE.fullmatch(identifier):
            raise QueueError("invalid BOE identifier")
        if not isinstance(section, str) or not re.fullmatch(r"a[1-9]\d{0,3}", section):
            raise QueueError("invalid BOE section")
        if s["hj_document_id"] is not None:
            raise QueueError("BOE cannot contain HJ document ID")
        expected = f"https://www.boe.es/buscar/act.php?id={identifier}"
    elif kind == "TC":
        if not isinstance(identifier, str) or not TC.fullmatch(identifier):
            raise QueueError("unsupported TC identifier")
        if not isinstance(section, str) or not re.fullmatch(r"FJ[1-9]\d?\d?|FALLO", section):
            raise QueueError("invalid TC section")
        hj = s["hj_document_id"]
        if type(hj) is not int or not 1 <= hj <= 999_999:
            raise QueueError("invalid HJ document ID")
        expected = f"https://hj.tribunalconstitucional.es/HJ/es/Resolucion/Show/{hj}"
    else:
        raise QueueError("CENDOJ and other sources are excluded")
    if _check_https(s["official_url"]) != expected:
        raise QueueError("source locator must match canonical official URL")
    return s


def validate_candidates(payload: Any) -> dict:
    if (not isinstance(payload, dict) or set(payload) != {"contract", "status", "cases", "note"} or
            payload["contract"] != CONTRACT or payload["status"] != "UNANNOTATED_NOT_GOLD"):
        raise QueueError("invalid candidate corpus contract")
    _exact_text(payload["note"], "corpus note", 20, 500)
    cases = payload["cases"]
    if not isinstance(cases, list) or not 30 <= len(cases) <= 50:
        raise QueueError("pilot requires 30–50 candidate cases")
    ids, propositions, areas, stresses = set(), set(), Counter(), Counter()
    source_counts = Counter()
    section_counts = Counter()
    for i, c in enumerate(cases):
        if not isinstance(c, dict) or set(c) != CANDIDATE_FIELDS:
            raise QueueError(f"case {i}: invalid candidate schema")
        case_id = c["case_id"]
        if not isinstance(case_id, str) or not CASE_ID.fullmatch(case_id) or case_id in ids:
            raise QueueError("duplicate/invalid case ID")
        ids.add(case_id)
        if c["area"] not in AREAS or c["stress_dimension"] not in STRESS:
            raise QueueError("unknown area or stress dimension")
        text = _exact_text(c["proposition"], "proposition", 35, 700)
        if text.casefold().strip() in propositions:
            raise QueueError("duplicate proposition")
        propositions.add(text.casefold().strip())
        _exact_text(c["fact_pattern"], "hypothetical facts", 35, 800)
        _exact_text(c["review_question"], "review question", 25, 350)
        _date(c["event_date"], "hypothetical event date", nullable=True)
        if (c["status"] != "PENDING_SOURCE_CAPTURE_AND_EXPERT_REVIEW" or
                c["origin"] != "AI_DRAFT_HYPOTHETICAL_PUBLIC_LOCATOR" or
                c["has_confidential_data"] is not False or c["expert_label"] is not None or
                c["evidence_sha256"] is not None or c["reuse_reviewed"] is not False):
            raise QueueError("candidates must not claim source/rights/expert clearance")
        s = _validate_source(c["source"])
        if (c["area"] == "JURISPRUDENCIA_TC") != (s["kind"] == "TC"):
            raise QueueError("area and source kind mismatch")
        areas[c["area"]] += 1
        stresses[c["stress_dimension"]] += 1
        source_counts[s["identifier"]] += 1
        section_counts[(s["identifier"], s["section_id"])] += 1
    if set(areas) != AREAS or len(stresses) < 6:
        raise QueueError("insufficient domain/stress diversity")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "contract": CONTRACT, "total_candidates": len(cases),
        "areas": dict(sorted(areas.items())), "stress_dimensions": dict(sorted(stresses.items())),
        "source_identifiers": dict(sorted(source_counts.items())),
        "unique_source_section_clusters": len(section_counts),
        "largest_source_section_cluster": max(section_counts.values()),
        "independent_case_sample_claimed": False,
        "corpus_sha256": hashlib.sha256(encoded).hexdigest(),
        "expert_gold_cases": 0, "legal_accuracy_measured": False,
        "source_snapshots_included": 0, "rights_cleared": 0,
        "note": "AI-drafted public-reference candidates; NOT expert labels, a random sample or holdout data."
    }


def _safe_capture(root: Path, filename: str) -> bytes:
    if (not isinstance(filename, str) or not re.fullmatch(r"PUB-M5-\d{3}\.txt", filename)
            or filename.startswith(".")):
        raise QueueError("capture must be a case-ID-named .txt file")
    if root.is_symlink() or not root.is_dir():
        raise QueueError("invalid capture directory")
    f = root / filename
    if f.is_symlink() or not f.is_file() or f.resolve().parent != root.resolve():
        raise QueueError("capture path escapes directory or is not a regular file")
    if not 64 <= f.stat().st_size <= 500_000:
        raise QueueError("capture size outside limits")
    raw = f.read_bytes()
    text = raw.decode("utf-8")
    if "\x00" in text or text.startswith("\ufeff"):
        raise QueueError("capture contains disallowed characters/BOM")
    return raw


def stage_pending(corpus, attestations, capture_root: Path):
    """Generate M4 pending records only from local captured, human-attested evidence.

    Attestations are assertions by people, NOT proof of legal/source authenticity.
    Capture bytes are not copied to output and must stay in controlled custody.
    """
    validate_candidates(corpus)
    if (not isinstance(attestations, dict) or set(attestations) != {"contract", "attestations"} or
            attestations["contract"] != CAPTURE_CONTRACT or
            not isinstance(attestations["attestations"], list) or
            not 1 <= len(attestations["attestations"]) <= len(corpus["cases"])):
        raise QueueError("invalid capture manifest")
    by_id = {c["case_id"]: c for c in corpus["cases"]}
    staged = []
    receipts = []
    seen = set()
    for att in attestations["attestations"]:
        if not isinstance(att, dict) or set(att) != ATTEST_FIELDS:
            raise QueueError("incomplete human capture attestation")
        cid = att["case_id"]
        if cid in seen or cid not in by_id:
            raise QueueError("duplicated or unknown captured case")
        seen.add(cid)
        case = by_id[cid]
        src = case["source"]
        for key, mapped in (("kind", "kind"), ("identifier", "identifier"),
                            ("section_id", "section_id"), ("official_url", "official_url")):
            if att[key] != src[mapped]:
                raise QueueError(f"capture source mismatch: {key}")
        for f in ("capture_checked_by", "reuse_checked_by"):
            _exact_text(att[f], f, 3, 120)
        for f in ("capture_checked_on", "reuse_checked_on"):
            _date(att[f], f)
        if (att["capture_checked_by"] == att["reuse_checked_by"] or
                att["source_publication_checked"] is not True or
                att["no_confidential_data_verified"] is not True):
            raise QueueError("independent source and rights checks required")
        _date(att["source_version_as_of"], "source version as-of date")
        _check_https(att["reuse_basis_url"])
        if att["license_scope"] != "INTERNAL_EXPERT_REVIEW_ONLY":
            raise QueueError("publication or broader reuse is not approved here")
        _exact_text(att["decision_note"], "review decision note", 40, 800)
        if att["capture_file"] != cid + ".txt":
            raise QueueError("capture file does not correspond to case ID")
        raw = _safe_capture(capture_root, att["capture_file"])
        digest = hashlib.sha256(raw).hexdigest()
        claim_hash = hashlib.sha256(case["proposition"].encode("utf-8")).hexdigest()
        staged.append({"contract": M4_CONTRACT, "case_id": cid,
                       "source_kind": src["kind"], "evidence_sha256": digest,
                       "argument_sha256": claim_hash, "contains_confidential_data": False,
                       "reuse_reviewed": True, "status": "PENDING_EXPERT",
                       "reviewer_a": None, "reviewer_b": None, "adjudication": None})
        receipts.append({"case_id": cid, "official_url": src["official_url"],
                         "section_id": src["section_id"], "evidence_sha256": digest,
                         "argument_sha256": claim_hash,
                         "capture_checked_by": att["capture_checked_by"],
                         "capture_checked_on": att["capture_checked_on"],
                         "reuse_checked_by": att["reuse_checked_by"],
                         "reuse_checked_on": att["reuse_checked_on"],
                         "reuse_basis_url": att["reuse_basis_url"],
                         "license_scope": att["license_scope"],
                         "source_version_as_of": att["source_version_as_of"],
                         "decision_note": att["decision_note"],
                         "not_gold": True, "original_capture_file": att["capture_file"]})
    summarize_review_queue(staged)
    return staged, {"contract": "keepmehonest-legal-es/m5-stage-receipts/v1",
                    "note": "Human attestations; capture integrity and provenance NOT independently authenticated.",
                    "staged_count": len(staged), "expert_gold_cases": 0,
                    "legal_accuracy_measured": False, "receipts": receipts}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="M5 pilot candidate validation / strictly controlled M4 staging")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--stage-manifest", type=Path)
    parser.add_argument("--capture-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = _read_json(args.candidates)
        summary = validate_candidates(payload)
        if args.stage_manifest or args.capture_root or args.output_dir:
            if not (args.stage_manifest and args.capture_root and args.output_dir):
                raise QueueError("staging requires manifest, capture root and output directory")
            if args.output_dir.exists() or args.output_dir.is_symlink():
                raise QueueError("output directory must not already exist")
            att = _read_json(args.stage_manifest)
            records, receipts = stage_pending(payload, att, args.capture_root)
            args.output_dir.mkdir(mode=0o700, parents=False)
            for name, output in (("m4_pending_reviews.json", records), ("m5_capture_receipts.json", receipts)):
                target = args.output_dir / name
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(output, f, ensure_ascii=False, indent=2, sort_keys=True)
                    f.write("\n")
            summary["staged_pending_expert"] = len(records)
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, QueueError) as exc:
        print(f"M5 queue error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
