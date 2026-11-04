"""Only synthetic protocol fixtures: reviewer IDs are not real expert people."""
from __future__ import annotations

import copy
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from keepmehonest_legal_es.m4_review import CONTRACT as M4_CONTRACT
from keepmehonest_legal_es.m5_expert_review import (
    ADJUDICATION_CONTRACT, REVIEW_CONTRACT, ReviewError, _safe_json, _sha,
    prepare, review_plan, validate_submissions, main,
)
from keepmehonest_legal_es.m5_queue import validate_candidates

ROOT = Path(__file__).resolve().parents[2]


def fixture():
    corpus = json.loads((ROOT / "evals/legal_es/m5/pilot_candidates.json").read_text(encoding="utf-8"))
    c = corpus["cases"][0]
    cid = c["case_id"]
    argument = sha256(c["proposition"].encode()).hexdigest()
    evidence = sha256(b"SYNTHETIC UNIT TEST ONLY: not official evidence").hexdigest()
    pending = [{"contract": M4_CONTRACT, "case_id": cid, "source_kind": "BOE",
                "evidence_sha256": evidence, "argument_sha256": argument,
                "contains_confidential_data": False, "reuse_reviewed": True,
                "status": "PENDING_EXPERT", "reviewer_a": None, "reviewer_b": None,
                "adjudication": None}]
    receipt = {"case_id": cid, "official_url": c["source"]["official_url"],
               "section_id": c["source"]["section_id"], "evidence_sha256": evidence,
               "argument_sha256": argument, "capture_checked_by": "TEST_CAPTURE_REVIEWER",
               "capture_checked_on": "2026-11-04", "reuse_checked_by": "TEST_RIGHTS_REVIEWER",
               "reuse_checked_on": "2026-11-04", "reuse_basis_url": "https://www.boe.es/informacion/aviso_legal/",
               "license_scope": "INTERNAL_EXPERT_REVIEW_ONLY", "source_version_as_of": "2023-09-12",
               "decision_note": "SYNTHETIC UNIT TEST; no real source or permission review performed.",
               "not_gold": True, "original_capture_file": cid + ".txt"}
    receipts = {"contract": "keepmehonest-legal-es/m5-stage-receipts/v1",
                "note": "SYNTHETIC UNIT TEST ONLY; no actual clearance.", "staged_count": 1,
                "expert_gold_cases": 0, "legal_accuracy_measured": False, "receipts": [receipt]}
    return corpus, pending, receipts


def submitted_forms(folder):
    packet = json.loads((folder / "packet.json").read_text())
    a = json.loads((folder / "reviewer_a/assignment.json").read_text())
    b = json.loads((folder / "reviewer_b/assignment.json").read_text())
    adjud = json.loads((folder / "adjudication_template.json").read_text())
    d = date.today().isoformat()
    for role, doc in (("A", a), ("B", b)):
        r = doc["assessments"][0]
        r.update({"reviewer_id": "TEST_EXPERT_" + role, "reviewed_on": d,
                  "documentary_label": "UNDETERMINED",
                  "legal_support_label": "INSUFFICIENT_EVIDENCE",
                  "facts_available": False, "temporal_applicability_reviewed": False,
                  "reason": "Synthetic test: facts and publication context are not sufficient.",
                  "evidence_locator": "https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229#a24"})
    r = adjud["decisions"][0]
    r.update({"adjudicator_id": "TEST_ADJUDICATOR", "adjudicated_on": d,
              "documentary_label": "UNDETERMINED",
              "legal_support_label": "INSUFFICIENT_EVIDENCE", "conflicts_resolved": True,
              "reason": "Synthetic test: no expert review occurred, no legal inference allowed.",
              "evidence_locator": "https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229#a24"})
    return packet, a, b, adjud


class M5CReviewTests(unittest.TestCase):
    def setUp(self):
        self.corpus, self.pending, self.receipts = fixture()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.out = self.root / "packet"

    def prep(self):
        result = prepare(self.corpus, self.pending, self.receipts, self.out)
        self.assertEqual(result["expert_gold_cases"], 0)
        self.assertEqual(result["pending_cases"], 1)
        return submitted_forms(self.out)

    def test_plan_blocks_premature_review_claims(self):
        result = review_plan(self.corpus)
        self.assertEqual(result["candidates"], 36)
        self.assertEqual(result["reviewable_now"], 0)
        self.assertFalse(result["legal_accuracy_measured"])

    def test_prepare_produces_blank_separate_forms_not_gold(self):
        self.prep()
        raw = (self.out / "reviewer_a/assignment.json").read_text()
        self.assertIn('"reviewer_id": null', raw)
        self.assertNotIn("TEST_EXPERT_A", raw)
        self.assertEqual((self.out / "reviewer_a").stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.out / "packet.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.out / "reviewer_b/assignment.json").stat().st_mode & 0o777, 0o600)

    def test_no_pending_or_rights_gate_blocks(self):
        with self.assertRaises(ReviewError):
            prepare(self.corpus, [], self.receipts, self.out)
        receipt = copy.deepcopy(self.receipts)
        receipt["receipts"][0]["license_scope"] = "PUBLIC_REUSE_ALLOWED"
        with self.assertRaises(ReviewError):
            prepare(self.corpus, self.pending, receipt, self.out)

    def test_mismatched_source_or_argument_hash_fails_closed(self):
        receipt = copy.deepcopy(self.receipts)
        receipt["receipts"][0]["section_id"] = "a25"
        with self.assertRaises(ReviewError):
            prepare(self.corpus, self.pending, receipt, self.out)
        p = copy.deepcopy(self.pending)
        p[0]["argument_sha256"] = "0" * 64
        with self.assertRaises(ReviewError):
            prepare(self.corpus, p, self.receipts, self.out)

    def test_unsafe_or_existing_directory_not_replaced(self):
        self.prep()
        with self.assertRaises(ReviewError):
            prepare(self.corpus, self.pending, self.receipts, self.out)
        self.assertTrue((self.out / "packet.json").exists())

    def test_validate_complete_fixtures_never_awards_gold(self):
        packet, a, b, adjud = self.prep()
        records, report = validate_submissions(packet, a, b, adjud)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["status"], "ADJUDICATED")  # M4 structural schema only
        self.assertEqual(report["expert_gold_cases"], 0)
        self.assertFalse(report["human_identity_verified_by_software"])
        self.assertFalse(report["legal_accuracy_measured"])

    def test_blank_forms_not_silently_accepted(self):
        self.prep()
        packet = _safe_json(self.out / "packet.json")
        a = _safe_json(self.out / "reviewer_a/assignment.json")
        b = _safe_json(self.out / "reviewer_b/assignment.json")
        adjud = _safe_json(self.out / "adjudication_template.json")
        with self.assertRaises(ReviewError):
            validate_submissions(packet, a, b, adjud)

    def test_packet_content_tamper_rejected(self):
        packet, a, b, adjud = self.prep()
        packet["cases"][0]["proposition"] = "Altered proposition"
        with self.assertRaises(ReviewError):
            validate_submissions(packet, a, b, adjud)

    def test_packet_hash_or_case_hash_tamper_rejected(self):
        packet, a, b, adjud = self.prep()
        a["assessments"][0]["case_sha256"] = "0" * 64
        with self.assertRaises(ReviewError):
            validate_submissions(packet, a, b, adjud)

    def test_role_swap_rejected(self):
        packet, a, b, adjud = self.prep()
        with self.assertRaises(ReviewError):
            validate_submissions(packet, b, a, adjud)

    def test_same_reviewer_rejected(self):
        packet, a, b, adjud = self.prep()
        b["assessments"][0]["reviewer_id"] = a["assessments"][0]["reviewer_id"]
        with self.assertRaises(ReviewError):
            validate_submissions(packet, a, b, adjud)

    def test_adjudicator_same_as_reviewer_rejected(self):
        packet, a, b, adjud = self.prep()
        adjud["decisions"][0]["adjudicator_id"] = b["assessments"][0]["reviewer_id"]
        with self.assertRaises(ReviewError):
            validate_submissions(packet, a, b, adjud)

    def test_conclusion_without_facts_rejected(self):
        packet, a, b, adjud = self.prep()
        a["assessments"][0]["legal_support_label"] = "DIRECT_SUPPORT"
        with self.assertRaises(ReviewError):
            validate_submissions(packet, a, b, adjud)

    def test_unfinished_conflicts_rejected(self):
        packet, a, b, adjud = self.prep()
        a["assessments"][0]["legal_support_label"] = "PARTIAL_SUPPORT"
        adjud["decisions"][0]["conflicts_resolved"] = False
        with self.assertRaises(ReviewError):
            validate_submissions(packet, a, b, adjud)

    def test_submissions_report_disagreement_without_automatic_resolution(self):
        packet, a, b, adjud = self.prep()
        a["assessments"][0]["legal_support_label"] = "CONTEXT_DEPENDENT"
        records, report = validate_submissions(packet, a, b, adjud)
        self.assertEqual(report["reviewer_disagreements"], 1)
        self.assertEqual(records[0]["adjudication"]["legal_support_label"], "INSUFFICIENT_EVIDENCE")

    def test_no_network_or_model_in_workflow(self):
        from unittest.mock import patch
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            self.prep()
            packet, a, b, adjud = submitted_forms(self.out)
            _, report = validate_submissions(packet, a, b, adjud)
            self.assertFalse(report["legal_accuracy_measured"])

    def test_cli_plan_real_corpus(self):
        code = main(["plan", "--candidates", str(ROOT / "evals/legal_es/m5/pilot_candidates.json")])
        self.assertEqual(code, 0)

    def test_cli_validate_creates_private_unpublished_draft(self):
        packet, a, b, adjud = self.prep()
        for name, obj in (("a.json", a), ("b.json", b), ("adjud.json", adjud)):
            (self.root / name).write_text(json.dumps(obj), encoding="utf-8")
        code = main(["validate", "--packet", str(self.out / "packet.json"),
                     "--reviewer-a", str(self.root / "a.json"),
                     "--reviewer-b", str(self.root / "b.json"),
                     "--adjudication", str(self.root / "adjud.json"),
                     "--output-dir", str(self.root / "result")])
        self.assertEqual(code, 0)
        result = _safe_json(self.root / "result/structural_audit.json")
        self.assertEqual(result["expert_gold_cases"], 0)
        self.assertTrue((self.root / "result/m4_candidate_DO_NOT_PUBLISH.json").exists())


if __name__ == "__main__":
    unittest.main()
