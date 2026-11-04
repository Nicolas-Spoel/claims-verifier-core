"""M5 tests use fake human attestations ONLY as controlled fixtures, never gold."""
from __future__ import annotations

import copy
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keepmehonest_legal_es.m4_review import summarize_review_queue
from keepmehonest_legal_es.m5_queue import (
    CAPTURE_CONTRACT, QueueError, _read_json, main,
    stage_pending, validate_candidates,
)

ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = ROOT / "evals/legal_es/m5/pilot_candidates.json"
TEMPLATE = ROOT / "evals/legal_es/m5/capture_attestations_TEMPLATE.json"


def corpus():
    return json.loads(CANDIDATES.read_text(encoding="utf-8"))


def approved_test_attestation(case):
    s = case["source"]
    return {
        "case_id": case["case_id"], "capture_file": case["case_id"] + ".txt",
        "kind": s["kind"], "identifier": s["identifier"],
        "section_id": s["section_id"], "official_url": s["official_url"],
        "capture_checked_by": "TEST-fixture-checker-A",
        "capture_checked_on": date.today().isoformat(),
        "reuse_checked_by": "TEST-fixture-checker-B",
        "reuse_checked_on": date.today().isoformat(),
        "reuse_basis_url": "https://www.boe.es/informacion/aviso_legal/",
        "license_scope": "INTERNAL_EXPERT_REVIEW_ONLY",
        "source_version_as_of": "2024-01-15",
        "no_confidential_data_verified": True,
        "source_publication_checked": True,
        "decision_note": "SIMULATED TEST FIXTURE, NOT A REAL SOURCE OR RIGHTS VERIFICATION",
    }


class M5CandidateTests(unittest.TestCase):
    def setUp(self):
        self.c = corpus()

    def test_inventory_has_36_unannotated_public_candidates(self):
        r = validate_candidates(self.c)
        self.assertEqual(r["total_candidates"], 36)
        self.assertEqual(r["unique_source_section_clusters"], 13)
        self.assertFalse(r["independent_case_sample_claimed"])
        self.assertEqual(r["expert_gold_cases"], 0)
        self.assertFalse(r["legal_accuracy_measured"])
        self.assertEqual(r["source_snapshots_included"], 0)
        self.assertEqual(r["rights_cleared"], 0)
        self.assertEqual(len(r["areas"]), 5)
        self.assertEqual(len(r["stress_dimensions"]), 7)

    def test_no_genuine_copies_or_personal_case_details_in_corpus_fields(self):
        for c in self.c["cases"]:
            self.assertEqual(c["origin"], "AI_DRAFT_HYPOTHETICAL_PUBLIC_LOCATOR")
            self.assertFalse(c["has_confidential_data"])
            self.assertIsNone(c["expert_label"])
            self.assertIsNone(c["evidence_sha256"])
            self.assertFalse(c["reuse_reviewed"])

    def test_reject_duplicate_case_id(self):
        self.c["cases"][1]["case_id"] = self.c["cases"][0]["case_id"]
        with self.assertRaisesRegex(QueueError, "duplicate"): validate_candidates(self.c)

    def test_reject_duplicate_proposition(self):
        self.c["cases"][1]["proposition"] = self.c["cases"][0]["proposition"]
        with self.assertRaisesRegex(QueueError, "duplicate"): validate_candidates(self.c)

    def test_reject_hidden_label(self):
        self.c["cases"][0]["expert_label"] = "DIRECT_SUPPORT"
        with self.assertRaises(QueueError): validate_candidates(self.c)

    def test_reject_rights_cleared_without_capture(self):
        self.c["cases"][0]["reuse_reviewed"] = True
        with self.assertRaises(QueueError): validate_candidates(self.c)

    def test_reject_confidential_candidate(self):
        self.c["cases"][0]["has_confidential_data"] = True
        with self.assertRaises(QueueError): validate_candidates(self.c)

    def test_reject_bogus_https_host(self):
        self.c["cases"][0]["source"]["official_url"] = "https://www.boe.es.evil.example/buscar/act.php?id=BOE-A-1978-31229"
        with self.assertRaises(QueueError): validate_candidates(self.c)

    def test_reject_https_userinfo(self):
        self.c["cases"][0]["source"]["official_url"] = "https://www.boe.es@evil.example/buscar/act.php?id=BOE-A-1978-31229"
        with self.assertRaises(QueueError): validate_candidates(self.c)

    def test_reject_wrong_boe_section_format(self):
        self.c["cases"][0]["source"]["section_id"] = "FJ1"
        with self.assertRaises(QueueError): validate_candidates(self.c)

    def test_reject_incorrect_tc_hj_link(self):
        self.c["cases"][-1]["source"]["official_url"] = "https://hj.tribunalconstitucional.es/HJ/es/Resolucion/Show/30063"
        with self.assertRaises(QueueError): validate_candidates(self.c)

    def test_reject_cendoj_source(self):
        self.c["cases"][-1]["source"]["kind"] = "CENDOJ"
        with self.assertRaises(QueueError): validate_candidates(self.c)

    def test_reject_future_event(self):
        self.c["cases"][0]["event_date"] = "2099-11-02"
        with self.assertRaises(QueueError): validate_candidates(self.c)

    def test_reject_missing_case_field(self):
        del self.c["cases"][0]["status"]
        with self.assertRaises(QueueError): validate_candidates(self.c)

    def test_reject_extra_case_field(self):
        self.c["cases"][0]["legal_verdict"] = "TRUE"
        with self.assertRaises(QueueError): validate_candidates(self.c)

    def test_reject_29_cases(self):
        self.c["cases"] = self.c["cases"][:29]
        with self.assertRaises(QueueError): validate_candidates(self.c)

    def test_reject_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bad.json"
            path.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaises(QueueError): _read_json(path)

    def test_template_is_deliberately_not_stageable(self):
        payload = _read_json(TEMPLATE)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(QueueError): stage_pending(self.c, payload, Path(d))

    def test_cli_validation_is_offline(self):
        with patch("socket.create_connection", side_effect=AssertionError("NETWORK FORBIDDEN")):
            self.assertEqual(main(["--candidates", str(CANDIDATES)]), 0)


class M5StageTests(unittest.TestCase):
    def setUp(self):
        self.c = corpus()
        self.case = self.c["cases"][0]
        self.att = approved_test_attestation(self.case)
        self.manifest = {"contract": CAPTURE_CONTRACT, "attestations": [self.att]}
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.snapshots = self.root / "captures"
        self.snapshots.mkdir()
        self.data = ("TEST FIXTURE ONLY. NOT OFFICIAL EVIDENCE. " * 5).encode("utf-8")
        (self.snapshots / self.att["capture_file"]).write_bytes(self.data)

    def tearDown(self):
        self.tmp.cleanup()

    def test_stage_produces_only_pending_expert_m4_records(self):
        stage, receipts = stage_pending(self.c, self.manifest, self.snapshots)
        self.assertEqual(summarize_review_queue(stage)["pending"], 1)
        self.assertEqual(summarize_review_queue(stage)["adjudicated"], 0)
        self.assertEqual(stage[0]["evidence_sha256"], sha256(self.data).hexdigest())
        self.assertEqual(stage[0]["argument_sha256"], sha256(self.case["proposition"].encode()).hexdigest())
        self.assertIsNone(stage[0]["reviewer_a"])
        self.assertIsNone(stage[0]["adjudication"])
        self.assertFalse(receipts["legal_accuracy_measured"])
        self.assertTrue(receipts["receipts"][0]["not_gold"])

    def test_changed_snapshot_changes_evidence_hash(self):
        previous = stage_pending(self.c, self.manifest, self.snapshots)[0][0]["evidence_sha256"]
        (self.snapshots / self.att["capture_file"]).write_bytes(self.data + b"change")
        current = stage_pending(self.c, self.manifest, self.snapshots)[0][0]["evidence_sha256"]
        self.assertNotEqual(previous, current)

    def test_missing_version_as_of_fails(self):
        self.att["source_version_as_of"] = None
        with self.assertRaises(QueueError): stage_pending(self.c, self.manifest, self.snapshots)

    def test_wrong_source_identifier_fails(self):
        self.att["identifier"] = "BOE-A-1978-30000"
        with self.assertRaises(QueueError): stage_pending(self.c, self.manifest, self.snapshots)

    def test_refuse_undeclared_rights(self):
        self.att["reuse_checked_by"] = None
        with self.assertRaises(QueueError): stage_pending(self.c, self.manifest, self.snapshots)

    def test_refuse_same_capture_and_rights_reviewer(self):
        self.att["capture_checked_by"] = self.att["reuse_checked_by"]
        with self.assertRaises(QueueError): stage_pending(self.c, self.manifest, self.snapshots)

    def test_refuse_noninternal_license_scope(self):
        self.att["license_scope"] = "PUBLIC_COMMERCIAL_USE"
        with self.assertRaises(QueueError): stage_pending(self.c, self.manifest, self.snapshots)

    def test_refuse_confidential_snapshot(self):
        self.att["no_confidential_data_verified"] = False
        with self.assertRaises(QueueError): stage_pending(self.c, self.manifest, self.snapshots)

    def test_refuse_missing_publication_review(self):
        self.att["source_publication_checked"] = False
        with self.assertRaises(QueueError): stage_pending(self.c, self.manifest, self.snapshots)

    def test_refuse_nonexistent_snapshot(self):
        (self.snapshots / self.att["capture_file"]).unlink()
        with self.assertRaises(QueueError): stage_pending(self.c, self.manifest, self.snapshots)

    def test_refuse_wrong_filename(self):
        self.att["capture_file"] = "../../secret.txt"
        with self.assertRaises(QueueError): stage_pending(self.c, self.manifest, self.snapshots)

    def test_refuse_capture_symlink(self):
        p = self.snapshots / self.att["capture_file"]
        p.unlink()
        p.symlink_to(self.root / "other.txt")
        with self.assertRaises(QueueError): stage_pending(self.c, self.manifest, self.snapshots)

    def test_refuse_duplicate_attestations(self):
        self.manifest["attestations"] = [self.att, copy.deepcopy(self.att)]
        with self.assertRaises(QueueError): stage_pending(self.c, self.manifest, self.snapshots)

    def test_cli_creates_private_m4_pending_packet(self):
        path = self.root / "att.json"
        path.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")
        target = self.root / "staged"
        with patch("socket.create_connection", side_effect=AssertionError("NETWORK FORBIDDEN")):
            self.assertEqual(main(["--candidates", str(CANDIDATES), "--stage-manifest", str(path),
                                   "--capture-root", str(self.snapshots), "--output-dir", str(target)]), 0)
        self.assertTrue((target / "m4_pending_reviews.json").exists())
        self.assertTrue((target / "m5_capture_receipts.json").exists())
        self.assertEqual(summarize_review_queue(json.loads((target/"m4_pending_reviews.json").read_text()))["pending"], 1)

    def test_existing_output_dir_not_overwritten(self):
        path = self.root / "att.json"
        path.write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaises(QueueError):  # staging function itself does not touch output
            bad = copy.deepcopy(self.manifest)
            bad["attestations"][0]["capture_file"] = "wrong.txt"
            stage_pending(self.c, bad, self.snapshots)
        self.assertEqual(main(["--candidates", str(CANDIDATES), "--stage-manifest", str(path),
                               "--capture-root", str(self.snapshots), "--output-dir", str(self.root)]), 2)


if __name__ == "__main__":
    unittest.main()
