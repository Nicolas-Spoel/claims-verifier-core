import unittest

from keepmehonest_legal_es import CitationCheck, QuoteCheck, review_claim, verify_quote
from test_evidence import tc_evidence


class ReviewTests(unittest.TestCase):
    def test_citation_and_quote_match_still_require_human_review(self):
        ev = tc_evidence()
        x = review_claim("La sentencia ECLI:ES:TC:2024:1 indica admisión.", ev, quote="La solicitud fue admitida")
        self.assertEqual(x.identifier_check, CitationCheck.MATCH)
        self.assertEqual(x.quotation_check, QuoteCheck.MATCH)
        self.assertEqual(x.status, "REVIEW_REQUIRED")
        self.assertEqual(x.legal_interpretation, "NOT_ASSESSED")
        self.assertEqual(x.authenticity, "NOT_ASSESSED")
        self.assertEqual(x.temporal_applicability, "NOT_ASSESSED")
        self.assertIsNone(x.core_lexical_verdict)

    def test_quote_with_opposite_negation_does_not_match(self):
        ev = tc_evidence()
        self.assertEqual(verify_quote(ev, "La solicitud no fue admitida"), QuoteCheck.MISMATCH)
        x = review_claim("ECLI:ES:TC:2024:1", ev, quote="La solicitud no fue admitida")
        self.assertEqual(x.status, "BLOCKED")

    def test_missing_or_wrong_reference_blocks(self):
        ev = tc_evidence()
        self.assertEqual(review_claim("La resolución considera algo.", ev).identifier_check, CitationCheck.MISSING)
        self.assertEqual(review_claim("ECLI:ES:TC:2024:2", ev).identifier_check, CitationCheck.DIFFERENT)
        self.assertEqual(review_claim("ECLI:ES:TC:2024:2", ev).status, "BLOCKED")
        mixed = review_claim("ECLI:ES:TC:2024:1 y ECLI:ES:TC:2024:2", ev)
        self.assertEqual(mixed.identifier_check, CitationCheck.AMBIGUOUS)
        self.assertEqual(mixed.status, "BLOCKED")

    def test_whitespace_normalization_but_not_semantic_edits(self):
        ev = tc_evidence(text="Primero, la  solicitud\n fue admitida.\nSegundo, no se juzga el fondo.")
        self.assertEqual(verify_quote(ev, "la solicitud fue admitida"), QuoteCheck.MATCH)
        self.assertEqual(verify_quote(ev, "sí se juzga el fondo"), QuoteCheck.MISMATCH)

    def test_too_short_quote_does_not_count_as_grounding(self):
        self.assertEqual(verify_quote(tc_evidence(), "La"), QuoteCheck.MISMATCH)

    def test_invalid_claim(self):
        with self.assertRaises(ValueError):
            review_claim(" ", tc_evidence())
