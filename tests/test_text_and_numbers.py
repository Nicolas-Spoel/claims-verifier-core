"""Text normalization, stemming, sentence splitting, Markdown stripping and number handling.

Spanish-language inputs in this module are deliberate: they exercise the Spanish lexicon, which the
engine keeps as language-support data alongside English.
"""

import unittest

from claims_verifier.numbers import NumberKind, Qualifier, extract_numbers, values_agree
from claims_verifier.text import content_stems, fold, split_sentences, stem, strip_markdown, synonym_map


class FoldAndStemTest(unittest.TestCase):
    def test_fold_removes_accents_and_case(self):
        self.assertEqual(fold("Aumentó la Facturación"), "aumento la facturacion")

    def test_stem_unifies_plural_and_singular(self):
        self.assertEqual(stem("camiones"), stem("camion"))
        self.assertEqual(stem("ventas"), stem("venta"))

    def test_content_stems_drop_stopwords_and_map_synonyms(self):
        self.assertEqual(content_stems("Los colaboradores de la empresa"), content_stems("empleados"))

    def test_extra_synonym_groups_extend_defaults(self):
        synonyms = synonym_map((("almacen", "deposito"),))
        self.assertEqual(content_stems("deposito", synonyms), content_stems("almacen", synonyms))
        self.assertEqual(content_stems("ventas", synonyms), content_stems("ingresos", synonyms))


class SentenceSplitTest(unittest.TestCase):
    def test_splits_on_terminal_punctuation(self):
        text = "Primera oración. Segunda oración! ¿Tercera?"
        spans = list(split_sentences(text))
        self.assertEqual([text[s:e] for s, e in spans], ["Primera oración.", "Segunda oración!", "¿Tercera?"])

    def test_does_not_split_on_abbreviations_or_decimals(self):
        text = "Nimbus Logística S.A.C. opera en Lima. Creció 12.5 por ciento. El Dr. Pérez lo confirmó."
        spans = list(split_sentences(text))
        self.assertEqual(len(spans), 3)

    def test_company_suffix_followed_by_capital_ends_the_sentence(self):
        text = "La operación involucra a Fenwar S.A. La CNCV la autorizó."
        self.assertEqual(len(list(split_sentences(text))), 2)

    def test_offsets_are_shifted(self):
        spans = list(split_sentences("Hello world.", offset=10))
        self.assertEqual(spans, [(10, 22)])


class MarkdownTest(unittest.TestCase):
    def test_strips_list_markers_and_emphasis(self):
        self.assertEqual(strip_markdown("- **Revenue** of [Nimbus](http://x)"), "Revenue of Nimbus")

    def test_flattens_table_rows(self):
        self.assertEqual(strip_markdown("| Fleet | 340 |"), "Fleet — 340")
        self.assertEqual(strip_markdown("|---|---|"), "")


class NumberExtractionTest(unittest.TestCase):
    def _single(self, text):
        numbers = extract_numbers(text)
        self.assertEqual(len(numbers), 1, numbers)
        return numbers[0]

    def test_spanish_decimal_comma_with_multiplier(self):
        n = self._single("ingresos de S/ 48,6 millones")
        self.assertAlmostEqual(n.value, 48_600_000)
        self.assertIs(n.kind, NumberKind.QUANTITY)

    def test_thousands_separator(self):
        self.assertEqual(self._single("1.240 colaboradores").value, 1240)
        self.assertEqual(self._single("1,240 employees").value, 1240)

    def test_mixed_separators(self):
        self.assertEqual(self._single("USD 1,234.5").value, 1234.5)
        self.assertEqual(self._single("S/ 1.234,5").value, 1234.5)

    def test_percent_and_year_kinds(self):
        kinds = [n.kind for n in extract_numbers("creció 12% en 2023 y 3 por ciento después")]
        self.assertEqual(kinds, [NumberKind.PERCENT, NumberKind.YEAR, NumberKind.PERCENT])

    def test_qualifiers(self):
        self.assertIs(self._single("más de 1.200 empleados").qualifier, Qualifier.AT_LEAST)
        self.assertIs(self._single("menos del 5%").qualifier, Qualifier.AT_MOST)
        self.assertIs(self._single("alrededor de 300 camiones").qualifier, Qualifier.APPROX)
        self.assertIs(self._single("300 camiones").qualifier, Qualifier.EXACT)

    def test_numbers_inside_words_are_ignored(self):
        self.assertEqual(extract_numbers("resultados del Q1"), ())


class NumberAgreementTest(unittest.TestCase):
    def _n(self, text):
        return extract_numbers(text)[0]

    def test_exact_values_agree(self):
        self.assertTrue(values_agree(self._n("340 camiones"), self._n("340 unidades")))
        self.assertFalse(values_agree(self._n("340 camiones"), self._n("325 camiones")))

    def test_claim_rounding_is_tolerated(self):
        self.assertTrue(values_agree(self._n("49 millones"), self._n("48,6 millones")))
        self.assertFalse(values_agree(self._n("48 millones"), self._n("48,6 millones")))

    def test_approximate_claim_widens_tolerance(self):
        self.assertTrue(values_agree(self._n("aproximadamente 1.200"), self._n("1.240")))

    def test_bounds(self):
        self.assertTrue(values_agree(self._n("más de 1.200"), self._n("1.240")))
        self.assertFalse(values_agree(self._n("más de 1.300"), self._n("1.240")))
        self.assertTrue(values_agree(self._n("menos de 10%"), self._n("8%")))
        self.assertFalse(values_agree(self._n("menos de 5%"), self._n("8%")))


if __name__ == "__main__":
    unittest.main()
