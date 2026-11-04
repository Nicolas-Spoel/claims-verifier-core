"""M5-D: local, metadata-only seal of unreviewed pilot inventory.

This is NOT an adjudicated legal benchmark. A seal checks bytes against
previously recorded hashes and replays M5-B snapshots without any network.
It cannot authenticate publishers, legal correctness, reviewers or reuse rights.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Any

from .m5_capture import CaptureError, verify_capture
from .m5_queue import QueueError, _read_json, validate_candidates

CONTRACT = "keepmehonest-legal-es/m5d-technical-seal/v1"
SEAL_STATE = "SEALED_UNADJUDICATED_TECHNICAL_INVENTORY"
CASE_CAPTURED = "REPLAYED_UNREVIEWED"
CASE_MISSING = "NOT_CAPTURED"
HEX = re.compile(r"[a-f0-9]{64}\Z")
CASE_IDS = ("PUB-M5-001", "PUB-M5-032")
MAX_CAPTURES = 33
MAX_MANIFEST_BYTES = 1_000_000


class SealError(ValueError):
    """Unsafe input, mismatched replay or unsupported legal provenance claim."""


def _bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(obj: Any) -> str:
    return sha256(_bytes(obj)).hexdigest()


def _text_sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _hex(s: Any) -> bool:
    return isinstance(s, str) and HEX.fullmatch(s) is not None


def _read(path: Path) -> Any:
    if path.is_symlink() or not path.is_file() or not stat.S_ISREG(path.lstat().st_mode):
        raise SealError("unsafe or missing JSON file")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise SealError("oversized seal input")
    return _read_json(path, max_bytes=MAX_MANIFEST_BYTES)


def plan(corpus: dict) -> dict:
    inv = validate_candidates(corpus)
    return {"contract": CONTRACT, "mode": "OFFLINE_TECHNICAL_SEAL_PLAN",
            "candidate_cases": inv["total_candidates"],
            "candidate_corpus_sha256": inv["corpus_sha256"],
            "pilots": list(CASE_IDS),
            "expert_gold_cases": 0, "legal_accuracy_measured": False,
            "rights_cleared": 0,
            "ready_for_public_legal_accuracy_claims": False,
            "note": "Can freeze inventory and replayed bytes without expert review; not legal validation."}


def _capture_metadata(corpus: dict, roots: list[Path]) -> list[dict]:
    if not 1 <= len(roots) <= MAX_CAPTURES:
        raise SealError("seal needs 1-33 individually provided offline capture directories")
    if len({str(r) for r in roots}) != len(roots):
        raise SealError("duplicate capture directory")
    all_tasks: set[str] = set()
    seen_cases: set[str] = set()
    found = []
    for root in roots:
        # Existing M5-B verifier rechecks raw bytes AND deterministic re-extraction.
        verified = verify_capture(corpus, root)
        mf = _read(root / "manifest.json")
        if not isinstance(mf, dict) or not isinstance(mf.get("tasks"), list):
            raise SealError("capture manifest invalid")
        for t in mf["tasks"]:
            if t["task_id"] in all_tasks:
                raise SealError("same snapshot task provided twice")
            all_tasks.add(t["task_id"])
            if any(cid in seen_cases for cid in t["case_ids"]):
                raise SealError("same candidate captured more than once")
            seen_cases.update(t["case_ids"])
            found.append({
                "task_id": t["task_id"],
                "case_ids": list(t["case_ids"]),
                "source": t["kind"],
                "identifier": t["identifier"],
                "section_id": t["section_id"],
                "requested_as_of": t["requested_as_of"],
                "source_manifest_sha256": verified["sha256_manifest"],
                "section_sha256": t["section_sha256"],
                "raw_sha256": [raw["sha256"] for raw in t["raw"]],
                "technical_status": CASE_CAPTURED,
                "publication_checked": False,
                "rights_reviewed": False,
                "legal_applicability": "NOT_ASSESSED",
            })
    return sorted(found, key=lambda x: x["task_id"])


def assemble(corpus: dict, capture_dirs: list[Path]) -> dict:
    inventory = validate_candidates(corpus)
    captures = _capture_metadata(corpus, capture_dirs)
    by_case = {cid: t["task_id"] for t in captures for cid in t["case_ids"]}
    cases = [{"case_id": c["case_id"],
              "proposition_sha256": _text_sha(c["proposition"]),
              "source_kind": c["source"]["kind"],
              "source_identifier": c["source"]["identifier"],
              "source_section": c["source"]["section_id"],
              "capture_task_id": by_case.get(c["case_id"]),
              "capture_status": CASE_CAPTURED if c["case_id"] in by_case else CASE_MISSING,
              "expert_status": "NOT_REVIEWED",
              "legal_support": "NOT_ASSESSED"}
             for c in corpus["cases"]]
    manifest = {
        "contract": CONTRACT, "status": SEAL_STATE,
        "candidate_corpus_sha256": inventory["corpus_sha256"],
        "candidate_cases": inventory["total_candidates"],
        "source_section_clusters": inventory["unique_source_section_clusters"],
        "cases": cases,
        "captures": captures,
        "captured_cases": len(by_case),
        "uncaptured_cases": len(cases) - len(by_case),
        "technically_replayed_tasks": len(captures),
        "expert_gold_cases": 0,
        "independently_adjudicated_cases": 0,
        "rights_cleared": 0,
        "legal_accuracy_measured": False,
        "legal_support_accuracy_measured": False,
        "ready_for_public_legal_accuracy_claims": False,
        "rights_for_source_redistribution": "NOT_REVIEWED",
        "human_review_status": "PENDING_UNFUNDED",
        "privacy_note": "No source texts or absolute capture paths in this manifest; private capture files stay outside Git.",
        "technical_note": "Self-hash/section hashes detect changes relative to local snapshots, NOT authentic publisher or legal validity.",
    }
    return {**manifest, "seal_sha256": _sha(manifest)}


def _validate_seal_schema(seal: dict, corpus: dict) -> None:
    if not isinstance(seal, dict) or set(seal) != {
        "contract", "status", "candidate_corpus_sha256", "candidate_cases", "source_section_clusters",
        "cases", "captures", "captured_cases", "uncaptured_cases", "technically_replayed_tasks",
        "expert_gold_cases", "independently_adjudicated_cases", "rights_cleared",
        "legal_accuracy_measured", "legal_support_accuracy_measured", "ready_for_public_legal_accuracy_claims",
        "rights_for_source_redistribution", "human_review_status", "privacy_note", "technical_note", "seal_sha256"}:
        raise SealError("unexpected seal schema")
    if seal.get("contract") != CONTRACT or seal.get("status") != SEAL_STATE:
        raise SealError("unknown or promoted seal status")
    if not _hex(seal["seal_sha256"]) or _sha({k: v for k, v in seal.items() if k != "seal_sha256"}) != seal["seal_sha256"]:
        raise SealError("seal digest mismatch")
    if (seal["expert_gold_cases"] != 0 or seal["independently_adjudicated_cases"] != 0 or
            seal["rights_cleared"] != 0 or seal["legal_accuracy_measured"] is not False or
            seal["legal_support_accuracy_measured"] is not False or
            seal["ready_for_public_legal_accuracy_claims"] is not False or
            seal["rights_for_source_redistribution"] != "NOT_REVIEWED" or
            seal["human_review_status"] != "PENDING_UNFUNDED"):
        raise SealError("gold/rights/accuracy promotion is forbidden without external review")
    inv = validate_candidates(corpus)
    if seal["candidate_corpus_sha256"] != inv["corpus_sha256"]:
        raise SealError("seal belongs to a different candidate corpus")


def verify_seal(corpus: dict, capture_dirs: list[Path], seal: dict) -> dict:
    _validate_seal_schema(seal, corpus)
    regenerated = assemble(corpus, capture_dirs)
    if seal != regenerated:
        raise SealError("sealed inventory differs from current verified captures")
    return {"contract": CONTRACT, "mode": "OFFLINE_M5D_TECHNICAL_SEAL_VERIFIED",
            "seal_sha256": seal["seal_sha256"],
            "candidate_cases": seal["candidate_cases"],
            "captured_cases": seal["captured_cases"],
            "uncaptured_cases": seal["uncaptured_cases"],
            "technically_replayed_tasks": seal["technically_replayed_tasks"],
            "rights_cleared": 0, "expert_gold_cases": 0,
            "legal_accuracy_measured": False,
            "publication_scope": "CODE_AND_PUBLIC_METADATA_ONLY_NO_SOURCE_TEXT",
            "note": "Technical byte replay and inventory freeze, not legal gold or rights clearance."}


def _safe_destination(dest: Path) -> None:
    if (not dest.is_absolute() or dest.exists() or dest.is_symlink() or
            not dest.parent.is_dir() or dest.parent.is_symlink() or
            not (dest.parent.stat().st_mode & stat.S_IWUSR)):
        raise SealError("new absolute output directory under an existing non-symlink parent required")


def _save_privately(dest: Path, seal: dict) -> None:
    _safe_destination(dest)
    tmp = Path(tempfile.mkdtemp(prefix=f".{dest.name}.tmp-", dir=dest.parent))
    try:
        tmp.chmod(0o700)
        p = tmp / "technical_seal_PRIVATE.json"
        fd = os.open(p, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(seal, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
            f.flush()
            os.fsync(f.fileno())
        _safe_destination(dest)
        tmp.rename(dest)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="M5-D technical freeze. No gold labels, source redistribution or legal accuracy claims")
    sub = parser.add_subparsers(dest="action", required=True)
    for act in ("plan", "seal", "verify"):
        p = sub.add_parser(act)
        p.add_argument("--candidates", type=Path, required=True)
        if act != "plan":
            p.add_argument("--capture-dir", type=Path, action="append", required=True)
            if act == "seal":
                p.add_argument("--output-dir", type=Path, required=True)
            else:
                p.add_argument("--seal-file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        corpus = _read(args.candidates)
        if args.action == "plan":
            report = plan(corpus)
        elif args.action == "seal":
            sealed = assemble(corpus, args.capture_dir)
            _save_privately(args.output_dir, sealed)
            report = verify_seal(corpus, args.capture_dir, sealed)
        else:
            report = verify_seal(corpus, args.capture_dir, _read(args.seal_file))
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (SealError, CaptureError, QueueError, ValueError, KeyError, TypeError, OSError, UnicodeError) as exc:
        print(f"M5-D technical seal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
