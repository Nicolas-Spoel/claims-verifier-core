"""M7-B offline synthetic/adversarial tests; no legal labels, HTTP or external model."""
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
from keepmehonest_legal_es.m7_review_gate import ReviewGateError
from keepmehonest_legal_es.m7_documentary_gaps import (
    CONTRACT, assess_documentary_gaps, main,
)

SECRET = "CONFIDENTIAL_CLIENT_EXAMPLE_NEVER_EMIT"
BOE = "BOE-A-1978-31229"  # Fixture identifier only, not a substantive quote.


def h(text):
    return sha256(text.encode("utf-8")).hexdigest()


def evidence(*, identifier=BOE, source="BOE", section="a24", version="2024-01-01",
             decision=None, text="Fictitious quotation" , origin="TEST_FIXTURE"):
    digest = h(text)
    key = h(f"{source}\0{identifier}\0{section}\0{digest}")
    return {
        "source": source, "identifier": identifier, "section_id": section,
        "sha256": digest, "evidence_key": key, "origin": origin,
        "version_date": version, "decision_date": decision,
    }


def report(*, status="DOCUMENTARY_QUOTE_MATCH", source_present=True):
    quote = "Este texto es completamente ficticio y no constituye legislación real"
    claim = f"El art. 24 {BOE} dice «{quote}». {SECRET}"
    ev = evidence(text=quote)
    linked = source_present and status not in {
        "NO_EXPLICIT_IDENTIFIER", "SECTION_NOT_EXPLICITLY_IDENTIFIED",
        "CITED_SECTION_NOT_SUPPLIED", "MULTIPLE_EVIDENCE_VERSIONS_AMBIGUOUS",
    }
    return {
        "schema_version": REPORT_VERSION,
        "status": "READY_FOR_HUMAN_REVIEW" if source_present else "SOURCES_REQUIRED",
        "legal_interpretation": "NOT_ASSESSED", "legal_argument_quality": "NOT_ASSESSED",
        "coverage": {
            "corpus_completeness": "UNVERIFIABLE",
            "ordinary_court_search": "NOT_PERFORMED_CENDOJ_DISABLED",
            "general_case_law_search": "NOT_PERFORMED",
        },
        "evidence": [ev] if source_present else [],
        "claims": [{
            "claim": claim, "lexical_verdict": "SUPPORTED", "legal_support": "NOT_ASSESSED",
            "argument_quality": "NOT_ASSESSED", "review_status": "HUMAN_REVIEW_REQUIRED",
            "documentary_grounding": {
                "claim_sha256": h(claim), "anchor_status": status,
                "source_identifier": BOE if status != "NO_EXPLICIT_IDENTIFIER" else None,
                "cited_section_id": "a24" if status != "SECTION_NOT_EXPLICITLY_IDENTIFIED" else None,
                "evidence_key": ev["evidence_key"] if linked else None,
                "evidence_sha256": ev["sha256"] if linked else None,
                "source_origin": ev["origin"] if linked else None,
                "quoted_passage_sha256": h(quote) if status == "DOCUMENTARY_QUOTE_MATCH" else None,
                "quoted_passage_characters": len(quote) if status == "DOCUMENTARY_QUOTE_MATCH" else None,
                "quote_match_method": "LITERAL_NFC_WHITESPACE_ONLY" if status == "DOCUMENTARY_QUOTE_MATCH" else None,
                "review_flags": ["QUOTE_DOES_NOT_ESTABLISH_LEGAL_ENTAILMENT"] if status == "DOCUMENTARY_QUOTE_MATCH" else [],
                "legal_support": "NOT_ASSESSED", "legal_applicability": "NOT_ASSESSED",
                "requires_human_review": True,
            },
            "sentence_context": {
                "inherit_documentary_anchor": False, "sentence_only_identifiers": [],
            },
            "legal_scope_screen": {
                "screen_status": "HUMAN_LEGAL_REVIEW_REQUIRED",
                "issues": [{"code": "EVIDENCE_AUTHENTICITY_NOT_INDEPENDENTLY_VERIFIED"}],
                "legal_support": "NOT_ASSESSED", "legal_applicability": "NOT_ASSESSED",
                "requires_human_review": True,
            },
        }],
        "unchecked_segments": [{"text": SECRET, "reason": "synthetic_omission"}],
    }


class M7BDocumentaryWorkflow(unittest.TestCase):
    def test_version_and_mode(self):
        o = assess_documentary_gaps(report())
        self.assertEqual(o["contract"], CONTRACT)
        self.assertEqual(o["mode"], "OFFLINE_DOCUMENTARY_GAPS_AND_SNAPSHOT_DIVERGENCE_NOT_LEGAL_VERDICT")

    def test_quote_is_documentary_only(self):
        o = assess_documentary_gaps(report())
        self.assertEqual(o["queue"][0]["documentary_review_stage"], "QUOTE_LOCATED_DOCUMENTARY_ONLY")
        self.assertEqual(o["counts"]["literal_quotes_located_documentary_only"], 1)
        self.assertEqual(o["queue"][0]["documentary_sufficiency"], "NOT_DETERMINED")
        self.assertFalse(o["legal_support_assessed"])

    def test_mismatch_is_not_legal_falsity(self):
        o = assess_documentary_gaps(report(status="QUOTED_PASSAGE_NOT_FOUND_IN_CITED_SECTION"))
        self.assertIn("QUOTATION_DISCREPANCY_NOT_LEGAL_FALSITY", o["queue"][0]["review_reason_codes"])
        self.assertEqual(o["queue"][0]["legal_truth_verdict"], "NOT_PRODUCED")

    def test_cited_section_without_quote(self):
        o = assess_documentary_gaps(report(status="SECTION_LOCATED_NO_EXPLICIT_QUOTATION"))
        self.assertEqual(o["counts"]["section_without_verifiable_quote"], 1)

    def test_missing_citation_no_negative_inference(self):
        o = assess_documentary_gaps(report(status="NO_EXPLICIT_IDENTIFIER", source_present=False))
        self.assertEqual(o["counts"]["unresolved_citations_or_sections"], 1)
        self.assertIn("SOURCE_OR_SECTION_COVERAGE_GAP_NOT_LEGAL_FALSITY", o["queue"][0]["review_reason_codes"])

    def test_missing_section_in_supplied_evidence(self):
        o = assess_documentary_gaps(report(status="CITED_SECTION_NOT_SUPPLIED", source_present=False))
        self.assertEqual(o["queue"][0]["documentary_review_stage"], "CITATION_OR_SECTION_MISSING_OR_AMBIGUOUS")

    def test_boe_temporal_review_never_claims_vigencia(self):
        o = assess_documentary_gaps(report())
        self.assertIn("BOE_TEMPORAL_APPLICABILITY_NOT_ESTABLISHED", o["queue"][0]["review_reason_codes"])

    def test_report_omits_secret_claim_source_and_identifiers(self):
        out = json.dumps(assess_documentary_gaps(report()), ensure_ascii=False)
        for marker in (SECRET, BOE, "completamente ficticio", "El art. 24", "SUPPORTED"):
            self.assertNotIn(marker, out)

    def test_no_claims(self):
        r = report()
        r["claims"] = []
        r["status"] = "NO_CHECKABLE_CLAIMS"
        out = assess_documentary_gaps(r)
        self.assertEqual(out["queue"], [])
        self.assertEqual(out["claims_queued"], 0)
        self.assertEqual(out["evidence_sections_listed"], 1)

    def test_unchecked_segments_are_counts_only(self):
        out = assess_documentary_gaps(report())
        self.assertEqual(out["unchecked_segments_count"], 1)
        self.assertNotIn(SECRET, json.dumps(out))

    def test_deterministic_hashes(self):
        r = report()
        self.assertEqual(assess_documentary_gaps(r), assess_documentary_gaps(deepcopy(r)))
        self.assertEqual(len(assess_documentary_gaps(r)["m7a_review_sha256"]), 64)

    def test_human_review_always_required(self):
        for status in ("DOCUMENTARY_QUOTE_MATCH", "SECTION_LOCATED_NO_EXPLICIT_QUOTATION",
                       "QUOTED_PASSAGE_NOT_FOUND_IN_CITED_SECTION", "CITED_SECTION_NOT_SUPPLIED"):
            with self.subTest(status=status):
                row = assess_documentary_gaps(report(status=status))["queue"][0]
                self.assertTrue(row["human_review_required"])
                self.assertEqual(row["legal_support"], "NOT_ASSESSED")
                self.assertFalse(row["legal_contradiction_established"])

    def test_scope_flags(self):
        r = report()
        r["claims"][0]["legal_scope_screen"]["issues"].append({"code": "ABSOLUTE_SCOPE_REQUIRES_REVIEW"})
        out = assess_documentary_gaps(r)
        self.assertIn("SCOPE_CONDITIONS_REQUIRE_HUMAN_REVIEW", out["queue"][0]["review_reason_codes"])
        self.assertEqual(out["counts"]["claims_with_scope_review_cues"], 1)

    def test_sibling_citation_not_inherited(self):
        r = report()
        r["claims"][0]["sentence_context"]["sentence_only_identifiers"] = ["ECLI:ES:TC:2024:1"]
        r["claims"][0]["legal_scope_screen"]["issues"].append({"code": "OTHER_CLAUSE_CITATION_NOT_INHERITED"})
        row = assess_documentary_gaps(r)["queue"][0]
        self.assertIn("ADJACENT_CLAUSE_CITATION_NOT_INHERITED", row["review_reason_codes"])

    def test_missing_date_flag(self):
        r = report()
        r["evidence"][0]["version_date"] = None
        o = assess_documentary_gaps(r)
        self.assertEqual(o["counts"]["claims_with_missing_date_metadata"], 1)

    def test_malformed_date_rejected(self):
        r = report()
        r["evidence"][0]["version_date"] = "2024-99-99"
        with self.assertRaises(ReviewGateError):
            assess_documentary_gaps(r)

    def test_leap_day_date_accepted(self):
        r = report()
        r["evidence"][0]["version_date"] = "2024-02-29"
        self.assertEqual(assess_documentary_gaps(r)["counts"]["claims_with_missing_date_metadata"], 0)


class M7BCompetingSnapshots(unittest.TestCase):
    def make(self, version2="2025-01-01", text2="An entirely different synthetic source version"):
        r = report(status="MULTIPLE_EVIDENCE_VERSIONS_AMBIGUOUS")
        r["evidence"].append(evidence(version=version2, text=text2))
        return r

    def test_competing_versions_detected(self):
        out = assess_documentary_gaps(self.make())
        g = out["competing_section_snapshot_groups"]
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["snapshot_count"], 2)
        self.assertEqual(g[0]["distinct_content_hashes"], 2)
        self.assertEqual(g[0]["documentary_tension_code"], "MULTIPLE_OR_UNDATED_SECTION_SNAPSHOTS")
        self.assertFalse(g[0]["legal_contradiction_established"])

    def test_same_date_different_hashes(self):
        out = assess_documentary_gaps(self.make("2024-01-01"))
        g = out["competing_section_snapshot_groups"][0]
        self.assertEqual(g["documentary_tension_code"], "SAME_DATE_DIFFERENT_SECTION_BYTES")
        self.assertEqual(g["distinct_source_dates"], 1)

    def test_unversioned_difference_not_legal_contradiction(self):
        out = assess_documentary_gaps(self.make(None))
        g = out["competing_section_snapshot_groups"][0]
        self.assertTrue(g["date_metadata_missing"])
        self.assertFalse(out["queue"][0]["legal_contradiction_established"])

    def test_ambiguous_citation_matches_group(self):
        out = assess_documentary_gaps(self.make())
        self.assertEqual(out["queue"][0]["competing_section_group_number"], 1)
        self.assertEqual(out["counts"]["claims_with_competing_source_section_snapshots"], 1)

    def test_other_article_is_not_a_conflict(self):
        r = report()
        r["evidence"].append(evidence(section="a25", text="Alternative subsection fixture"))
        self.assertEqual(assess_documentary_gaps(r)["competing_section_snapshot_groups"], [])

    def test_other_norm_is_not_a_conflict(self):
        r = report()
        r["evidence"].append(evidence(identifier="BOE-A-2015-10565", text="Alternate norm fixture"))
        self.assertEqual(assess_documentary_gaps(r)["competing_section_snapshot_groups"], [])

    def test_same_text_section_alias_is_not_divergence(self):
        r = report()
        r["evidence"].append(evidence(section="art 24", text="Este texto es completamente ficticio y no constituye legislación real"))
        self.assertEqual(assess_documentary_gaps(r)["competing_section_snapshot_groups"], [])

    def test_no_identifier_in_output_even_for_competing_group(self):
        out = json.dumps(assess_documentary_gaps(self.make()), ensure_ascii=False)
        self.assertNotIn(BOE, out)
        self.assertNotIn("An entirely different synthetic", out)

    def test_competing_official_marked_unverified(self):
        r = self.make()
        r["evidence"][0]["origin"] = "OFFICIAL_FETCH"
        r["evidence"][1]["origin"] = "OFFICIAL_FETCH"
        out = assess_documentary_gaps(r)
        self.assertFalse(out["source_authenticity_independently_verified"])
        self.assertFalse(out["legal_support_assessed"])

    def test_invalid_tc_date_is_rejected(self):
        r = report()
        r["evidence"].append(evidence(identifier="ECLI:ES:TC:2024:1", source="TC", section="FJ1", version=None,
                                      decision="2024-13-01", text="TC synthetic"))
        with self.assertRaises(ReviewGateError):
            assess_documentary_gaps(r)

    def test_invalid_section_rejected(self):
        r = report()
        r["evidence"].append(evidence(section="not an article", text="Other synthetic"))
        with self.assertRaises(ReviewGateError):
            assess_documentary_gaps(r)

    def test_duplicate_manifest_rejected_by_m7a(self):
        r = self.make()
        r["evidence"].append(deepcopy(r["evidence"][0]))
        with self.assertRaises(ReviewGateError):
            assess_documentary_gaps(r)

    def test_m3_legal_overclaim_rejected(self):
        r = report()
        r["claims"][0]["legal_support"] = "SUPPORTED"
        with self.assertRaises(ReviewGateError):
            assess_documentary_gaps(r)

    def test_m3_claim_hash_tamper_rejected(self):
        r = report()
        r["claims"][0]["documentary_grounding"]["claim_sha256"] = "0"*64
        with self.assertRaises(ReviewGateError):
            assess_documentary_gaps(r)


class M7BCli(unittest.TestCase):
    def test_cli_local_report_no_text_no_network(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/"argument.txt").write_text("Un caso ficticio", encoding="utf-8")
            output = p/"result.json"
            with patch("keepmehonest_legal_es.m7_documentary_gaps.verify_argument", return_value=report()), patch("builtins.print") as stdout:
                rc = main(["--text-file", str(p/"argument.txt"), "--output", str(output)])
            self.assertEqual(rc, 0)
            self.assertTrue(output.is_file())
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(SECRET, output.read_text(encoding="utf-8"))
            self.assertTrue(stdout.called)

    def test_cli_rejects_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/"text.txt").write_text("Synthetic", encoding="utf-8")
            target = p/"result.json"
            target.write_text("EXISTING", encoding="utf-8")
            with patch("keepmehonest_legal_es.m7_documentary_gaps.verify_argument", return_value=report()):
                self.assertEqual(main(["--text-file", str(p/"text.txt"), "--output", str(target)]), 2)
            self.assertEqual(target.read_text(encoding="utf-8"), "EXISTING")

    def test_cli_evidence_origin_cannot_be_forged(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/"text.txt").write_text("Synthetic", encoding="utf-8")
            evidence_input = [{
                "source": "BOE", "identifier": BOE, "section_id": "a24",
                "text": "Esta frase es completamente artificial y solo vale como prueba",
                "official_url": f"https://www.boe.es/buscar/act.php?id={BOE}#a24",
                "title": "Falso documento oficial sintético", "origin": "OFFICIAL_FETCH",
                "version_date": "2024-01-01",
            }]
            (p/"evidence.json").write_text(json.dumps(evidence_input))
            def stub(text, items):
                self.assertEqual(items[0].origin.value, "USER_SUPPLIED")
                return report()
            with patch("keepmehonest_legal_es.m7_documentary_gaps.verify_argument", side_effect=stub):
                self.assertEqual(main(["--text-file", str(p/"text.txt"),
                                       "--evidence-json", str(p/"evidence.json"),
                                       "--output", str(p/"output.json")]), 0)

    def test_cli_duplicate_json_field_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/"text.txt").write_text("Synthetic", encoding="utf-8")
            (p/"evidence.json").write_text('[{"x":1,"x":2}]')
            self.assertEqual(main(["--text-file", str(p/"text.txt"),
                                   "--evidence-json", str(p/"evidence.json"),
                                   "--output", str(p/"result.json")]), 2)
            self.assertFalse((p/"result.json").exists())

    def test_cli_rejects_symlink_input(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/"text.txt").write_text("Synthetic")
            (p/"link.txt").symlink_to(p/"text.txt")
            self.assertEqual(main(["--text-file", str(p/"link.txt"),
                                   "--output", str(p/"result.json")]), 2)

    def test_cli_does_not_open_network(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/"text.txt").write_text("Synthetic")
            with patch("keepmehonest_legal_es.m7_documentary_gaps.verify_argument", return_value=report()), \
                 patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
                self.assertEqual(main(["--text-file", str(p/"text.txt"),
                                       "--output", str(p/"out.json")]), 0)

    def test_cli_output_inside_repo_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/"text.txt").write_text("Synthetic")
            target = Path.cwd()/"M7B_PRIVATE.json"
            with patch("keepmehonest_legal_es.m7_documentary_gaps.verify_argument", return_value=report()):
                self.assertEqual(main(["--text-file", str(p/"text.txt"),
                                       "--output", str(target)]), 2)
            self.assertFalse(target.exists())


class CoreEndToEnd(unittest.TestCase):
    def test_synthetic_m3_m7a_m7b_integration(self):
        import importlib.util
        if importlib.util.find_spec("claims_verifier") is None:
            self.skipTest("generic Core absent in isolated reconstruction")
        from keepmehonest_legal_es.evidence import LegalEvidence, SourceKind, Origin
        from keepmehonest_legal_es.independent import verify_argument
        quote = "Este ejemplo es artificial y no constituye un criterio legal"
        ev = LegalEvidence(source=SourceKind.BOE, identifier=BOE, section_id="a24",
                           text=quote,
                           official_url=f"https://www.boe.es/buscar/act.php?id={BOE}#a24",
                           title="Fixture synthetic", origin=Origin.TEST_FIXTURE,
                           version_date="1978-12-29")
        arg = f"El art. 24 {BOE} dice «{quote}»."
        out = assess_documentary_gaps(verify_argument(arg, [ev]))
        self.assertGreaterEqual(out["claims_queued"], 1)
        self.assertFalse(out["legal_support_assessed"])
        self.assertTrue(all(r["human_review_required"] for r in out["queue"]))


if __name__ == "__main__":
    unittest.main()
