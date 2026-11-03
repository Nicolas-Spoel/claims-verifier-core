"""Integration check is designed to run in the real upstream fork tree."""
import importlib.util
import unittest

from keepmehonest_legal_es import review_claim, to_core_document
from test_evidence import tc_evidence


@unittest.skipUnless(importlib.util.find_spec("claims_verifier"), "requires Claims Verifier Core from the fork")
class CoreBridgeTests(unittest.TestCase):
    def test_core_from_documents_unchanged(self):
        from claims_verifier import ClaimsVerifier
        evidence = tc_evidence()
        document = to_core_document(evidence)
        self.assertEqual(document.metadata["identifier"], evidence.identifier)
        self.assertEqual(document.metadata["evidence_sha256"], evidence.sha256)
        self.assertEqual(document.sha256, evidence.sha256)
        engine = ClaimsVerifier.from_documents([document])
        report = engine.verify_claims(["El órgano ficticio admitió la solicitud."])
        self.assertEqual(len(report.results), 1)

    def test_lexical_verdict_is_not_legal_conclusion(self):
        result = review_claim("ECLI:ES:TC:2024:1 admitió una solicitud.", tc_evidence(), run_core=True)
        self.assertIsNotNone(result.core_lexical_verdict)
        self.assertEqual(result.status, "REVIEW_REQUIRED")
        self.assertEqual(result.legal_interpretation, "NOT_ASSESSED")
