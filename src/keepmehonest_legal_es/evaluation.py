"""M4: offline controlled regression evaluation, NOT legal accuracy certification.

This module intentionally does not import the generic Core or issue network calls
at import time. The synthetic corpus can be validated without the Core; executing
cases requires the complete user's fork. No external inference is used.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Callable

CONTRACT = "keepmehonest-legal-es/m4-synthetic-regression/v1"
REPORT_CONTRACT = "keepmehonest-legal-es/0.3.1"
CORPUS_LIMIT = 100
QUOTE_ANCHOR = "DOCUMENTARY_QUOTE_MATCH"
EXPECTED_ANCHORS = frozenset({
    QUOTE_ANCHOR, "NO_EXPLICIT_IDENTIFIER", "MULTIPLE_IDENTIFIERS_REQUIRE_MAPPING",
    "SOURCE_KIND_UNSUPPORTED", "SECTION_NOT_EXPLICITLY_IDENTIFIED",
    "SUBARTICLE_SCOPE_UNSUPPORTED", "MULTIPLE_SECTIONS_AMBIGUOUS",
    "CITED_SECTION_NOT_SUPPLIED", "MULTIPLE_EVIDENCE_VERSIONS_AMBIGUOUS",
    "SECTION_LOCATED_NO_EXPLICIT_QUOTATION", "SECTION_LOCATED_MULTIPLE_QUOTATIONS_AMBIGUOUS",
    "SECTION_LOCATED_QUOTATION_TOO_SHORT", "SECTION_LOCATED_QUOTATION_HAS_OMISSIONS",
    "QUOTED_PASSAGE_NOT_FOUND_IN_CITED_SECTION",
})


class EvaluationError(ValueError):
    """Invalid or unsafe corpus, incompatible report or evidence integrity."""


def _hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _keys(value: Any, required: set[str], optional: set[str] = frozenset(), *, path: str) -> None:
    if not isinstance(value, dict):
        raise EvaluationError(f"{path}: expected object")
    missing, extra = required - value.keys(), value.keys() - required - optional
    if missing or extra:
        raise EvaluationError(f"{path}: missing={sorted(missing)} unexpected={sorted(extra)}")


def validate_corpus(payload: Any) -> dict:
    """Strictly validate a small, public synthetic corpus without network or Core.

    The expected labels are developer-defined regression assertions, NOT expert
    annotation or evidence of real-world legal correctness.
    """
    _keys(payload, {"contract", "corpus_id", "kind", "cases"}, path="corpus")
    if payload["contract"] != CONTRACT or payload["kind"] != "SYNTHETIC_REGRESSION_ONLY":
        raise EvaluationError("only the M4 synthetic regression contract is accepted")
    cases = payload["cases"]
    if not isinstance(payload["corpus_id"], str) or not payload["corpus_id"].strip():
        raise EvaluationError("invalid corpus_id")
    if not isinstance(cases, list) or not 1 <= len(cases) <= CORPUS_LIMIT:
        raise EvaluationError(f"1..{CORPUS_LIMIT} cases required")
    seen = set()
    for index, case in enumerate(cases):
        path = f"cases[{index}]"
        _keys(case, {"id", "category", "argument", "argument_sha256", "evidence", "expected_claims",
                     "expert_status"}, path=path)
        cid = case["id"]
        if (not isinstance(cid, str) or not 3 <= len(cid) <= 64 or not all(
                c.isalnum() or c in "-_" for c in cid) or cid in seen):
            raise EvaluationError(f"{path}: duplicate or invalid case id")
        seen.add(cid)
        if case["expert_status"] != "NOT_EXPERT_REVIEWED":
            raise EvaluationError(f"{cid}: synthetic expectations cannot masquerade as expert gold")
        if not isinstance(case["category"], str) or not 3 <= len(case["category"]) <= 80:
            raise EvaluationError(f"{cid}: category is required")
        arg = case["argument"]
        if not isinstance(arg, str) or not arg.strip() or len(arg) > 4000 or _hash(arg) != case["argument_sha256"]:
            raise EvaluationError(f"{cid}: argument not identical to locked digest")
        items = case["evidence"]
        if not isinstance(items, list) or len(items) > 10:
            raise EvaluationError(f"{cid}: invalid evidence inventory")
        for k, item in enumerate(items):
            _keys(item, {"source", "identifier", "section_id", "text", "text_sha256", "official_url",
                         "title", "origin"}, {"version_date", "decision_date"}, path=f"{cid}.evidence[{k}]")
            if item["source"] not in ("BOE", "TC") or item["origin"] != "TEST_FIXTURE":
                raise EvaluationError(f"{cid}: only explicitly synthetic offline BOE/TC evidence allowed")
            if not isinstance(item["text"], str) or not item["text"].strip() or len(item["text"]) > 5000:
                raise EvaluationError(f"{cid}: evidence text missing or oversized")
            if not _is_digest(item["text_sha256"]) or _hash(item["text"]) != item["text_sha256"]:
                raise EvaluationError(f"{cid}: evidence text digest mismatch")
            if any(not isinstance(item[key], str) or not item[key].strip() for key in
                   ("identifier", "section_id", "official_url", "title")):
                raise EvaluationError(f"{cid}: invalid evidence fields")
        claims = case["expected_claims"]
        if not isinstance(claims, list) or not 1 <= len(claims) <= 8:
            raise EvaluationError(f"{cid}: expected_claims must have 1..8 entries")
        for ci, expected in enumerate(claims):
            _keys(expected, {"contains", "anchor_status", "required_issues", "forbidden_issues",
                             "sentence_only_identifiers"}, path=f"{cid}.expected_claims[{ci}]")
            if not isinstance(expected["contains"], str) or len(expected["contains"]) < 12:
                raise EvaluationError(f"{cid}: distinctive claim substring required")
            if expected["anchor_status"] not in EXPECTED_ANCHORS:
                raise EvaluationError(f"{cid}: unsupported expected anchor")
            for key in ("required_issues", "forbidden_issues", "sentence_only_identifiers"):
                values = expected[key]
                if (not isinstance(values, list) or len(values) > 20 or
                        any(not isinstance(v, str) or not v or len(v) > 160 for v in values) or
                        len(values) != len(set(values))):
                    raise EvaluationError(f"{cid}: invalid {key}")
            if set(expected["required_issues"]) & set(expected["forbidden_issues"]):
                raise EvaluationError(f"{cid}: issue both required and forbidden")
    return payload


def read_corpus(path: str | Path) -> dict:
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise EvaluationError("corpus is too large")
    try:
        # Reject duplicate object keys: they could silently change expected labels.
        def unique(pairs):
            item = {}
            for key, value in pairs:
                if key in item:
                    raise EvaluationError(f"duplicate JSON key: {key}")
                item[key] = value
            return item
        return validate_corpus(json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"invalid corpus JSON: {exc}") from exc


def corpus_fingerprint(payload: dict) -> str:
    return _hash(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def _compare_report(case: dict, report: dict) -> dict:
    """Compare M3 output against locked synthetic expectations; fail closed."""
    problems: list[str] = []
    counts = {"claims": 0, "exact_documentary_matches": 0, "false_documentary_matches": 0,
              "missed_documentary_matches": 0, "documentary_abstentions": 0,
              "review_cue_misses": 0, "forbidden_cues": 0, "unassessed_legal_claims": 0}
    claims = report.get("claims")
    if report.get("schema_version") != REPORT_CONTRACT:
        problems.append("REPORT_SCHEMA_MISMATCH")
    if report.get("status") not in ("READY_FOR_HUMAN_REVIEW", "SOURCES_REQUIRED"):
        problems.append("INVALID_WORKFLOW_STATE")
    if report.get("legal_interpretation") != "NOT_ASSESSED":
        problems.append("OVERCLAIMED_LEGAL_INTERPRETATION")
    if report.get("legal_argument_quality") != "NOT_ASSESSED":
        problems.append("OVERCLAIMED_ARGUMENT_QUALITY")
    if not isinstance(claims, list) or len(claims) != len(case["expected_claims"]):
        problems.append("CLAIM_COUNT_OR_MISSING_REPORT")
        claims = claims if isinstance(claims, list) else []
    for i, expected in enumerate(case["expected_claims"]):
        if i >= len(claims) or not isinstance(claims[i], dict):
            problems.append(f"CLAIM_{i+1}_MISSING")
            continue
        claim = claims[i]
        counts["claims"] += 1
        actual_text = claim.get("claim")
        grounding = claim.get("documentary_grounding")
        ctx = claim.get("sentence_context")
        screen = claim.get("legal_scope_screen")
        if not isinstance(actual_text, str) or expected["contains"] not in actual_text:
            problems.append(f"CLAIM_{i+1}_TEXT_OR_ORDER_CHANGED")
        if not isinstance(grounding, dict) or not isinstance(ctx, dict) or not isinstance(screen, dict):
            problems.append(f"CLAIM_{i+1}_MISSING_M3_COMPONENT")
            continue
        if grounding.get("claim_sha256") != _hash(actual_text if isinstance(actual_text, str) else ""):
            problems.append(f"CLAIM_{i+1}_DOCUMENTARY_HASH_MISMATCH")
        actual_anchor = grounding.get("anchor_status")
        expected_anchor = expected["anchor_status"]
        if actual_anchor == QUOTE_ANCHOR:
            counts["exact_documentary_matches"] += 1
        if actual_anchor == QUOTE_ANCHOR and expected_anchor != QUOTE_ANCHOR:
            counts["false_documentary_matches"] += 1
            problems.append(f"CLAIM_{i+1}_FALSE_DOCUMENTARY_MATCH")
        if actual_anchor != QUOTE_ANCHOR and expected_anchor == QUOTE_ANCHOR:
            counts["missed_documentary_matches"] += 1
            problems.append(f"CLAIM_{i+1}_MISSED_DOCUMENTARY_MATCH")
        if actual_anchor != expected_anchor:
            problems.append(f"CLAIM_{i+1}_ANCHOR_MISMATCH:{expected_anchor}!={actual_anchor}")
        else:
            if actual_anchor != QUOTE_ANCHOR:
                counts["documentary_abstentions"] += 1
        actual_identifiers = ctx.get("sentence_only_identifiers")
        if actual_identifiers != expected["sentence_only_identifiers"]:
            problems.append(f"CLAIM_{i+1}_CONTEXT_IDENTIFIERS_MISMATCH")
        if ctx.get("inherit_documentary_anchor") is not False:
            problems.append(f"CLAIM_{i+1}_UNSAFE_SOURCE_INHERITANCE")
        issues = screen.get("issues")
        if not isinstance(issues, list) or any(not isinstance(v, dict) for v in issues):
            problems.append(f"CLAIM_{i+1}_MALFORMED_ISSUES")
            continue
        codes = {v.get("code") for v in issues}
        missing = set(expected["required_issues"]) - codes
        forbidden = set(expected["forbidden_issues"]) & codes
        counts["review_cue_misses"] += len(missing)
        counts["forbidden_cues"] += len(forbidden)
        for value in sorted(missing):
            problems.append(f"CLAIM_{i+1}_REQUIRED_CUE_MISSING:{value}")
        for value in sorted(forbidden):
            problems.append(f"CLAIM_{i+1}_FORBIDDEN_CUE:{value}")
        if (claim.get("legal_support") != "NOT_ASSESSED" or
                grounding.get("legal_support") != "NOT_ASSESSED" or
                screen.get("legal_support") != "NOT_ASSESSED" or
                screen.get("legal_applicability") != "NOT_ASSESSED" or
                claim.get("argument_quality") != "NOT_ASSESSED"):
            problems.append(f"CLAIM_{i+1}_UNSUPPORTED_LEGAL_CONCLUSION")
        else:
            counts["unassessed_legal_claims"] += 1
    expected_keys = {
        # Evidence key is content-sensitive; never trust the cited URL alone.
        _evidence_key_from_payload(e) for e in case["evidence"]
    }
    found = report.get("evidence")
    actual_keys = {e.get("evidence_key") for e in found if isinstance(e, dict)} if isinstance(found, list) else set()
    if expected_keys != actual_keys or (isinstance(found, list) and len(found) != len(expected_keys)):
        problems.append("EVIDENCE_MANIFEST_MISMATCH")
    return {"case_id": case["id"], "pass": not problems, "problems": problems, "counts": counts,
            "workflow_status": report.get("status")}


def _evidence_key_from_payload(item: dict) -> str:
    # Use the same canonical key contract as M1 LegalEvidence, without importing
    # network clients or granting any origin-status upgrade.
    from .evidence import LegalEvidence, Origin, SourceKind
    data = {k: v for k, v in item.items() if k != "text_sha256"}
    data["source"] = SourceKind(data["source"])
    data["origin"] = Origin(data["origin"])
    return LegalEvidence(**data).evidence_key


def run_corpus(payload: dict, *, runner: Callable[[str, list], dict] | None = None) -> dict:
    """Run locked offline synthetic regressions; never a model benchmark.

    A runner may be injected for isolated unit tests; the default calls the
    published M3 verify_argument() function directly with TEST_FIXTURE sources.
    """
    validate_corpus(payload)
    from .evidence import LegalEvidence, Origin, SourceKind
    if runner is None:
        from .independent import verify_argument
        runner = lambda text, evidence: verify_argument(text, evidence)
    rows = []
    for case in payload["cases"]:
        evidence = []
        for item in case["evidence"]:
            data = {k: v for k, v in item.items() if k != "text_sha256"}
            data["source"] = SourceKind(data["source"])
            data["origin"] = Origin.TEST_FIXTURE
            evidence.append(LegalEvidence(**data))
        report = runner(case["argument"], evidence)
        if not isinstance(report, dict):
            raise EvaluationError(f"{case['id']}: runner did not return report object")
        rows.append(_compare_report(case, report))
    totals = {key: sum(r["counts"][key] for r in rows) for key in rows[0]["counts"]}
    failures = [row["case_id"] for row in rows if not row["pass"]]
    return {
        "contract": CONTRACT,
        "corpus_id": payload["corpus_id"],
        "corpus_sha256": corpus_fingerprint(payload),
        "kind": "SYNTHETIC_REGRESSION_ONLY",
        "cases_total": len(rows), "cases_passed": len(rows) - len(failures),
        "cases_failed": len(failures), "failed_case_ids": failures,
        "counts": totals, "results": rows,
        "expert_gold_cases": 0,
        "legal_accuracy_measured": False,
        "legal_support_accuracy_measured": False,
        "production_validated": False,
        "no_external_models_or_network_in_evaluator": True,
        "note": "Synthetic regression and documentary safety only; not real legal-quality evidence.",
    }
