"""M4 verifies a *synthetic* deterministic harness; never legal truth."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from hashlib import sha256

from keepmehonest_legal_es.citations import find_references
from keepmehonest_legal_es.evaluation import (
    EvaluationError, REPORT_CONTRACT, QUOTE_ANCHOR,
    _compare_report, corpus_fingerprint, read_corpus, run_corpus, validate_corpus,
)
from keepmehonest_legal_es.grounding import anchor_claim
from keepmehonest_legal_es.legal_context import screen_legal_scope
from keepmehonest_legal_es.m4_eval import main

CORPUS = Path(__file__).resolve().parents[2] / "evals" / "legal_es" / "m4" / "synthetic_cases.json"
HAS_CORE = importlib.util.find_spec("claims_verifier") is not None


def deterministic_component_runner(text, evidence):
    """Isolated regression adapter: exercises M3 components; NOT the Core extractor.

    The full Core integration is separately exercised in the user's fork.
    """
    if ", pero " in text:
        left, right = text.split(", pero ", 1)
        texts = [left, right]
    else:
        texts = [text]
    sentence_refs = {r.value for r in find_references(text)}
    results = []
    for claim in texts:
        own = {r.value for r in find_references(claim)}
        sentence_only = sorted(sentence_refs - own)
        context = {
            "context_status": "SENTENCE_MAPPED",
            "direct_identifiers": sorted(own),
            "sentence_only_identifiers": sentence_only,
            "inherit_documentary_anchor": False,
            "sibling_claim_numbers": [],
        }
        a = anchor_claim(claim, evidence)
        s = screen_legal_scope(claim, context, a, evidence)
        results.append({
            "claim": claim,
            "documentary_grounding": a,
            "sentence_context": context,
            "legal_scope_screen": s,
            "legal_support": "NOT_ASSESSED",
            "argument_quality": "NOT_ASSESSED",
        })
    return {
        "schema_version": REPORT_CONTRACT,
        "status": "READY_FOR_HUMAN_REVIEW" if evidence else "SOURCES_REQUIRED",
        "legal_interpretation": "NOT_ASSESSED",
        "legal_argument_quality": "NOT_ASSESSED",
        "claims": results,
        "evidence": [{"evidence_key": e.evidence_key} for e in evidence],
    }


class M4CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.corpus = read_corpus(CORPUS)

    def test_locked_corpus_valid_and_nonexpert(self):
        self.assertEqual(len(self.corpus["cases"]), 12)
        self.assertEqual(len({c["id"] for c in self.corpus["cases"]}), 12)
        self.assertTrue(all(c["expert_status"] == "NOT_EXPERT_REVIEWED" for c in self.corpus["cases"]))
        self.assertEqual(corpus_fingerprint(self.corpus), corpus_fingerprint(read_corpus(CORPUS)))

    def test_synthetic_components_all_pass_without_core(self):
        result = run_corpus(self.corpus, runner=deterministic_component_runner)
        self.assertEqual(result["cases_failed"], 0, result["results"])
        self.assertFalse(result["legal_accuracy_measured"])
        self.assertEqual(result["expert_gold_cases"], 0)
        self.assertEqual(result["counts"]["false_documentary_matches"], 0)

    def test_argument_tampering_rejected(self):
        data = copy.deepcopy(self.corpus)
        data["cases"][0]["argument"] += " cambiado"
        with self.assertRaisesRegex(EvaluationError, "digest"):
            validate_corpus(data)

    def test_evidence_tampering_rejected(self):
        data = copy.deepcopy(self.corpus)
        data["cases"][0]["evidence"][0]["text"] += " adulterado"
        with self.assertRaisesRegex(EvaluationError, "digest"):
            validate_corpus(data)

    def test_claim_order_or_text_changed_blocks_acceptance(self):
        data = self.corpus["cases"][10]
        report = deterministic_component_runner(data["argument"], [])
        # Manifest would differ if used empty evidence; test focuses on claim order.
        report["claims"].reverse()
        comparison = _compare_report(data, report)
        self.assertFalse(comparison["pass"])
        self.assertTrue(any("TEXT_OR_ORDER_CHANGED" in p for p in comparison["problems"]))

    def test_false_documentary_anchor_is_critical(self):
        data = self.corpus["cases"][1]  # quote that is NOT in the fake source
        from keepmehonest_legal_es.evidence import LegalEvidence, Origin, SourceKind
        sources = []
        for item in data["evidence"]:
            x = {k: v for k, v in item.items() if k != "text_sha256"}
            x["source"] = SourceKind(x["source"])
            x["origin"] = Origin.TEST_FIXTURE
            sources.append(LegalEvidence(**x))
        report = deterministic_component_runner(data["argument"], sources)
        report["claims"][0]["documentary_grounding"]["anchor_status"] = QUOTE_ANCHOR
        comparison = _compare_report(data, report)
        self.assertEqual(comparison["counts"]["false_documentary_matches"], 1)
        self.assertIn("CLAIM_1_FALSE_DOCUMENTARY_MATCH", comparison["problems"])

    def test_unearned_legal_support_is_blocked(self):
        data = self.corpus["cases"][3]
        report = deterministic_component_runner(data["argument"], [])
        report["claims"][0]["legal_support"] = "SUPPORTED"
        result = _compare_report(data, report)
        self.assertFalse(result["pass"])
        self.assertIn("CLAIM_1_UNSUPPORTED_LEGAL_CONCLUSION", result["problems"])

    def test_cannot_inherit_sibling_evidence(self):
        data = self.corpus["cases"][10]
        from keepmehonest_legal_es.evidence import LegalEvidence, Origin, SourceKind
        sources = []
        for raw in data["evidence"]:
            x = {k:v for k,v in raw.items() if k != "text_sha256"}
            x["source"] = SourceKind(x["source"])
            x["origin"] = Origin.TEST_FIXTURE
            sources.append(LegalEvidence(**x))
        r = deterministic_component_runner(data["argument"], sources)
        r["claims"][1]["sentence_context"]["inherit_documentary_anchor"] = True
        out = _compare_report(data, r)
        self.assertIn("CLAIM_2_UNSAFE_SOURCE_INHERITANCE", out["problems"])

    def test_missing_required_review_cue_is_error(self):
        data = self.corpus["cases"][5]  # absolute scope
        from keepmehonest_legal_es.evidence import LegalEvidence, Origin, SourceKind
        sources = []
        for raw in data["evidence"]:
            x = {k:v for k,v in raw.items() if k != "text_sha256"}
            x["source"] = SourceKind(x["source"])
            x["origin"] = Origin.TEST_FIXTURE
            sources.append(LegalEvidence(**x))
        r = deterministic_component_runner(data["argument"], sources)
        r["claims"][0]["legal_scope_screen"]["issues"] = []
        out = _compare_report(data, r)
        self.assertEqual(out["counts"]["review_cue_misses"], 1)

    def test_undocumented_official_origin_rejected(self):
        data = copy.deepcopy(self.corpus)
        data["cases"][0]["evidence"][0]["origin"] = "OFFICIAL_FETCH"
        with self.assertRaisesRegex(EvaluationError, "synthetic"):
            validate_corpus(data)

    def test_unreviewed_corpus_cannot_mark_expert(self):
        data = copy.deepcopy(self.corpus)
        data["cases"][0]["expert_status"] = "EXPERT_REVIEWED"
        with self.assertRaisesRegex(EvaluationError, "expert gold"):
            validate_corpus(data)

    def test_duplicate_case_id_rejected(self):
        data = copy.deepcopy(self.corpus)
        data["cases"][1]["id"] = data["cases"][0]["id"]
        with self.assertRaisesRegex(EvaluationError, "duplicate"):
            validate_corpus(data)

    def test_duplicate_json_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "dup.json"
            p.write_text('{"contract": "x", "contract": "y"}', encoding="utf-8")
            with self.assertRaisesRegex(EvaluationError, "duplicate JSON key"):
                read_corpus(p)

    def test_unexpected_field_rejected(self):
        data = copy.deepcopy(self.corpus)
        data["cases"][0]["confidence"] = 0.99
        with self.assertRaisesRegex(EvaluationError, "unexpected"):
            validate_corpus(data)

    def test_evidence_manifest_mismatch_is_error(self):
        data = self.corpus["cases"][0]
        from keepmehonest_legal_es.evidence import LegalEvidence, Origin, SourceKind
        raw = data["evidence"][0]
        x = {k:v for k,v in raw.items() if k != "text_sha256"}
        x["source"] = SourceKind(x["source"]);x["origin"] = Origin.TEST_FIXTURE
        report = deterministic_component_runner(data["argument"], [LegalEvidence(**x)])
        report["evidence"][0]["evidence_key"] = '0'*64
        out = _compare_report(data, report)
        self.assertIn("EVIDENCE_MANIFEST_MISMATCH", out["problems"])

    def test_cli_validate_without_core(self):
        self.assertEqual(main(["--corpus", str(CORPUS), "--validate-only"]), 0)

    @unittest.skipUnless(HAS_CORE, "full generic Claims Verifier Core is required")
    def test_offline_real_m3_runner(self):
        result = run_corpus(self.corpus)
        self.assertEqual(result["cases_failed"], 0, result["results"])
        self.assertEqual(result["counts"]["false_documentary_matches"], 0)
        self.assertEqual(result["counts"]["unassessed_legal_claims"], result["counts"]["claims"])


if __name__ == "__main__":
    unittest.main()
