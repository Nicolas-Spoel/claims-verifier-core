"""M7-A: synthetic offline tests; no legal gold labels or official-network access."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keepmehonest_legal_es.independent import REPORT_VERSION
from keepmehonest_legal_es.m7_review_gate import (
    CONTRACT, ReviewGateError, _no_duplicate_keys, _read_file, _write_private,
    assess_report, main,
)


def digest(s):
    return sha256(s.encode("utf-8")).hexdigest()


def synthetic_report(*, literal=True, with_evidence=True, scope=False, sibling=False):
    claim = ('El artículo 24 BOE-A-1978-31229 señala «Este ejemplo es artificial y no constituye un criterio legal» '
             'y siempre tiene una excepción.' if scope else
             'El artículo 24 BOE-A-1978-31229 dice «Este ejemplo es artificial y no constituye un criterio legal».')
    text = 'Este ejemplo es artificial y no constituye un criterio legal'
    source_sha = digest(text)
    evidence_key = digest('BOE\0BOE-A-1978-31229\0a24\0' + source_sha)
    evidence = [{
        "source": "BOE", "identifier": "BOE-A-1978-31229", "section_id": "a24",
        "sha256": source_sha, "evidence_key": evidence_key, "origin": "TEST_FIXTURE",
        "version_date": "1978-12-29",
    }] if with_evidence else []
    anchor_status = ('DOCUMENTARY_QUOTE_MATCH' if literal else 'QUOTED_PASSAGE_NOT_FOUND_IN_CITED_SECTION')
    issues = [
        {"code": ("EXACT_QUOTE_DOES_NOT_PROVE_PROPOSITION" if literal else
                  "DOCUMENTARY_SUPPORT_NOT_ESTABLISHED"), "basis": "M3A_ANCHOR"},
        {"code": "EVIDENCE_AUTHENTICITY_NOT_INDEPENDENTLY_VERIFIED", "basis": "EVIDENCE_PROVENANCE"},
    ]
    if scope:
        issues.append({"code": "ABSOLUTE_SCOPE_REQUIRES_REVIEW", "basis": "NONQUOTED_CLAIM_TEXT"})
    if sibling:
        issues.append({"code": "OTHER_CLAUSE_CITATION_NOT_INHERITED", "basis": "SENTENCE_CONTEXT"})
    record = {
        "claim": claim, "citations": ["BOE-A-1978-31229"],
        "lexical_verdict": "SUPPORTED",  # Intentionally adversarial Core label, ignored.
        "legal_support": "NOT_ASSESSED", "argument_quality": "NOT_ASSESSED",
        "review_status": "HUMAN_REVIEW_REQUIRED",
        "documentary_grounding": {
            "claim_sha256": digest(claim), "anchor_status": anchor_status,
            "source_identifier": "BOE-A-1978-31229", "cited_section_id": "a24",
            "evidence_key": evidence_key if with_evidence else None,
            "evidence_sha256": source_sha if with_evidence else None,
            "source_origin": "TEST_FIXTURE" if with_evidence else None,
            "quoted_passage_sha256": digest(text) if literal else None,
            "quoted_passage_characters": len(text) if literal else None,
            "quote_match_method": "LITERAL_NFC_WHITESPACE_ONLY" if literal else None,
            "review_flags": (["QUOTE_DOES_NOT_ESTABLISH_LEGAL_ENTAILMENT"] if literal else []),
            "legal_support": "NOT_ASSESSED", "legal_applicability": "NOT_ASSESSED",
            "requires_human_review": True,
        },
        "legal_scope_screen": {
            "screen_status": "HUMAN_LEGAL_REVIEW_REQUIRED", "issues": issues,
            "legal_support": "NOT_ASSESSED", "legal_applicability": "NOT_ASSESSED",
            "requires_human_review": True,
        },
        "sentence_context": {
            "context_status": "SENTENCE_MAPPED", "inherit_documentary_anchor": False,
            "sentence_only_identifiers": ["ECLI:ES:TC:2024:1"] if sibling else [],
        },
    }
    return {
        "schema_version": REPORT_VERSION,
        "status": "READY_FOR_HUMAN_REVIEW" if with_evidence else "SOURCES_REQUIRED",
        "legal_interpretation": "NOT_ASSESSED", "legal_argument_quality": "NOT_ASSESSED",
        "coverage": {"corpus_completeness": "UNVERIFIABLE",
                     "ordinary_court_search": "NOT_PERFORMED_CENDOJ_DISABLED",
                     "general_case_law_search": "NOT_PERFORMED"},
        "evidence": evidence, "claims": [record], "unchecked_segments": [],
    }


class GateNormalCases(unittest.TestCase):
    def test_contract_and_workflow(self):
        got = assess_report(synthetic_report())
        self.assertEqual(got["contract"], CONTRACT)
        self.assertEqual(got["mode"], "OFFLINE_DOCUMENTARY_REVIEW_QUEUE_NOT_LEGAL_VERDICT")

    def test_literal_not_legal_support(self):
        got = assess_report(synthetic_report())
        self.assertEqual(got["counts"]["literal_quote_located"], 1)
        self.assertEqual(got["queue"][0]["documentary_workflow"], "LITERAL_QUOTE_LOCATED_NOT_LEGAL_SUPPORT")
        self.assertEqual(got["queue"][0]["legal_truth_verdict"], "NOT_PRODUCED")
        self.assertFalse(got["legal_support_assessed"])

    def test_lexical_supported_not_inherited(self):
        got = assess_report(synthetic_report())
        self.assertNotIn("SUPPORTED", json.dumps(got))
        self.assertTrue(got["queue"][0]["human_review_required"])

    def test_no_raw_text_or_title(self):
        got = assess_report(synthetic_report())
        out = json.dumps(got, ensure_ascii=False)
        self.assertNotIn("Este ejemplo es artificial", out)
        self.assertNotIn("BOE-A-1978-31229", out)

    def test_hash_is_stable(self):
        r = synthetic_report()
        self.assertEqual(assess_report(r), assess_report(deepcopy(r)))

    def test_no_evidence_always_abstains(self):
        r = synthetic_report(with_evidence=False, literal=False)
        r["claims"][0]["documentary_grounding"]["anchor_status"] = "CITED_SECTION_NOT_SUPPLIED"
        got = assess_report(r)
        self.assertEqual(got["evidence_sections_listed"], 0)
        self.assertEqual(got["counts"]["citation_or_section_unresolved"], 1)

    def test_quote_mismatch_is_not_falsity(self):
        got = assess_report(synthetic_report(literal=False))
        self.assertEqual(got["counts"]["quote_discrepancies"], 1)
        self.assertEqual(got["queue"][0]["legal_truth_verdict"], "NOT_PRODUCED")

    def test_section_no_quote_is_review(self):
        r = synthetic_report(literal=False)
        r["claims"][0]["documentary_grounding"]["anchor_status"] = "SECTION_LOCATED_NO_EXPLICIT_QUOTATION"
        got = assess_report(r)
        self.assertEqual(got["counts"]["section_without_quote"], 1)

    def test_absolute_scope_flag(self):
        got = assess_report(synthetic_report(scope=True))
        self.assertEqual(got["counts"]["claims_with_scope_flags"], 1)
        self.assertIn("ABSOLUTE_SCOPE_REQUIRES_REVIEW", got["queue"][0]["scope_review_signal_codes"])

    def test_sibling_citation_flag(self):
        got = assess_report(synthetic_report(sibling=True))
        self.assertEqual(got["counts"]["claims_with_unsupported_sentence_citation"], 1)
        self.assertTrue(got["queue"][0]["sibling_citation_not_inherited"])

    def test_no_claims(self):
        r = synthetic_report()
        r["claims"] = []
        r["status"] = "NO_CHECKABLE_CLAIMS"
        got = assess_report(r)
        self.assertEqual(got["claims_queued"], 0)
        self.assertEqual(got["queue"], [])

    def test_unchecked_segment_not_transmitted(self):
        r = synthetic_report()
        r["unchecked_segments"] = [{"text": "SECRETO_NO_COPIAR", "reason": "skip"}]
        got = assess_report(r)
        self.assertEqual(got["unchecked_segments_count"], 1)
        self.assertNotIn("SECRETO_NO_COPIAR", json.dumps(got))

    def test_zero_gold_and_rights(self):
        got = assess_report(synthetic_report())
        self.assertEqual(got["expert_gold_cases"], 0)
        self.assertFalse(got["rights_cleared"])
        self.assertFalse(got["coverage_exhaustive"])
        self.assertFalse(got["network_used"])


class GateAdversarialCases(unittest.TestCase):
    def check_reject(self, edit):
        r = synthetic_report()
        edit(r)
        with self.assertRaises(ReviewGateError):
            assess_report(r)

    def test_wrong_contract(self):
        self.check_reject(lambda r: r.update(schema_version="other"))

    def test_overclaimed_legal_interpretation(self):
        self.check_reject(lambda r: r.update(legal_interpretation="SUPPORTED"))

    def test_false_exhaustiveness(self):
        self.check_reject(lambda r: r["coverage"].update(corpus_completeness="COMPLETE"))

    def test_malicious_evidence_key(self):
        self.check_reject(lambda r: r["evidence"][0].update(evidence_key="0"*64))

    def test_duplicate_evidence_key(self):
        self.check_reject(lambda r: r["evidence"].append(dict(r["evidence"][0])))

    def test_wrong_claim_hash(self):
        self.check_reject(lambda r: r["claims"][0]["documentary_grounding"].update(claim_sha256="f"*64))

    def test_unlisted_link(self):
        self.check_reject(lambda r: r["claims"][0]["documentary_grounding"].update(evidence_key="f"*64))

    def test_mismatched_source_origin(self):
        self.check_reject(lambda r: r["claims"][0]["documentary_grounding"].update(source_origin="OFFICIAL_FETCH"))

    def test_wrong_section_lineage(self):
        self.check_reject(lambda r: r["claims"][0]["documentary_grounding"].update(cited_section_id="a25"))

    def test_missing_literal_provenance(self):
        self.check_reject(lambda r: r["claims"][0]["documentary_grounding"].update(quote_match_method=None))

    def test_overclaimed_claim_support(self):
        self.check_reject(lambda r: r["claims"][0].update(legal_support="SUPPORTED"))

    def test_quote_inherited_from_sibling(self):
        self.check_reject(lambda r: r["claims"][0]["sentence_context"].update(inherit_documentary_anchor=True))

    def test_unknown_issue_rejected(self):
        self.check_reject(lambda r: r["claims"][0]["legal_scope_screen"]["issues"].append({"code":"CLIENT_NAME", "basis": "name"}))

    def test_duplicate_issue_rejected(self):
        self.check_reject(lambda r: r["claims"][0]["legal_scope_screen"]["issues"].append(dict(r["claims"][0]["legal_scope_screen"]["issues"][0])))

    def test_sibling_without_review_flag(self):
        self.check_reject(lambda r: r["claims"][0]["sentence_context"].update(sentence_only_identifiers=["ECLI:ES:TC:2024:1"]))

    def test_no_claims_status_inconsistent(self):
        self.check_reject(lambda r: r.update(status="NO_CHECKABLE_CLAIMS"))

    def test_massive_claims_inconsistent(self):
        self.check_reject(lambda r: r.update(claims=r["claims"] * 301))


class FullCoreIntegration(unittest.TestCase):
    def test_offline_m3_to_m7_pipeline(self):
        import importlib.util
        if importlib.util.find_spec("claims_verifier") is None:
            self.skipTest("generic Core unavailable in isolated reconstruction")
        from keepmehonest_legal_es.evidence import LegalEvidence, Origin, SourceKind
        from keepmehonest_legal_es.independent import verify_argument
        source = LegalEvidence(
            source=SourceKind.BOE, identifier="BOE-A-1978-31229", section_id="a24",
            text="Este ejemplo es artificial y no constituye un criterio legal",
            official_url="https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229#a24",
            title="Ejemplo sintético", origin=Origin.TEST_FIXTURE, version_date="1978-12-29",
        )
        claim = ('El art. 24 BOE-A-1978-31229 dice '
                 '«Este ejemplo es artificial y no constituye un criterio legal».')
        got = assess_report(verify_argument(claim, [source]))
        self.assertGreaterEqual(got["claims_queued"], 1)
        self.assertFalse(got["legal_support_assessed"])
        self.assertTrue(all(row["human_review_required"] for row in got["queue"]))


class CLISecurityTests(unittest.TestCase):
    def test_duplicate_keys_rejected(self):
        with self.assertRaises(ReviewGateError):
            json.loads('{"a":1,"a":2}', object_pairs_hook=_no_duplicate_keys)

    def test_read_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)/"real.txt"
            p.write_text("synthetic", encoding="utf-8")
            link = Path(directory)/"link.txt"
            link.symlink_to(p)
            with self.assertRaises(OSError):
                _read_file(link, 100)

    def test_private_report_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"review.json"
            _write_private(path, {"synthetic": True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ReviewGateError):
                _write_private(path, {"synthetic": True})

    def test_output_refuses_repo(self):
        from keepmehonest_legal_es.m7_review_gate import _repo_root
        repo = _repo_root(Path.cwd())
        if repo is None:
            self.skipTest("no repository root in this reconstructed context")
        with self.assertRaises(ReviewGateError):
            _write_private(repo/"M7A_SENSITIVE.json", {"synthetic": True})

    def test_cli_no_external_network_and_no_text_stdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"arg.txt").write_text("Un texto ficticio para revisión documental.", encoding="utf-8")
            output = root/"report.json"
            r = synthetic_report()
            with patch("keepmehonest_legal_es.m7_review_gate.verify_argument", return_value=r), patch("builtins.print") as printed:
                self.assertEqual(main(["--text-file", str(root/"arg.txt"), "--output", str(output)]), 0)
            self.assertTrue(output.is_file())
            serialized = output.read_text(encoding="utf-8")
            self.assertNotIn("Este ejemplo es artificial", serialized)
            self.assertTrue(printed.called)

    def test_cli_user_cannot_spoof_official_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"arg.txt").write_text("Texto de prueba.", encoding="utf-8")
            evidence = [{
                "source": "BOE", "identifier": "BOE-A-1978-31229", "section_id": "a24",
                "text": "Texto completamente sintético de prueba.",
                "official_url": "https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229#a24",
                "title": "Ejemplo", "origin": "OFFICIAL_FETCH", "version_date": "1978-12-29",
                "retrieved_at": "2026-11-04T10:00:00+00:00",
            }]
            (root/"evidence.json").write_text(json.dumps(evidence), encoding="utf-8")
            def check_report(text, sources):
                self.assertEqual(len(sources), 1)
                self.assertEqual(sources[0].origin.value, "USER_SUPPLIED")
                return synthetic_report()
            with patch("keepmehonest_legal_es.m7_review_gate.verify_argument", side_effect=check_report):
                self.assertEqual(main(["--text-file", str(root/"arg.txt"),
                                       "--evidence-json", str(root/"evidence.json"),
                                       "--output", str(root/"review.json")]), 0)

    def test_cli_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"arg.txt").write_text("Texto de prueba.", encoding="utf-8")
            path = root/"report.json"
            path.write_text("old contents", encoding="utf-8")
            with patch("keepmehonest_legal_es.m7_review_gate.verify_argument", return_value=synthetic_report()):
                self.assertEqual(main(["--text-file", str(root/"arg.txt"), "--output", str(path)]), 2)
            self.assertEqual(path.read_text(encoding="utf-8"), "old contents")


if __name__ == "__main__":
    unittest.main()
