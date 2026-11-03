"""Regression tests for edge cases in lexical judgement (synthetic data).

Spanish-language inputs in this module are deliberate: they exercise the Spanish lexicon, which the
engine keeps as language-support data alongside English.
"""

import unittest

from claims_verifier import ClaimsVerifier, Verdict, make_document
from claims_verifier.signals import Direction, analyze

DOCS = [
    make_document(
        "coop",
        "En 2024 la cooperativa acopió 4.850 toneladas de café, un 6% menos que en 2023 por las lluvias.\n\n"
        "La cooperativa agrupa a 2.300 socios, de los cuales el 41% son mujeres.\n\n"
        "El 72% del café obtuvo certificación orgánica.\n\n"
        "Las pérdidas de agua no facturada disminuyeron de 38% a 33% entre 2022 y 2023.\n\n"
        "El margen fue de 7% y los costos bajaron.\n",
    )
]


class RegressionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verifier = ClaimsVerifier.from_documents(DOCS)

    def verdict(self, text):
        return self.verifier.verify_claims([text]).results[0].verdict

    def test_verbless_comparative_applies_to_the_previous_clause(self):
        signals = analyze("acopió 4.850 toneladas, un 6% menos que en 2023")
        self.assertIs(signals.clauses[0].direction, Direction.DOWN)
        self.assertIs(self.verdict("El acopio de café aumentó en 2024 respecto a 2023."), Verdict.CONTRADICTED)
        self.assertIs(self.verdict("El acopio de 2024 cayó un 6% por las lluvias."), Verdict.SUPPORTED)

    def test_direction_in_an_unrelated_clause_does_not_support_or_contradict(self):
        self.assertNotIn(self.verdict("El margen aumentó."), {Verdict.SUPPORTED, Verdict.CONTRADICTED})

    def test_approximation_words_are_not_required_terms(self):
        self.assertIs(self.verdict("Cerca de 5.000 toneladas de café fueron acopiadas en 2024."), Verdict.SUPPORTED)

    def test_majority_is_checked_against_percentages(self):
        self.assertIs(self.verdict("La mayoría de los socios son mujeres."), Verdict.CONTRADICTED)
        self.assertIs(self.verdict("Una minoría de los socios son mujeres."), Verdict.SUPPORTED)
        self.assertIs(self.verdict("La mayoría del café obtuvo certificación orgánica."), Verdict.SUPPORTED)

    def test_shared_lexical_negation_is_not_clause_polarity(self):
        self.assertIs(self.verdict("Las pérdidas de agua no facturada aumentaron en 2023."), Verdict.CONTRADICTED)
        self.assertIs(self.verdict("Las pérdidas de agua no facturada bajaron a 33% en 2023."), Verdict.SUPPORTED)


if __name__ == "__main__":
    unittest.main()
