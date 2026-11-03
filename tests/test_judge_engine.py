"""Passage judgement, verdicts and aggregation.

`SpanishVerdictsTest` keeps Spanish inputs on purpose (Spanish-language support test data): it exercises
the Spanish lexicon; `EnglishVerdictsTest` covers the same behavior in English.
"""

import unittest

from claims_verifier import ClaimsVerifier, JudgeConfig, Stance, Verdict, VerifierConfig, make_document
from claims_verifier.aggregate import Uncertainty, aggregate
from claims_verifier.judge import Code
from claims_verifier.models import Claim, Passage, PassageAssessment, Signal

ES_DOCS = [
    make_document(
        "informe",
        "---\ntitle: Informe anual 2023 de Andes Agro\ndate: 2024-02-01\n---\n"
        "Los ingresos de Andes Agro alcanzaron S/ 20 millones en 2023, un crecimiento de 8% respecto a 2022.\n\n"
        "La empresa no exporta a Europa.\n\n"
        "En abril de 2023 se inauguró la planta de Ica.\n\n"
        "El 60% de los clientes renovó su contrato.\n\n"
        "La planta de Piura podría ampliarse en 2026.\n\n"
        "En 2022 los ingresos fueron de S/ 18,5 millones.\n",
    ),
    make_document(
        "nota",
        "---\ntitle: Nota de prensa 2024\ndate: 2024-06-01\n---\nLos ingresos de Andes Agro alcanzaron S/ 21 millones en 2023.\n",
    ),
]

EN_DOCS = [
    make_document(
        "report",
        "---\ntitle: Quillfield Freight Co annual report 2023\n---\n"
        "Revenue grew 7% in 2023 to USD 12 million.\n\n"
        "The company did not open new warehouses in 2023.\n\n"
        "Customer churn fell to 4% in 2023.\n",
    )
]


def verdict_of(verifier, text):
    return verifier.verify_claims([text]).results[0]


class SpanishVerdictsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verifier = ClaimsVerifier.from_documents(ES_DOCS)

    def assertVerdict(self, text, expected):
        result = verdict_of(self.verifier, text)
        self.assertIs(result.verdict, expected, f"{text}: {result}")
        return result

    def test_supported_with_traceable_evidence(self):
        result = self.assertVerdict("Andes Agro creció 8% en 2023 respecto a 2022.", Verdict.SUPPORTED)
        evidence = result.evidence[0]
        self.assertEqual(evidence.passage.doc_id, "informe")
        self.assertIs(evidence.stance, Stance.SUPPORTS)
        self.assertTrue(any(s.code == Code.NUMBER_MATCH for s in evidence.signals))

    def test_number_mismatch_is_a_contradiction(self):
        result = self.assertVerdict("Los ingresos crecieron 15% respecto a 2022.", Verdict.CONTRADICTED)
        self.assertEqual(result.evidence[0].signals[0].code, Code.NUMBER_MISMATCH)

    def test_negation_mismatch(self):
        self.assertVerdict("Andes Agro exporta a Europa.", Verdict.CONTRADICTED)

    def test_month_mismatch(self):
        result = self.assertVerdict("La planta de Ica se inauguró en junio de 2023.", Verdict.CONTRADICTED)
        self.assertEqual(result.evidence[0].signals[0].code, Code.DATE_MISMATCH)

    def test_year_mismatch_for_event_dates(self):
        self.assertVerdict("La planta de Ica se inauguró en 2021.", Verdict.CONTRADICTED)

    def test_other_period_is_not_a_contradiction(self):
        result = self.assertVerdict("Los ingresos de 2021 fueron de S/ 20 millones.", Verdict.NOT_ENOUGH_EVIDENCE)
        self.assertIn(Uncertainty.OTHER_PERIOD_ONLY, [u.code for u in result.uncertainty])

    def test_conflicting_sources_report_the_newest(self):
        result = self.assertVerdict("Los ingresos de Andes Agro fueron de S/ 20 millones en 2023.", Verdict.CONFLICTING)
        conflict = result.uncertainty[0]
        self.assertEqual(conflict.code, Uncertainty.CONFLICTING_SOURCES)
        self.assertIn("nota (2024-06-01, against)", conflict.detail)

    def test_quantifier_overstated(self):
        result = self.assertVerdict("Todos los clientes renovaron su contrato.", Verdict.PARTIALLY_SUPPORTED)
        self.assertIn(Uncertainty.QUANTIFIER_OVERSTATED, [u.code for u in result.uncertainty])

    def test_certainty_overstated(self):
        result = self.assertVerdict("La planta de Piura se ampliará en 2026.", Verdict.PARTIALLY_SUPPORTED)
        self.assertIn(Uncertainty.CERTAINTY_OVERSTATED, [u.code for u in result.uncertainty])

    def test_hedged_claim_matching_hedged_evidence_is_supported_but_flagged(self):
        result = self.assertVerdict("La planta de Piura podría ampliarse en 2026.", Verdict.SUPPORTED)
        self.assertIn(Uncertainty.CLAIM_HEDGED, [u.code for u in result.uncertainty])

    def test_out_of_corpus_scope(self):
        result = self.assertVerdict("Andes Agro cotiza en la bolsa de Nueva York.", Verdict.NOT_ENOUGH_EVIDENCE)
        self.assertIn("bolsa", " ".join(result.terms_absent_from_corpus))
        self.assertEqual(result.evidence, ())

    def test_claim_without_content_terms_has_no_evidence(self):
        self.assertVerdict("2023.", Verdict.NOT_ENOUGH_EVIDENCE)


class EnglishVerdictsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verifier = ClaimsVerifier.from_documents(EN_DOCS)

    def test_english_claims(self):
        cases = {
            "Revenue grew 7% in 2023.": Verdict.SUPPORTED,
            "Revenue grew 9% in 2023.": Verdict.CONTRADICTED,
            "Revenue decreased in 2023.": Verdict.CONTRADICTED,
            "The company opened new warehouses in 2023.": Verdict.CONTRADICTED,
            "Customer churn fell to about 4% in 2023.": Verdict.SUPPORTED,
            "The company was founded in 1990.": Verdict.NOT_ENOUGH_EVIDENCE,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertIs(verdict_of(self.verifier, text).verdict, expected)


class ConfigurationTest(unittest.TestCase):
    def test_stricter_support_threshold_downgrades_support(self):
        strict = ClaimsVerifier.from_documents(
            EN_DOCS, VerifierConfig(judge=JudgeConfig(support_min=1.01, numeric_support_bonus=0.0))
        )
        result = verdict_of(strict, "Revenue grew 7% in 2023.")
        self.assertIs(result.verdict, Verdict.PARTIALLY_SUPPORTED)

    def test_custom_synonyms_improve_coverage(self):
        docs = [make_document("d", "The central warehouse has 5 loading docks.")]
        claim = "The central depot has 5 loading docks."
        default = verdict_of(ClaimsVerifier.from_documents(docs), claim)
        tuned = verdict_of(
            ClaimsVerifier.from_documents(docs, VerifierConfig(synonym_groups=(("warehouse", "depot"),))), claim
        )
        self.assertIsNot(default.verdict, Verdict.SUPPORTED)
        self.assertIs(tuned.verdict, Verdict.SUPPORTED)

    def test_custom_judge_can_be_plugged_in(self):
        class AlwaysContradicts:
            name = "stub"

            def assess(self, claim, passage, retrieval_score):
                return PassageAssessment(passage, Stance.CONTRADICTS, 1.0, retrieval_score, (Signal("STUB", "x"),), (), ())

        verifier = ClaimsVerifier(ClaimsVerifier.from_documents(EN_DOCS).corpus, judge=AlwaysContradicts())
        report = verifier.verify_claims(["Revenue grew."])
        self.assertIs(report.results[0].verdict, Verdict.CONTRADICTED)
        self.assertEqual(report.engine["judge"], "stub")


class AggregationTest(unittest.TestCase):
    CLAIM = Claim("C1", "x y z", 0, 5)

    def _assessment(self, doc_id, stance, relevance=1.0, signals=()):
        passage = Passage(f"{doc_id}:p1", doc_id, "t", 0, 1, 1, "", "")
        return PassageAssessment(passage, stance, relevance, 1.0, tuple(signals), (), ())

    def test_corroboration_raises_score(self):
        single = aggregate(self.CLAIM, [self._assessment("a", Stance.SUPPORTS)], {})
        double = aggregate(
            self.CLAIM, [self._assessment("a", Stance.SUPPORTS), self._assessment("b", Stance.SUPPORTS)], {}
        )
        self.assertGreater(double.score, single.score)
        self.assertIn(Uncertainty.SINGLE_SOURCE, [u.code for u in single.uncertainty])
        self.assertNotIn(Uncertainty.SINGLE_SOURCE, [u.code for u in double.uncertainty])

    def test_weak_support_is_flagged(self):
        result = aggregate(self.CLAIM, [self._assessment("a", Stance.SUPPORTS, relevance=0.78)], {})
        self.assertIn(Uncertainty.WEAK_MATCH, [u.code for u in result.uncertainty])

    def test_evidence_list_is_bounded_and_excludes_neutral(self):
        many = [self._assessment(f"d{i}", Stance.SUPPORTS) for i in range(6)] + [self._assessment("n", Stance.NEUTRAL)]
        result = aggregate(self.CLAIM, many, {}, max_evidence=3)
        self.assertEqual(len(result.evidence), 3)
        self.assertTrue(all(e.stance is Stance.SUPPORTS for e in result.evidence))

    def test_score_is_capped(self):
        many = [self._assessment(f"d{i}", Stance.SUPPORTS) for i in range(5)]
        self.assertLessEqual(aggregate(self.CLAIM, many, {}).score, 0.99)


if __name__ == "__main__":
    unittest.main()
