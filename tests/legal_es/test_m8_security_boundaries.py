"""M8-A: cross-component adversarial regression tests. Offline; no network.

These tests check selected known trust boundaries, not comprehensive security
assurance or accuracy of legal conclusions. Never use real client material.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keepmehonest_legal_es.m6_discovery import (
    BOESearchTransport, DiscoveryError, build_url as boe_search_url,
    parse_listing, _write_new,
)
from keepmehonest_legal_es.m6_linkage import (
    LinkageError, plan as boe_article_plan, select as boe_select,
)
from keepmehonest_legal_es.m6_tc_boe_index import (
    BOESummaryTransport, TCBOEIndexError,
    build_url as tc_index_url, handoff, parse_day,
)
from keepmehonest_legal_es.m6_tc_linkage import (
    TCLinkageError, plan as tc_section_plan,
)
from keepmehonest_legal_es.m7_review_gate import (
    ReviewGateError, _read_file, _write_private, assess_report,
)
from keepmehonest_legal_es.sources.transport import Retrieved, FetchError, SecureHTTP
from keepmehonest_legal_es.independent import REPORT_VERSION


CLIENT_SECRET = "M8_CLIENT_NAME_PRIVATE_MARKER"
SOURCE_SECRET = "M8_SOURCE_TEXT_PRIVATE_MARKER"
DAY = date(2024, 2, 20)
BOE = "BOE-A-1978-31229"
STC = "BOE-A-2024-3267"


def _wire(url, obj):
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return Retrieved(url, body, "application/json", sha256(body).hexdigest(),
                     "2026-11-04T12:00:00+00:00")


def _listing():
    url = boe_search_url("constitucional", 1, 0)
    payload = {
        "status": {"code": 200},
        "data": [{
            "identificador": BOE, "titulo": "Constitución Española",
            "fecha_publicacion": "19781229", "fecha_actualizacion": "20261104T091715Z",
            "url_html_consolidada": f"https://www.boe.es/buscar/act.php?id={BOE}",
        }],
    }
    return parse_listing(_wire(url, payload), topic="constitucional", limit=1, offset=0)


def _tc_day(title="Sentencia 1/2024. " + CLIENT_SECRET):
    return _wire(tc_index_url(DAY), {
        "status": {"code": "200"},
        "data": {"sumario": {
            "metadatos": {"publicacion": "BOE", "fecha_publicacion": "20240220"},
            "diario": {"seccion": [{
                "codigo": "T", "nombre": "T.C. Sección del Tribunal Constitucional",
                "departamento": {"codigo": "TC", "nombre": "TRIBUNAL CONSTITUCIONAL",
                                 "texto": {"epigrafe": [{"nombre": "Sentencias",
                                                        "item": [{"identificador": STC, "titulo": title,
                                                                  "control": "x", "url_html": "x",
                                                                  "url_pdf": "x", "url_xml": "x"}]}]}},
            }]},
        }},
    })


def _m3_report():
    claim = "La frase ficticia de un cliente " + CLIENT_SECRET
    q = SOURCE_SECRET
    evidence_digest = sha256(q.encode()).hexdigest()
    key = sha256((f"BOE\0{BOE}\0a24\0{evidence_digest}").encode()).hexdigest()
    return {
        "schema_version": REPORT_VERSION,
        "status": "READY_FOR_HUMAN_REVIEW",
        "legal_interpretation": "NOT_ASSESSED",
        "legal_argument_quality": "NOT_ASSESSED",
        "coverage": {"corpus_completeness": "UNVERIFIABLE",
                     "ordinary_court_search": "NOT_PERFORMED_CENDOJ_DISABLED",
                     "general_case_law_search": "NOT_PERFORMED"},
        "evidence": [{"source": "BOE", "identifier": BOE, "section_id": "a24",
                      "sha256": evidence_digest, "evidence_key": key, "origin": "USER_SUPPLIED"}],
        "unchecked_segments": [{"text": "OTRO_SECRETO_M8", "reason": "not parsed"}],
        "claims": [{
            "claim": claim, "lexical_verdict": "SUPPORTED",
            "legal_support": "NOT_ASSESSED", "argument_quality": "NOT_ASSESSED",
            "review_status": "HUMAN_REVIEW_REQUIRED",
            "documentary_grounding": {
                "claim_sha256": sha256(claim.encode()).hexdigest(),
                "anchor_status": "DOCUMENTARY_QUOTE_MATCH", "source_identifier": BOE,
                "cited_section_id": "a24", "evidence_key": key,
                "evidence_sha256": evidence_digest, "source_origin": "USER_SUPPLIED",
                "quoted_passage_sha256": sha256(q.encode()).hexdigest(),
                "quoted_passage_characters": len(q), "quote_match_method": "LITERAL_NFC_WHITESPACE_ONLY",
                "review_flags": ["QUOTE_DOES_NOT_ESTABLISH_LEGAL_ENTAILMENT"],
                "legal_support": "NOT_ASSESSED", "legal_applicability": "NOT_ASSESSED",
                "requires_human_review": True,
            },
            "legal_scope_screen": {"screen_status": "HUMAN_LEGAL_REVIEW_REQUIRED",
                                    "issues": [{"code": "EXACT_QUOTE_DOES_NOT_PROVE_PROPOSITION"}],
                                    "legal_support": "NOT_ASSESSED",
                                    "legal_applicability": "NOT_ASSESSED",
                                    "requires_human_review": True},
            "sentence_context": {"inherit_documentary_anchor": False,
                                 "sentence_only_identifiers": []},
        }],
    }


class OutboundAllowlistTests(unittest.TestCase):
    def test_boe_query_has_no_free_form_claim_or_client_name(self):
        url = boe_search_url("constitucional", 5, 0)
        self.assertNotIn(CLIENT_SECRET, url)
        self.assertIn("www.boe.es", url)
        with self.assertRaises(DiscoveryError):
            boe_search_url(CLIENT_SECRET, 5, 0)

    def test_boe_search_rejects_arbitrary_and_spoofed_hosts(self):
        for url in (
            "http://www.boe.es/datosabiertos/api/legislacion-consolidada",
            "https://www.boe.es.evil.test/datosabiertos/api/legislacion-consolidada",
            "https://example.test/", "file:///etc/passwd",
            boe_search_url("civil") + "&q=" + CLIENT_SECRET,
            boe_search_url("civil").replace("offset=0", "offset=0&offset=0"),
        ):
            with self.subTest(url=url), self.assertRaises(DiscoveryError):
                BOESearchTransport.check_url(url)

    def test_tc_daily_index_rejects_arbitrary_destination_or_query(self):
        canonical = tc_index_url(DAY)
        BOESummaryTransport.check_url(canonical)
        for url in (canonical + "?text=" + CLIENT_SECRET,
                    canonical.replace("www.boe.es", "www.boe.es.evil.test"),
                    canonical.replace("https://", "http://"),
                    canonical + "/../20240221", "file:///tmp/a"):
            with self.subTest(url=url), self.assertRaises(TCBOEIndexError):
                BOESummaryTransport.check_url(url)

    def test_tc_json_transport_stays_one_resolution(self):
        SecureHTTP.check_url("https://hj.tribunalconstitucional.es/HJ/Resolucion/Api/json/30062")
        for url in ("https://hj.tribunalconstitucional.es/HJ/es/Busqueda/Index",
                    "https://hj.tribunalconstitucional.es/HJ/Resolucion/Api/json/30062?keyword=" + CLIENT_SECRET,
                    "https://hj.tribunalconstitucional.es.evil.test/HJ/Resolucion/Api/json/30062"):
            with self.subTest(url=url), self.assertRaises(FetchError):
                SecureHTTP.check_url(url)

    def test_boe_listing_does_not_bless_unscoped_retrieval(self):
        listing = _listing()
        selection = boe_article_plan(listing, identifier=BOE, article=24,
                                     as_of="2024-01-15", discovery_file_sha256="a" * 64)
        self.assertFalse(selection["network_used"])
        self.assertFalse(selection["section_retrieved"])
        self.assertFalse(selection["legal_support_assessed"])
        self.assertEqual(selection["legal_applicability"], "NOT_ASSESSED")

    def test_boe_article_not_on_listing_rejected(self):
        with self.assertRaises(LinkageError):
            boe_select(_listing(), identifier="BOE-A-2020-7796", article=24, as_of="2024-01-15")

    def test_boe_historical_date_predating_norm_rejected(self):
        with self.assertRaises(LinkageError):
            boe_select(_listing(), identifier=BOE, article=24, as_of="1978-01-01")

    def test_tc_manual_ids_do_not_claim_identity_verified(self):
        report = tc_section_plan(ecli="ECLI:ES:TC:2024:1", hj_id=30062,
                                 section="FJ1", topic="constitucional")
        self.assertFalse(report["user_supplied_pair_verified"])
        self.assertFalse(report["network_used"])
        self.assertFalse(report["coverage"]["exhaustive"])


class PublicationPrivacyTests(unittest.TestCase):
    def test_tc_publication_index_omits_potential_names(self):
        meta, rows = parse_day(_tc_day(), day=DAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["identifier"], STC)
        blob = json.dumps([meta, rows], ensure_ascii=False)
        self.assertNotIn(CLIENT_SECRET, blob)
        self.assertNotIn("titulo", blob)
        self.assertIsNone(rows[0]["ecli"])
        self.assertIsNone(rows[0]["hj_document_id"])
        self.assertFalse(rows[0]["section_retrieved"])

    def test_tc_unknown_container_must_fail_instead_of_zero_results(self):
        payload = json.loads(_tc_day().body)
        dept = payload["data"]["sumario"]["diario"]["seccion"][0]["departamento"]
        dept["texto"] = {"unknown": []}
        with self.assertRaises(TCBOEIndexError):
            parse_day(_wire(tc_index_url(DAY), payload), day=DAY)

    def test_tc_duplicate_identifiers_are_rejected(self):
        payload = json.loads(_tc_day().body)
        items = payload["data"]["sumario"]["diario"]["seccion"][0]["departamento"]["texto"]["epigrafe"][0]["item"]
        items.append(deepcopy(items[0]))
        with self.assertRaisesRegex(TCBOEIndexError, "duplicate"):
            parse_day(_wire(tc_index_url(DAY), payload), day=DAY)

    def test_tc_source_code_label_mismatch_is_rejected(self):
        payload = json.loads(_tc_day().body)
        payload["data"]["sumario"]["diario"]["seccion"][0]["codigo"] = "TC"
        with self.assertRaises(TCBOEIndexError):
            parse_day(_wire(tc_index_url(DAY), payload), day=DAY)

    def test_tc_modified_payload_with_old_hash_rejected(self):
        response = _tc_day()
        modified = response.body.replace(b"20240220", b"20240221")
        with self.assertRaises(TCBOEIndexError):
            parse_day(Retrieved(response.url, modified, response.content_type,
                                response.sha256, response.retrieved_at), day=DAY)

    def test_tc_wrong_publication_day_rejected(self):
        with self.assertRaises(TCBOEIndexError):
            parse_day(_tc_day(), day=date(2024, 2, 21))

    def test_tc_handoff_requires_explicit_unverified_pair(self):
        meta, rows = parse_day(_tc_day(), day=DAY)
        report = {"contract": "keepmehonest-legal-es/m6-tc-boe-daily-index/v1",
                  "mode": "BOE_TC_PUBLICATION_INDEX_DISCOVERY_METADATA_ONLY",
                  "candidates": rows}
        result = handoff(report, boe_id=STC, ecli="ECLI:ES:TC:2024:1",
                         hj_id=30062, section="FJ1", topic="constitucional")
        self.assertFalse(result["boe_to_hj_pair_verified"])
        self.assertFalse(result["m6c1_plan"]["user_supplied_pair_verified"])
        self.assertFalse(result["network_used"])
        self.assertFalse(result["coverage_exhaustive"])
        with self.assertRaises(TCBOEIndexError):
            handoff(report, boe_id=STC, ecli="ECLI:ES:TC:2024:2",
                    hj_id=30062, section="FJ1", topic="constitucional")


class DocumentaryAbstentionTests(unittest.TestCase):
    def test_lexical_support_and_quote_not_legal_truth(self):
        output = assess_report(_m3_report())
        self.assertEqual(output["counts"]["literal_quote_located"], 1)
        self.assertFalse(output["legal_support_assessed"])
        self.assertFalse(output["legal_accuracy_measured"])
        self.assertFalse(output["coverage_exhaustive"])
        self.assertEqual(output["expert_gold_cases"], 0)
        self.assertEqual(output["queue"][0]["legal_truth_verdict"], "NOT_PRODUCED")
        self.assertTrue(output["queue"][0]["human_review_required"])

    def test_private_marker_and_identifier_redacted_from_queue(self):
        output = assess_report(_m3_report())
        data = json.dumps(output, ensure_ascii=False)
        for marker in (CLIENT_SECRET, SOURCE_SECRET, BOE, "OTRO_SECRETO_M8", "SUPPORTED"):
            self.assertNotIn(marker, data)
        self.assertTrue(output["queue"][0]["claim_sha256"])
        self.assertFalse(output["client_text_in_report"])

    def test_evidence_origin_cannot_be_escalated_via_claim(self):
        report = _m3_report()
        report["claims"][0]["documentary_grounding"]["source_origin"] = "OFFICIAL_FETCH"
        with self.assertRaises(ReviewGateError):
            assess_report(report)

    def test_fabricated_legal_verdict_is_rejected(self):
        report = _m3_report()
        report["claims"][0]["legal_support"] = "SUPPORTED"
        with self.assertRaises(ReviewGateError):
            assess_report(report)

    def test_tampered_claim_text_is_rejected(self):
        report = _m3_report()
        report["claims"][0]["claim"] += " UNHASHED_APPEND"
        with self.assertRaises(ReviewGateError):
            assess_report(report)

    def test_sibling_citation_lineage_fail_closed(self):
        report = _m3_report()
        report["claims"][0]["sentence_context"]["sentence_only_identifiers"] = ["ECLI:ES:TC:2024:1"]
        with self.assertRaises(ReviewGateError):
            assess_report(report)

    def test_no_expert_gold_claim_from_user_report(self):
        report = _m3_report()
        report["expert_gold_cases"] = 99  # unrelated key cannot promote reviewed cases
        output = assess_report(report)
        self.assertEqual(output["expert_gold_cases"], 0)
        self.assertFalse(output["legal_accuracy_measured"])


class LocalFileSecurityTests(unittest.TestCase):
    def test_review_json_is_0600_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "review.json"
            _write_private(p, assess_report(_m3_report()))
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ReviewGateError):
                _write_private(p, {"changed": True})
            self.assertNotIn(CLIENT_SECRET, p.read_text(encoding="utf-8"))

    def test_private_input_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "real.txt"
            real.write_text(CLIENT_SECRET, encoding="utf-8")
            link = Path(td) / "link.txt"
            link.symlink_to(real)
            with self.assertRaises(OSError):
                _read_file(link, 800_000)

    def test_report_output_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "other.json"
            link = Path(td) / "review.json"
            link.symlink_to(real)
            with self.assertRaises(ReviewGateError):
                _write_private(link, {"safe": True})
            self.assertFalse(real.exists())

    def test_public_metadata_output_no_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "metadata.json"
            _write_new(dest, {"mode": "SYNTHETIC"})
            self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(DiscoveryError):
                _write_new(dest, {"mode": "REPLACEMENT"})


if __name__ == "__main__":
    unittest.main()
