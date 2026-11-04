"""M3-B review cues: strict nonsemantic, no source/claim approval by inheritance."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import importlib.util
import unittest
from unittest.mock import patch

from keepmehonest_legal_es.evidence import LegalEvidence, Origin, SourceKind
from keepmehonest_legal_es.grounding import anchor_claim
from keepmehonest_legal_es.legal_context import (
    CONTRACT, context_for_claims, screen_legal_scope, sentence_frames,
)

BOE = "BOE-A-1978-31229"
TC = "ECLI:ES:TC:2024:1"
PASSAGE = "Todas las personas tienen derecho a obtener la tutela efectiva de los jueces y tribunales"


def boe(*, text=PASSAGE, version="1978-12-29", origin=Origin.TEST_FIXTURE):
    return LegalEvidence(
        source=SourceKind.BOE, identifier=BOE, section_id="a24",
        text=text, official_url=f"https://www.boe.es/buscar/act.php?id={BOE}#a24",
        title="Constitución española, artículo 24", origin=origin, version_date=version,
    )


def tc(*, text="Se delimita el objeto del proceso de amparo y su relevancia constitucional."):
    return LegalEvidence(
        source=SourceKind.TC, identifier=TC, section_id="FJ1", text=text,
        official_url="https://hj.tribunalconstitucional.es/HJ/es/Resolucion/Show/30062",
        title="STC 1/2024, fundamento jurídico 1", origin=Origin.TEST_FIXTURE,
        decision_date="2024-01-15",
    )


def ctx(*, own=(), full=(), siblings=(), mapped=True):
    return {"context_status": "SENTENCE_MAPPED" if mapped else "SPAN_UNRESOLVED",
            "sentence_only_identifiers": list(set(full) - set(own)),
            "direct_identifiers": list(own),
            "sentence_identifiers": list(full),
            "sibling_claim_numbers": list(siblings)}


def codes(result):
    return {issue["code"] for issue in result["issues"]}


class ReviewCueTests(unittest.TestCase):
    def test_no_evidence_keeps_support_unassessed(self):
        claim = f"El artículo 24 de {BOE} garantiza defensa jurídica."
        r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor_claim(claim, []), [])
        self.assertEqual(r["legal_support"], "NOT_ASSESSED")
        self.assertEqual(r["screen_status"], "HUMAN_LEGAL_REVIEW_REQUIRED")
        self.assertIn("EXACT_SOURCE_SECTION_NOT_LINKED", codes(r))
        self.assertTrue(r["requires_human_review"])

    def test_matching_literal_is_not_legal_support(self):
        ev = boe()
        claim = f"El artículo 24 de {BOE} dice «{PASSAGE}»."
        anchor = anchor_claim(claim, [ev])
        self.assertEqual(anchor["anchor_status"], "DOCUMENTARY_QUOTE_MATCH")
        r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor, [ev])
        self.assertEqual(r["legal_support"], "NOT_ASSESSED")
        self.assertIn("EXACT_QUOTE_DOES_NOT_PROVE_PROPOSITION", codes(r))
        self.assertIn("BOE_VIGENCIA_AND_APPLICABILITY_NOT_ESTABLISHED", codes(r))
        self.assertNotIn("EXACT_SOURCE_SECTION_NOT_LINKED", codes(r))

    def test_sibling_reference_is_never_inherited(self):
        claim = "no basta por sí sola para una conclusión jurídica"
        context = ctx(full=[BOE], siblings=[1])
        r = screen_legal_scope(claim, context, anchor_claim(claim, [boe()]), [boe()])
        self.assertIn("OTHER_CLAUSE_CITATION_NOT_INHERITED", codes(r))
        self.assertIn("EXACT_SOURCE_SECTION_NOT_LINKED", codes(r))
        self.assertEqual(r["legal_support"], "NOT_ASSESSED")

    def test_no_context_does_not_guess(self):
        claim = f"El artículo 24 de {BOE} afirma un derecho."
        r = screen_legal_scope(claim, ctx(mapped=False), anchor_claim(claim, [boe()]), [boe()])
        self.assertIn("SENTENCE_CONTEXT_UNRESOLVED", codes(r))

    def test_absolute_claim_is_review_trigger_not_falsity(self):
        claim = f"El artículo 24 de {BOE} siempre es aplicable sin excepción."
        r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor_claim(claim, [boe()]), [boe()])
        self.assertIn("ABSOLUTE_SCOPE_REQUIRES_REVIEW", codes(r))
        self.assertEqual(r["legal_support"], "NOT_ASSESSED")
        self.assertNotIn("CONTRADICTED", str(r))

    def test_absolute_word_inside_exact_quote_is_not_authors_assertion(self):
        ev = boe(text="El derecho será siempre protegido sin excepción.")
        claim = f'El artículo 24 de {BOE} declara «{ev.text}».'
        r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor_claim(claim, [ev]), [ev])
        self.assertNotIn("ABSOLUTE_SCOPE_REQUIRES_REVIEW", codes(r))

    def test_detects_temporal_claim_without_declaring_vigencia(self):
        claim = f"El artículo 24 de {BOE} sigue vigente a fecha de hoy."
        r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor_claim(claim, [boe()]), [boe()])
        self.assertIn("ASSERTED_TEMPORAL_SCOPE_UNVERIFIED", codes(r))
        self.assertEqual(r["legal_applicability"], "NOT_ASSESSED")

    def test_historical_bo_evidence_date_is_not_applicability(self):
        ev = boe(version="2000-02-01")
        claim = f"El artículo 24 de {BOE} produce efectos desde 2000."
        attempts = [{"source": "BOE", "identifier": BOE, "status": "FETCHED", "requested_as_of": "2024-01-15"}]
        r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor_claim(claim, [ev]), [ev], attempts)
        m = r["linked_source_temporal_metadata"]
        self.assertEqual(m["version_date"], "2000-02-01")
        self.assertEqual(m["request_date_candidates"], ["2024-01-15"])
        self.assertEqual(m["temporal_applicability"], "NOT_ASSESSED")

    def test_fetch_failed_attempt_does_not_supply_a_date(self):
        ev = boe()
        claim = f"El artículo 24 de {BOE} produce efectos."
        attempts = [{"source": "BOE", "identifier": BOE, "status": "UNAVAILABLE", "requested_as_of": "2024-01-15"}]
        r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor_claim(claim, [ev]), [ev], attempts)
        self.assertEqual(r["linked_source_temporal_metadata"]["request_date_candidates"], [])

    def test_duplicate_attempt_dates_are_not_misrepresented_as_one(self):
        ev = boe()
        claim = f"El artículo 24 de {BOE} produce efectos."
        attempts = [
            {"source": "BOE", "identifier": BOE, "status": "FETCHED", "requested_as_of": "2024-01-15"},
            {"source": "BOE", "identifier": BOE, "status": "FETCHED", "requested_as_of": "2023-01-15"},
        ]
        r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor_claim(claim, [ev]), [ev], attempts)
        self.assertEqual(r["linked_source_temporal_metadata"]["request_date_candidates"], ["2023-01-15", "2024-01-15"])

    def test_exception_in_cited_section_only_triggers_review(self):
        ev = boe(text="Todos pueden solicitar un recurso, salvo en los supuestos previstos expresamente.")
        claim = f"El artículo 24 de {BOE} regula un recurso."
        r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor_claim(claim, [ev]), [ev])
        self.assertIn("CITED_SECTION_CONTAINS_SCOPE_QUALIFIER", codes(r))
        self.assertEqual(r["legal_support"], "NOT_ASSESSED")

    def test_exception_in_unrelated_evidence_does_not_trigger_cited_section(self):
        claimed = boe()
        unrelated = tc(text="Una excepción muy particular queda acreditada salvo revisión.")
        claim = f"El artículo 24 de {BOE} dice «{PASSAGE}»."
        r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor_claim(claim, [claimed, unrelated]), [claimed, unrelated])
        self.assertNotIn("CITED_SECTION_CONTAINS_SCOPE_QUALIFIER", codes(r))

    def test_tc_ratio_and_later_cases_not_silently_assessed(self):
        ev = tc()
        claim = f"El FJ1 de {TC} señala «{ev.text}»."
        r = screen_legal_scope(claim, ctx(own=[TC], full=[TC]), anchor_claim(claim, [ev]), [ev])
        self.assertIn("TC_RATIO_PROCEDURAL_FIT_AND_LATER_CASES_UNCHECKED", codes(r))
        self.assertEqual(r["linked_source_temporal_metadata"]["decision_date"], "2024-01-15")
        self.assertIn("later_amendments_or_cases", r["not_checked"])

    def test_bad_quote_does_not_grant_semantic_support(self):
        ev = boe()
        claim = f"El artículo 24 de {BOE} indica «Queda prohibida toda tutela judicial efectiva sin excepción»."
        r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor_claim(claim, [ev]), [ev])
        self.assertIn("DOCUMENTARY_SUPPORT_NOT_ESTABLISHED", codes(r))
        self.assertEqual(r["legal_support"], "NOT_ASSESSED")

    def test_untested_marker_not_same_as_support(self):
        ev = boe()
        claim = f"El artículo 24 de {BOE} regula asuntos ordinarios."
        r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor_claim(claim, [ev]), [ev])
        self.assertEqual(r["screen_status"], "HUMAN_LEGAL_REVIEW_REQUIRED")
        self.assertEqual(r["argument_quality"], "NOT_ASSESSED")
        self.assertFalse(any("SUPPORTED" in issue["code"] for issue in r["issues"]))

    def test_sentence_context_fails_closed_without_guessing(self):
        @dataclass(frozen=True)
        class Claim:
            text: str
            char_start: int | None
            char_end: int | None

        text = f"El artículo 24 de {BOE} resulta relevante, pero eso no permite validar toda conclusión."
        comma = text.index(", pero")
        first = Claim(text[:comma], 0, comma)
        second_start = comma + len(", pero ")
        second = Claim(text[second_start:], second_start, len(text))
        contexts = context_for_claims(text, (first, second), ((0, len(text)),))
        self.assertEqual(contexts[0]["sibling_claim_numbers"], [2])
        self.assertEqual(contexts[1]["sibling_claim_numbers"], [1])
        self.assertEqual(contexts[1]["direct_identifiers"], [])
        self.assertEqual(contexts[1]["sentence_only_identifiers"], [BOE])
        self.assertFalse(contexts[1]["inherit_documentary_anchor"])
        self.assertEqual(contexts[1]["sentence_text"], text)

    def test_mismatched_span_returns_unresolved_without_borrowing_refs(self):
        @dataclass(frozen=True)
        class Claim:
            text: str
            char_start: int | None
            char_end: int | None

        text = f"El artículo 24 de {BOE} ofrece una garantía."
        result = context_for_claims(text, (Claim("texto de otra fuente", 500, 505),), ((0, len(text)),))
        self.assertEqual(result[0]["context_status"], "SPAN_UNRESOLVED")
        self.assertIsNone(result[0]["sentence_text"])
        self.assertEqual(result[0]["sentence_only_identifiers"], [])

    def test_mask_length_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            sentence_frames("texto jurídico", "texto")

    def test_no_network_calls_in_screen(self):
        ev = boe()
        claim = f"El artículo 24 de {BOE} señala «{PASSAGE}»."
        with patch("keepmehonest_legal_es.sources.transport.SecureHTTP.get", side_effect=AssertionError("network")):
            r = screen_legal_scope(claim, ctx(own=[BOE], full=[BOE]), anchor_claim(claim, [ev]), [ev])
        self.assertEqual(r["legal_support"], "NOT_ASSESSED")


HAS_CORE = importlib.util.find_spec("claims_verifier") is not None


@unittest.skipUnless(HAS_CORE, "requires full Core 0.1.1 checkout")
class ContextIntegrationTests(unittest.TestCase):
    def test_sentence_split_keeps_sibling_refs_without_inheritance(self):
        from keepmehonest_legal_es.independent import verify_argument
        text = f"La fuente {BOE} resulta relevante, pero no basta por sí sola para demostrar una conclusión jurídica concreta."
        report = verify_argument(text, [boe()])
        self.assertEqual(len(report["claims"]), 2)
        first, second = report["claims"]
        self.assertEqual(first["sentence_context"]["sibling_claim_numbers"], [2])
        self.assertEqual(second["sentence_context"]["sibling_claim_numbers"], [1])
        self.assertEqual(second["sentence_context"]["sentence_only_identifiers"], [BOE])
        self.assertEqual(second["sentence_context"]["direct_identifiers"], [])
        self.assertEqual(second["documentary_grounding"]["anchor_status"], "NO_EXPLICIT_IDENTIFIER")
        self.assertEqual(second["legal_support"], "NOT_ASSESSED")
        self.assertIn("OTHER_CLAUSE_CITATION_NOT_INHERITED", codes(second["legal_scope_screen"]))
        self.assertFalse(second["sentence_context"]["inherit_documentary_anchor"])

    def test_context_contains_original_text_and_offsets(self):
        from keepmehonest_legal_es.independent import verify_argument
        text = f"El art. 24 de {BOE} dice «{PASSAGE}»."
        report = verify_argument(text, [boe()])
        self.assertEqual(len(report["claims"]), 1)
        c = report["claims"][0]["sentence_context"]
        self.assertEqual(c["sentence_text"], text)
        self.assertEqual(c["sentence_char_span"], [0, len(text)])
        self.assertEqual(c["sentence_sha256"], sha256(text.encode()).hexdigest())
        self.assertEqual(c["direct_identifiers"], [BOE])
        self.assertEqual(c["sentence_only_identifiers"], [])

    def test_separate_sentences_never_share_refs(self):
        from keepmehonest_legal_es.independent import verify_argument
        text = f"El art. 24 de {BOE} resulta pertinente. Sin embargo, falta interpretación constitucional."
        report = verify_argument(text, [boe()])
        self.assertEqual(len(report["claims"]), 2)
        self.assertEqual(report["claims"][1]["sentence_context"]["sentence_only_identifiers"], [])

    def test_context_is_line_scoped(self):
        from keepmehonest_legal_es.independent import verify_argument
        text = f"El art. 24 de {BOE} resulta pertinente.\nLa argumentación exige una revisión independiente."
        report = verify_argument(text, [boe()])
        self.assertEqual(len(report["claims"]), 2)
        self.assertEqual(report["claims"][1]["sentence_context"]["sentence_only_identifiers"], [])

    def test_original_span_survives_abbreviation_mask(self):
        from keepmehonest_legal_es.independent import verify_argument
        text = f"Art. 24 de {BOE} establece garantías jurídicas."
        report = verify_argument(text, [boe()])
        self.assertEqual(report["claims"][0]["sentence_context"]["sentence_text"], text)
        self.assertEqual(report["claims"][0]["sentence_context"]["sentence_char_span"], [0, len(text)])

    def test_report_has_nonsemantic_coverage(self):
        from keepmehonest_legal_es.independent import verify_argument
        claim = f"El art. 24 de {BOE} es siempre aplicable."
        report = verify_argument(claim, [boe()])
        self.assertEqual(report["schema_version"], "keepmehonest-legal-es/0.3.1")
        coverage = report["coverage"]["m3b_legal_scope_screen"]
        self.assertEqual(coverage["legal_support_assessed"], 0)
        self.assertEqual(coverage["claims_examined"], 1)
        self.assertEqual(coverage["sentence_contexts_mapped"], 1)
        self.assertEqual(report["claims"][0]["legal_scope_screen"]["legal_support"], "NOT_ASSESSED")
        self.assertEqual(report["claims"][0]["legal_support"], "NOT_ASSESSED")

    def test_tc_historical_context_only(self):
        from keepmehonest_legal_es.independent import verify_argument
        ev = tc()
        claim = f"El FJ1 de {TC} afirma «{ev.text}»."
        r = verify_argument(claim, [ev])
        self.assertEqual(r["claims"][0]["documentary_grounding"]["anchor_status"], "DOCUMENTARY_QUOTE_MATCH")
        self.assertEqual(r["claims"][0]["legal_scope_screen"]["legal_applicability"], "NOT_ASSESSED")

    def test_no_evidence_still_records_context(self):
        from keepmehonest_legal_es.independent import verify_argument
        text = f"El artículo 24 de {BOE} no está incluido."
        r = verify_argument(text, [])
        self.assertEqual(r["status"], "SOURCES_REQUIRED")
        self.assertEqual(r["coverage"]["m3b_legal_scope_screen"]["claims_examined"], 1)
        self.assertIsNone(r["claims"][0]["legal_scope_screen"]["linked_source_temporal_metadata"])

    def test_no_network_for_context_integration(self):
        from keepmehonest_legal_es.independent import verify_argument
        text = f"El artículo 24 de {BOE} siempre requiere revisión."
        with patch("keepmehonest_legal_es.sources.transport.SecureHTTP.get", side_effect=AssertionError("network")):
            r = verify_argument(text, [boe()])
        self.assertEqual(r["claims"][0]["legal_support"], "NOT_ASSESSED")


if __name__ == "__main__":
    unittest.main()
