"""Signal extraction: polarity, direction, hedging, quantifiers, dates and modality.

Spanish-language inputs in this module are deliberate: they exercise the Spanish lexicon, which the
engine keeps as language-support data alongside English.
"""

import unittest

from claims_verifier.signals import Direction, analyze


class PolarityTest(unittest.TestCase):
    def test_detects_negation(self):
        self.assertTrue(analyze("La tasa no disminuyó").negated)
        self.assertFalse(analyze("La tasa disminuyó").negated)

    def test_ignores_negation_false_friends(self):
        self.assertFalse(analyze("Sin embargo, la tasa disminuyó").negated)
        self.assertFalse(analyze("No solo creció la flota").negated)

    def test_focus_uses_the_clause_that_matches_the_claim(self):
        signals = analyze("La empresa, que no cotiza en bolsa, registró ingresos récord")
        negated, _ = signals.focus(analyze("registró ingresos récord").stems)
        self.assertFalse(negated)
        self.assertTrue(signals.negated)


class DirectionTest(unittest.TestCase):
    def test_up_and_down(self):
        self.assertIs(analyze("Los ingresos aumentaron").direction, Direction.UP)
        self.assertIs(analyze("Revenue fell sharply").direction, Direction.DOWN)

    def test_mixed_sentence_has_no_single_direction(self):
        self.assertIsNone(analyze("Las ventas crecieron y los costos disminuyeron").direction)

    def test_focus_resolves_direction_per_clause(self):
        signals = analyze("Las ventas crecieron y los costos disminuyeron")
        _, direction = signals.focus(analyze("los costos").stems)
        self.assertIs(direction, Direction.DOWN)


class HedgeQuantifierDateTest(unittest.TestCase):
    def test_hedges(self):
        self.assertTrue(analyze("El centro podría abrir en 2025").hedged)
        self.assertTrue(analyze("Se estima un ahorro de 10%").hedged)
        self.assertTrue(analyze("Revenue is expected to grow").hedged)
        self.assertFalse(analyze("El centro abrió en 2023").hedged)

    def test_quantifiers(self):
        self.assertTrue(analyze("Todos los clientes renovaron").universal)
        self.assertTrue(analyze("Algunos clientes renovaron").partial)
        self.assertTrue(analyze("El 78% de los clientes renovó").has_partial_percentage)

    def test_months_and_years(self):
        signals = analyze("En marzo de 2023 abrió el centro")
        self.assertEqual(signals.months, frozenset({3}))
        self.assertEqual(signals.years, frozenset({2023}))

    def test_numbers_are_anchored_to_their_clause(self):
        signals = analyze("Las ventas crecieron 12% y los costos 5%")
        contexts = {n.mention.value: n.context for n in signals.measures}
        sales = analyze("ventas").stems[0]
        self.assertIn(sales, contexts[12.0])
        self.assertNotIn(sales, contexts[5.0])


class ModalityAndTrendTest(unittest.TestCase):
    def test_future_counts_as_hedged_but_not_conditional(self):
        signals = analyze("La planta abrirá en 2027")
        self.assertTrue(signals.hedged)
        self.assertFalse(signals.conditional)

    def test_conditional_mood_and_if_clauses(self):
        self.assertTrue(analyze("Las obras comenzarían en 2027").conditional)
        self.assertTrue(analyze("Si se aprueba el crédito, las obras empiezan en 2027").conditional)
        self.assertTrue(analyze("The plant would open next year").conditional)
        self.assertFalse(analyze("Sí, la secretaría aprobó el plan").conditional)

    def test_figure_compared_with_baseline_implies_direction(self):
        self.assertIs(analyze("La morosidad fue de 3,1% en 2025, frente a 3,6% en 2024").direction, Direction.DOWN)
        self.assertIs(analyze("Se registraron 9 casos, frente a 4 el año anterior").direction, Direction.UP)
        self.assertIsNone(analyze("La morosidad fue de 3,1% en 2025").direction)

    def test_negated_predicate_clause_is_in_focus(self):
        signals = analyze("En la revisión del proceso de ingresos de Arandel, los auditores no identificaron observaciones.")
        negations, _ = signals.focus(analyze("Los auditores identificaron observaciones en el proceso de ingresos de Arandel").stems)
        self.assertTrue(negations)


if __name__ == "__main__":
    unittest.main()
