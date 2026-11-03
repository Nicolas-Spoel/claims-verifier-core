"""Edge-case tests for numbers, alignment, dates, text, corpus loading, reports and CLI.

A few number and year tests use Spanish inputs on purpose (Spanish-language support test data).
"""

import io
import tempfile
import time
import unittest
from pathlib import Path

from claims_verifier import ClaimsVerifier, Verdict, make_document
from claims_verifier.aggregate import _newest
from claims_verifier.claims import claims_from_texts
from claims_verifier.cli import EXIT_INPUT_ERROR, EXIT_OK, main
from claims_verifier.corpus import load_documents
from claims_verifier.numbers import NumberKind, extract_numbers
from claims_verifier.report import to_dict, to_markdown
from claims_verifier.signals import analyze
from claims_verifier.text import fold, split_sentences

DEMO = Path(__file__).resolve().parents[1] / "examples" / "demo"


def verdict(evidence, claim):
    return ClaimsVerifier.from_documents([make_document("d", evidence)]).verify_claims([claim]).results[0].verdict


class NumberFindingsTest(unittest.TestCase):
    def test_sign_is_kept(self):
        self.assertEqual(extract_numbers("dropped to -5 degrees")[0].value, -5)
        self.assertEqual(extract_numbers("fell −5%")[0].value, -5)
        self.assertEqual(extract_numbers("2022-2023")[1].value, 2023)
        self.assertIs(verdict("Revenue grew 5% in 2023.", "Revenue grew -5% in 2023."), Verdict.CONTRADICTED)

    def test_spelled_multiplier_decides_the_separator(self):
        # Spanish "millones" uses "." for thousands and "," for decimals.
        self.assertEqual(extract_numbers("1,950 million")[0].value, 1_950_000_000)
        self.assertEqual(extract_numbers("1.950 millones")[0].value, 1_950_000_000)
        self.assertEqual(extract_numbers("3,125 millones")[0].value, 3_125_000)
        self.assertIs(verdict("Revenue was 1,950 million in 2023.", "Revenue was 1950 million in 2023."), Verdict.SUPPORTED)

    def test_year_needs_temporal_context(self):
        self.assertIs(extract_numbers("employs 2000 workers")[0].kind, NumberKind.QUANTITY)
        # Spanish year markers ("en 2023", "2023 fue ...").
        self.assertIs(extract_numbers("en 2023 la flota")[0].kind, NumberKind.YEAR)
        self.assertIs(extract_numbers("2023 fue un buen año")[0].kind, NumberKind.YEAR)
        evidence = "The firm employs 2,000 workers according to the 2023 report."
        self.assertIs(verdict(evidence, "The firm employs 2000 workers."), Verdict.SUPPORTED)

    def test_bare_m_is_not_million(self):
        self.assertEqual(extract_numbers("10 m tall")[0].value, 10)
        self.assertEqual(extract_numbers("USD 5M")[0].value, 5_000_000)

    def test_numeric_dates_compare_exactly(self):
        self.assertIs(extract_numbers("signed on 12/03/2023")[0].kind, NumberKind.DATE)
        evidence = "The contract was signed on 12/03/2023."
        self.assertIs(verdict(evidence, "The contract was signed on 03/12/2023."), Verdict.CONTRADICTED)
        self.assertIs(verdict(evidence, "The contract was signed on 12/03/2023."), Verdict.SUPPORTED)


class AlignmentAndDateFindingsTest(unittest.TestCase):
    def test_number_must_count_the_same_thing(self):
        evidence = "There were 1.5 million users and 300 admins in the system."
        self.assertIsNot(verdict(evidence, "There were 300 users in the system."), Verdict.SUPPORTED)

    def test_every_year_of_a_dated_event_must_match(self):
        evidence = "The contract ran from March 2023 to June 2024."
        self.assertIs(verdict(evidence, "The contract ran from March 2023 to June 2025."), Verdict.CONTRADICTED)
        self.assertIs(verdict(evidence, "The contract ran from March 2023 to June 2024."), Verdict.SUPPORTED)


class TextFindingsTest(unittest.TestCase):
    def test_fold_preserves_length(self):
        for text in ("ﬁnal ﬂow", "½ in total", "Straße", "Aumentó", "emoji 🚀 ok"):
            with self.subTest(text=text):
                self.assertEqual(len(fold(text)), len(text))

    def test_number_offsets_survive_ligatures(self):
        text = "The ﬁnancial ﬂow ﬁnal revenue grew 5% in 2023"
        self.assertEqual([n.raw for n in extract_numbers(text)], ["5%", "2023"])
        self.assertEqual([n.mention.raw for n in analyze("ﬁnal result rose 5 %, but costs fell").numbers], ["5 %"])

    def test_sentence_splitting_is_linear(self):
        started = time.perf_counter()
        text = "a. " * 50_000
        spans = list(split_sentences(text))
        self.assertLess(time.perf_counter() - started, 1.0)
        self.assertTrue(all(e - s <= 1000 for s, e in spans))
        self.assertEqual("".join(text[s:e] for s, e in spans).replace(" ", ""), text.replace(" ", ""))


class CorpusFindingsTest(unittest.TestCase):
    def test_bom_and_leading_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bom.md").write_text("\ufeff---\ntitle: T\ndate: 2024-01-01\n---\nBody.", encoding="utf-8")
            (root / "rule.md").write_text("---\nText after a horizontal rule.", encoding="utf-8")
            docs = {d.doc_id: d for d in load_documents(root)}
        self.assertEqual(docs["bom"].title, "T")
        self.assertEqual(docs["bom"].date, "2024-01-01")
        self.assertEqual(docs["rule"].metadata, {})

    def test_newest_source_uses_real_dates(self):
        self.assertEqual(_newest(["a", "b", "c"], {"a": "2024-09-01", "b": "2024-10-01", "c": "01/02/2025"}), "b")


class ReportAndCliFindingsTest(unittest.TestCase):
    def test_markdown_escapes_every_untrusted_field(self):
        doc = make_document(
            "<b>x</b>`id",
            "---\ndate: <i>2024</i>\n---\nThe fleet has 20 trucks ![t](http://example.invalid/x.png) [c](javascript:alert(1)).",
            source_path="path`with`backticks.md",
        )
        extra = make_document("[link](http://example.invalid)", "Completely unrelated text.")
        report = ClaimsVerifier.from_documents([doc, extra]).verify_claims(["The fleet has 20 trucks."])
        markdown = to_markdown(report)
        for injected in ("<b>", "<i>", "![t](", "[c](", "[link](", "path`with"):
            self.assertNotIn(injected, markdown)

    def test_pre_extracted_claims_are_numbered_after_filtering_without_spans(self):
        extraction = claims_from_texts(["", "x y z"])
        self.assertEqual(extraction.claims[0].claim_id, "C1")
        self.assertIsNone(extraction.claims[0].char_start)

    def test_report_json_has_null_span_for_pre_extracted_claims(self):
        report = ClaimsVerifier.from_path(DEMO / "corpus").verify_claims(["The general manager is Lucía Ramos."])
        self.assertIsNone(to_dict(report)["claims"][0]["char_span"])

    def run_cli(self, *argv, stdin=""):
        err = io.StringIO()
        return main(list(argv), stdin=io.StringIO(stdin), stdout=io.StringIO(), stderr=err), err.getvalue()

    def test_oversized_stdin_is_rejected(self):
        code, err = self.run_cli("verify", "--corpus", str(DEMO / "corpus"), "--claims", "-", stdin="x" * 2_000_001)
        self.assertEqual(code, EXIT_INPUT_ERROR)
        self.assertIn("stdin exceeds", err)

    def test_claims_lines_may_start_with_brackets(self):
        code, _ = self.run_cli(
            "verify", "--corpus", str(DEMO / "corpus"), "--claims", "-", stdin="[1] The general manager is Lucía Ramos.\n"
        )
        self.assertEqual(code, EXIT_OK)

    def test_os_errors_are_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, err = self.run_cli(
                "verify", "--corpus", str(DEMO / "corpus"), "--answer", str(DEMO / "answer.md"), "--out", tmp
            )
        self.assertEqual(code, EXIT_INPUT_ERROR)
        self.assertIn("error", err)

    def test_top_k_is_capped(self):
        code, err = self.run_cli("verify", "--corpus", str(DEMO / "corpus"), "--answer", "-", "--top-k", "1000", stdin="x")
        self.assertEqual(code, EXIT_INPUT_ERROR)
        self.assertIn("--top-k", err)


if __name__ == "__main__":
    unittest.main()
