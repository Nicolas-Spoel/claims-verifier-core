"""M7-A: deterministic documentary review gate, NEVER a legal merits classifier.

Consumes a fresh M3 independent report, rejects internally inconsistent claim
lineage, and returns a text-free human review queue. This is a *workflow*
assessment; no lexical score, quote match, source origin or legal-scope flag
can become a legal support, truth or applicability verdict.

The CLI operates on local documents only and deliberately has no network mode.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import sys

from .evidence import Origin, SourceKind
from .independent import REPORT_VERSION, verify_argument
from .grounding import _canon_section

CONTRACT = "keepmehonest-legal-es/m7a-documentary-review-gate/v1"
MAX_TEXT_BYTES = 800_000
MAX_EVIDENCE_BYTES = 2_000_000
MAX_CLAIMS = 300
_HEX = re.compile(r"[0-9a-f]{64}\Z")

# Non-semantic M3-B signals, recognized by exact code only. In particular,
# arbitrary source text and caller-provided issue descriptions are never copied.
_ALLOWED_ISSUES = frozenset({
    "SENTENCE_CONTEXT_UNRESOLVED",
    "OTHER_CLAUSE_CITATION_NOT_INHERITED",
    "DOCUMENTARY_SUPPORT_NOT_ESTABLISHED",
    "EXACT_QUOTE_DOES_NOT_PROVE_PROPOSITION",
    "EXACT_SOURCE_SECTION_NOT_LINKED",
    "ABSOLUTE_SCOPE_REQUIRES_REVIEW",
    "ASSERTED_TEMPORAL_SCOPE_UNVERIFIED",
    "EVIDENCE_AUTHENTICITY_NOT_INDEPENDENTLY_VERIFIED",
    "BOE_VIGENCIA_AND_APPLICABILITY_NOT_ESTABLISHED",
    "TC_RATIO_PROCEDURAL_FIT_AND_LATER_CASES_UNCHECKED",
    "ORDINARY_COURTS_COVERAGE_NOT_SEARCHED",
    "CITED_SECTION_CONTAINS_SCOPE_QUALIFIER",
})


class ReviewGateError(ValueError):
    """Report is incompatible, internally inconsistent or overclaims legal status."""


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _hash_text(text: str) -> str:
    return _digest(text.encode("utf-8"))


def _sha(value: object) -> bool:
    return type(value) is str and _HEX.fullmatch(value) is not None


def _fail(message: str) -> None:
    raise ReviewGateError(message)


def _evidence_index(report: dict) -> dict[str, dict]:
    evidence = report.get("evidence")
    if not isinstance(evidence, list) or len(evidence) > 30:
        _fail("evidence inventory is absent or exceeds the M3 limit")
    found: dict[str, dict] = {}
    for entry in evidence:
        if not isinstance(entry, dict):
            _fail("malformed evidence inventory entry")
        key, digest = entry.get("evidence_key"), entry.get("sha256")
        source, origin = entry.get("source"), entry.get("origin")
        if (not _sha(key) or not _sha(digest)
                or source not in {s.value for s in SourceKind}
                or origin not in {o.value for o in Origin}
                or type(entry.get("identifier")) is not str
                or type(entry.get("section_id")) is not str):
            _fail("evidence fingerprint, identity or origin invalid")
        raw = (f"{source}\0{entry['identifier']}\0{entry['section_id']}\0{digest}").encode("utf-8")
        if _digest(raw) != key or key in found:
            _fail("evidence manifest key inconsistent or duplicated")
        found[key] = entry
    return found


def _workflow(anchor_status: str) -> str:
    if anchor_status == "DOCUMENTARY_QUOTE_MATCH":
        return "LITERAL_QUOTE_LOCATED_NOT_LEGAL_SUPPORT"
    if anchor_status == "QUOTED_PASSAGE_NOT_FOUND_IN_CITED_SECTION":
        return "QUOTATION_DISCREPANCY_REQUIRES_REVIEW"
    if anchor_status.startswith("SECTION_LOCATED_"):
        return "CITED_SECTION_WITHOUT_VERIFIABLE_QUOTE"
    return "CITATION_OR_SECTION_UNRESOLVED"


def assess_report(report: dict) -> dict:
    """Review the *internal consistency* of an M3 report, never source authenticity.

    Does not verify raw source bytes. Use this API only with a report just
    produced by `verify_argument`; a copied/forged report remains untrusted.
    """
    if not isinstance(report, dict) or report.get("schema_version") != REPORT_VERSION:
        _fail("M7 requires an M3 independent report of the supported version")
    if report.get("legal_interpretation") != "NOT_ASSESSED" or report.get("legal_argument_quality") != "NOT_ASSESSED":
        _fail("M3 report must not contain legal quality verdicts")
    coverage = report.get("coverage")
    if (not isinstance(coverage, dict)
            or coverage.get("corpus_completeness") != "UNVERIFIABLE"
            or coverage.get("ordinary_court_search") != "NOT_PERFORMED_CENDOJ_DISABLED"
            or coverage.get("general_case_law_search") != "NOT_PERFORMED"):
        _fail("M3 non-exhaustive coverage contract missing")
    inventory = _evidence_index(report)
    claims = report.get("claims")
    if not isinstance(claims, list) or len(claims) > MAX_CLAIMS:
        _fail("M3 claims inventory malformed or excessive")
    if report.get("status") not in {"READY_FOR_HUMAN_REVIEW", "SOURCES_REQUIRED", "NO_CHECKABLE_CLAIMS"}:
        _fail("unknown M3 workflow state")
    if report.get("status") == "NO_CHECKABLE_CLAIMS" and claims:
        _fail("empty-claims M3 status contradicts inventory")

    rows = []
    counts = {"literal_quote_located": 0, "quote_discrepancies": 0,
              "section_without_quote": 0, "citation_or_section_unresolved": 0,
              "claims_with_scope_flags": 0, "claims_with_unsupported_sentence_citation": 0}
    for index, claim in enumerate(claims, start=1):
        if not isinstance(claim, dict) or not isinstance(claim.get("claim"), str) or not claim["claim"].strip():
            _fail("M3 claim missing")
        grounding, scope, context = (claim.get("documentary_grounding"),
                                     claim.get("legal_scope_screen"), claim.get("sentence_context"))
        if not all(isinstance(d, dict) for d in (grounding, scope, context)):
            _fail("M3 claim missing grounding, context or scope screen")
        if (claim.get("legal_support") != "NOT_ASSESSED"
                or claim.get("argument_quality") != "NOT_ASSESSED"
                or grounding.get("legal_support") != "NOT_ASSESSED"
                or grounding.get("legal_applicability") != "NOT_ASSESSED"
                or grounding.get("requires_human_review") is not True
                or scope.get("screen_status") != "HUMAN_LEGAL_REVIEW_REQUIRED"
                or scope.get("legal_support") != "NOT_ASSESSED"
                or scope.get("legal_applicability") != "NOT_ASSESSED"
                or scope.get("requires_human_review") is not True
                or context.get("inherit_documentary_anchor") is not False
                or claim.get("review_status") != "HUMAN_REVIEW_REQUIRED"):
            _fail("claim attempts to elevate documentary evidence to legal truth")
        if not _sha(grounding.get("claim_sha256")) or grounding["claim_sha256"] != _hash_text(claim["claim"]):
            _fail("claim hash does not match supplied text")
        status = grounding.get("anchor_status")
        if type(status) is not str or len(status) > 100 or not re.fullmatch(r"[A-Z0-9_]+", status):
            _fail("unknown documentary anchor state")
        evidence_key = grounding.get("evidence_key")
        if evidence_key is not None:
            if evidence_key not in inventory:
                _fail("claim's linked evidence not in report inventory")
            linked = inventory[evidence_key]
            if (grounding.get("evidence_sha256") != linked["sha256"]
                    or grounding.get("source_identifier") != linked["identifier"]
                    or grounding.get("source_origin") != linked["origin"]
                    or grounding.get("cited_section_id") != _canon_section(SourceKind(linked["source"]), linked["section_id"])):
                _fail("claim provenance does not match evidence inventory")
        if status == "DOCUMENTARY_QUOTE_MATCH":
            if (evidence_key is None or not _sha(grounding.get("quoted_passage_sha256"))
                    or type(grounding.get("quoted_passage_characters")) is not int
                    or grounding["quoted_passage_characters"] < 12
                    or grounding.get("quote_match_method") != "LITERAL_NFC_WHITESPACE_ONLY"
                    or "QUOTE_DOES_NOT_ESTABLISH_LEGAL_ENTAILMENT" not in grounding.get("review_flags", [])):
                _fail("literal quote match lacks a complete M3 audit trail")
        issues = scope.get("issues")
        if not isinstance(issues, list) or len(issues) > 30:
            _fail("M3-B review signals missing or excessive")
        issue_codes = set()
        for issue in issues:
            if not isinstance(issue, dict) or issue.get("code") not in _ALLOWED_ISSUES:
                _fail("unknown M3-B review signal")
            if issue["code"] in issue_codes:
                _fail("duplicated M3-B issue")
            issue_codes.add(issue["code"])
        sibling_refs = context.get("sentence_only_identifiers")
        if (not isinstance(sibling_refs, list) or len(sibling_refs) > 30
                or any(type(v) is not str for v in sibling_refs)):
            _fail("sentence lineage missing")
        if sibling_refs and "OTHER_CLAUSE_CITATION_NOT_INHERITED" not in issue_codes:
            _fail("sibling citation was not flagged for review")
        kind = _workflow(status)
        if kind == "LITERAL_QUOTE_LOCATED_NOT_LEGAL_SUPPORT":
            counts["literal_quote_located"] += 1
        elif kind == "QUOTATION_DISCREPANCY_REQUIRES_REVIEW":
            counts["quote_discrepancies"] += 1
        elif kind == "CITED_SECTION_WITHOUT_VERIFIABLE_QUOTE":
            counts["section_without_quote"] += 1
        else:
            counts["citation_or_section_unresolved"] += 1
        scope_codes = sorted(issue_codes & {
            "ABSOLUTE_SCOPE_REQUIRES_REVIEW", "ASSERTED_TEMPORAL_SCOPE_UNVERIFIED",
            "CITED_SECTION_CONTAINS_SCOPE_QUALIFIER"})
        if scope_codes:
            counts["claims_with_scope_flags"] += 1
        if sibling_refs:
            counts["claims_with_unsupported_sentence_citation"] += 1
        rows.append({
            "claim_number": index,
            "claim_sha256": grounding["claim_sha256"],
            "documentary_anchor_status": status,
            "documentary_workflow": kind,
            "linked_evidence_key": evidence_key,
            "evidence_origin": inventory[evidence_key]["origin"] if evidence_key else None,
            "review_signal_codes": sorted(issue_codes),
            "scope_review_signal_codes": scope_codes,
            "sibling_citation_not_inherited": bool(sibling_refs),
            "human_review_required": True,
            "legal_support": "NOT_ASSESSED",
            "legal_applicability": "NOT_ASSESSED",
            "legal_truth_verdict": "NOT_PRODUCED",
        })
    unchecked = report.get("unchecked_segments")
    if not isinstance(unchecked, list):
        _fail("M3 unchecked segments accounting missing")
    output = {
        "contract": CONTRACT,
        "mode": "OFFLINE_DOCUMENTARY_REVIEW_QUEUE_NOT_LEGAL_VERDICT",
        "input_m3_report_sha256": _digest(json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")),
        "claims_queued": len(rows),
        "evidence_sections_listed": len(inventory),
        "unchecked_segments_count": len(unchecked),
        "counts": counts,
        "queue": rows,
        "coverage_exhaustive": False,
        "source_authenticity_independently_verified": False,
        "legal_support_assessed": False,
        "legal_applicability": "NOT_ASSESSED",
        "legal_accuracy_measured": False,
        "expert_gold_cases": 0,
        "rights_cleared": False,
        "network_used": False,
        "source_text_in_report": False,
        "client_text_in_report": False,
        "limitations": [
            "M3 quote matching is documentary only and does not establish legal entailment.",
            "Internal M3 report consistency does not authenticate external source material.",
            "Missing citations or unlinked evidence cannot establish legal falsity.",
            "No temporal applicability, precedent, exceptions, expert adjudication, or legal correctness assessed.",
            "No exhaustive legislation or jurisprudence coverage; CENDOJ is disabled.",
        ],
    }
    return output


def _no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReviewGateError("duplicate JSON field in local input")
        result[key] = value
    return result


def _read_file(path: Path, limit: int) -> bytes:
    """Bounded local read: disallow symlink final component and special files."""
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as f:
        info = os.fstat(f.fileno())
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
            raise ReviewGateError("local input must be a bounded regular file")
        data = f.read(limit + 1)
    if not 0 < len(data) <= limit:
        raise ReviewGateError("input exceeds size limit")
    return data


def _repo_root(path: Path) -> Path | None:
    base = path.resolve()
    return next((p for p in (base, *base.parents) if (p / ".git").exists()), None)


def _write_private(path: Path, content: dict) -> None:
    if not path.is_absolute() or path.exists() or path.is_symlink() or not path.parent.is_dir():
        raise ReviewGateError("output must be a new absolute file inside an existing directory")
    repos = {_repo_root(Path.cwd()), _repo_root(Path(__file__).resolve())}
    target = path.resolve(strict=False)
    if any(repo is not None and (target == repo or repo in target.parents) for repo in repos):
        raise ReviewGateError("do not write review artifacts into the Git repository")
    payload = (json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="M7-A offline documentary review queue, not legal truth")
    parser.add_argument("--text-file", required=True, type=Path)
    parser.add_argument("--evidence-json", type=Path, help="optional array of locally supplied LegalEvidence objects")
    parser.add_argument("--output", required=True, type=Path, help="new, private JSON file OUTSIDE Git")
    args = parser.parse_args(argv)
    try:
        text = _read_file(args.text_file, MAX_TEXT_BYTES).decode("utf-8")
        evidence = []
        if args.evidence_json is not None:
            from .evidence import LegalEvidence
            raw = json.loads(_read_file(args.evidence_json, MAX_EVIDENCE_BYTES).decode("utf-8"),
                             object_pairs_hook=_no_duplicate_keys)
            if not isinstance(raw, list) or len(raw) > 30:
                _fail("evidence JSON must be an array of at most 30 sections")
            for item in raw:
                if not isinstance(item, dict):
                    _fail("evidence array entry must be an object")
                allowed = {"source", "identifier", "section_id", "text", "official_url", "title",
                           "origin", "decision_date", "version_date", "retrieved_at"}
                if set(item) - allowed:
                    _fail("unknown evidence input field")
                entry = dict(item)
                entry["source"] = SourceKind(entry["source"])
                entry["origin"] = Origin.USER_SUPPLIED  # No promotion by user JSON.
                evidence.append(LegalEvidence(**entry))
        report = verify_argument(text, evidence)
        result = assess_report(report)
        _write_private(args.output, result)
        print(json.dumps({"mode": result["mode"], "claims_queued": result["claims_queued"],
                          "evidence_sections_listed": result["evidence_sections_listed"],
                          "legal_support_assessed": False, "output_created": True}, sort_keys=True))
        return 0
    except (OSError, ValueError, UnicodeError, TypeError, KeyError) as exc:
        # No private input text, source text or filename is copied to stderr.
        print(f"M7-A review error ({type(exc).__name__}); no legal verdict produced", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
