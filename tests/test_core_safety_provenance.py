"""Safe verdicts, and provenance and coverage accounting."""

import io
import json
import tempfile
import unittest
from pathlib import Path

from claims_verifier import ClaimsVerifier, Verdict, make_document
from claims_verifier.cli import EXIT_INPUT_ERROR, EXIT_OK, main
from claims_verifier.corpus import CorpusError, load_corpus
from claims_verifier.inventory import Completeness, ExpectedSource, InventoryError, account, load_expected
from claims_verifier.report import to_dict, to_markdown

# Spanish-language fixture: the safe-verdict checks below exercise the Spanish lexicon (language-support
# test data). Provenance and report tests further down use English inputs.
DOCS = [
    make_document(
        "memoria",
        "---\ntitle: Memoria 2025 de Grupo Arandel\ndate: 2026-03-01\n---\n"
        "En 2025, Grupo Arandel adquirió el 60% de Textiles Morel.\n\n"
        "Grupo Arandel solicitó la licencia ambiental para la planta de Sorin.\n\n"
        "No se encontró registro de sanciones contra Textiles Morel.\n\n"
        "Los empleados de la planta de Sorin recibieron un bono de productividad.\n\n"
        "Los ingresos de Grupo Arandel crecieron 8% en 2025.\n\n"
        "Los costos operativos de Grupo Arandel aumentaron 12% en 2025.\n\n"
        "El gerente afirmó que la empresa duplicará sus exportaciones.\n",
    )
]


class SafeVerdictsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.verifier = ClaimsVerifier.from_documents(DOCS)

    def verdict(self, claim):
        return self.verifier.verify_claims([claim]).results[0]

    def test_supported_control(self):
        self.assertIs(self.verdict("Grupo Arandel adquirió el 60% de Textiles Morel en 2025.").verdict, Verdict.SUPPORTED)

    def test_subject_object_inversion_abstains(self):
        result = self.verdict("Textiles Morel adquirió el 60% de Grupo Arandel en 2025.")
        self.assertIs(result.verdict, Verdict.INCONCLUSIVE)
        self.assertIsNone(result.score)

    def test_request_is_not_grant(self):
        self.assertIsNot(self.verdict("Grupo Arandel obtuvo la licencia ambiental para la planta de Sorin.").verdict,
                         Verdict.SUPPORTED)

    def test_absence_of_evidence_neither_supports_nor_contradicts(self):
        for claim in ("Textiles Morel no tiene sanciones.", "Textiles Morel tiene sanciones."):
            with self.subTest(claim=claim):
                self.assertNotIn(self.verdict(claim).verdict, {Verdict.SUPPORTED, Verdict.CONTRADICTED})

    def test_partial_population_is_not_full_support(self):
        result = self.verdict("Los empleados de Grupo Arandel recibieron un bono de productividad.")
        self.assertIs(result.verdict, Verdict.PARTIALLY_SUPPORTED)

    def test_figure_of_another_attribute_does_not_decide(self):
        result = self.verdict("Los ingresos de Grupo Arandel crecieron 12% en 2025.")
        self.assertIs(result.verdict, Verdict.CONTRADICTED)
        self.assertEqual(result.evidence[0].passage.text, "Los ingresos de Grupo Arandel crecieron 8% en 2025.")

    def test_attributed_statement_is_not_fact(self):
        self.assertIsNot(self.verdict("La empresa duplicará sus exportaciones.").verdict, Verdict.SUPPORTED)


class ProvenanceTest(unittest.TestCase):
    def make_corpus(self, root: Path) -> None:
        (root / "a.md").write_text("# A\n\nThe fleet has 20 trucks.", encoding="utf-8")
        (root / "b.txt").write_text("Text with verifiable data.", encoding="utf-8")
        (root / "empty.md").write_text("# Just a title\n", encoding="utf-8")
        (root / "broken.txt").write_bytes("café".encode("latin-1"))
        (root / "photo.png").write_bytes(b"\x89PNG")
        (root / ".hidden").write_text("x", encoding="utf-8")

    def test_inventory_distinguishes_received_examined_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_corpus(root)
            corpus = load_corpus(root)
        status = {s.path: (s.status.value, s.reason) for s in corpus.sources}
        self.assertEqual(status["a.md"], ("examined", None))
        self.assertEqual(status["b.txt"], ("examined", None))
        self.assertEqual(status["empty.md"], ("excluded", "no_text"))
        self.assertEqual(status["photo.png"], ("excluded", "unsupported_type"))
        self.assertEqual(status[".hidden"], ("excluded", "hidden"))
        self.assertEqual(status["broken.txt"][0], "excluded")
        self.assertIn("UTF-8", status["broken.txt"][1])
        self.assertEqual([d.doc_id for d in corpus.documents], ["a", "b"])

    def test_strict_mode_fails_on_unusable_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_corpus(root)
            with self.assertRaisesRegex(CorpusError, "UTF-8"):
                load_corpus(root, strict=True)

    def test_duplicate_ids_are_renamed_never_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("---\nid: x\n---\nOne two three.", encoding="utf-8")
            (root / "b.md").write_text("---\nid: x\n---\nFour five six.", encoding="utf-8")
            corpus = load_corpus(root)
        status = {s.path: (s.status.value, s.reason, s.doc_ids) for s in corpus.sources}
        self.assertEqual(status["a.md"], ("examined", None, ("x",)))
        self.assertEqual(status["b.md"], ("examined", "duplicate id renamed to x@b.md", ("x@b.md",)))
        self.assertEqual(sorted(d.doc_id for d in corpus.documents), ["x", "x@b.md"])

    def test_completeness_needs_an_expected_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_corpus(root)
            corpus = load_corpus(root)
        sha_a = next(s.sha256 for s in corpus.sources if s.path == "a.md")
        self.assertIs(account(corpus.sources, None).completeness, Completeness.UNVERIFIABLE)
        sha_b = next(s.sha256 for s in corpus.sources if s.path == "b.txt")
        complete = account(corpus.sources, [ExpectedSource("./a.md", sha_a.upper()), ExpectedSource("b.txt", sha_b)])
        self.assertIs(complete.completeness, Completeness.COMPLETE)
        self.assertIn("photo.png", complete.unexpected)
        unversioned = account(corpus.sources, [ExpectedSource("a.md", sha_a), ExpectedSource("b.txt")])
        self.assertIs(unversioned.completeness, Completeness.COMPLETE_UNVERSIONED)
        gaps = account(corpus.sources, [ExpectedSource("a.md", "0" * 64), ExpectedSource("c.md"), ExpectedSource("empty.md")])
        self.assertIs(gaps.completeness, Completeness.INCOMPLETE)
        self.assertEqual((gaps.missing, gaps.version_mismatch, gaps.excluded_expected), (("c.md",), ("a.md",), ("empty.md",)))

    def test_expected_inventory_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "e.json"
            path.write_text('["a.md", {"path": "b.txt", "sha256": "abc"}]', encoding="utf-8")
            self.assertEqual(load_expected(path)[1], ExpectedSource("b.txt", "abc"))
            for content in ("[]", '[{"x": 1}]', "{oops"):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(InventoryError):
                    load_expected(path)


class ReportProvenanceTest(unittest.TestCase):
    def test_report_links_results_to_sources_and_marks_score_uncalibrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("---\nversion: v3\n---\nThe fleet has 20 trucks.", encoding="utf-8")
            (root / "photo.png").write_bytes(b"x")
            report = ClaimsVerifier(load_corpus(root), expected=[ExpectedSource("a.md"), ExpectedSource("z.md")]) \
                .verify_claims(["The fleet has 20 trucks.", "The fleet has drones."])
        data = to_dict(report)
        supported, unknown = data["claims"]
        evidence = supported["evidence"][0]
        self.assertEqual(evidence["document_version"], "v3")
        self.assertEqual(len(evidence["passage_sha256"]), 64)
        self.assertEqual(supported["score_kind"], "heuristic_uncalibrated")
        self.assertEqual(supported["examined"]["documents"], ["a"])
        self.assertIsNone(unknown["score"])
        self.assertIn("NOT a calibrated probability", data["score_semantics"])
        sources = data["sources"]
        self.assertEqual((sources["received"], sources["examined"], len(sources["excluded"])), (2, 1, 1))
        self.assertEqual(sources["accounting"]["completeness"], "incomplete")
        self.assertEqual(sources["accounting"]["missing"], ["z.md"])
        markdown = to_markdown(report)
        self.assertIn("incomplete against the expected inventory", markdown)
        self.assertIn("not a probability", markdown)

    def test_in_memory_corpus_is_unverifiable(self):
        report = ClaimsVerifier.from_documents([make_document("d", "Revenue grew 8% in 2025.")]).verify_claims(
            ["Revenue grew 8%."])
        self.assertEqual(to_dict(report)["sources"]["accounting"]["completeness"], "unverifiable")
        self.assertIn("unverifiable", to_markdown(report))


class CliProvenanceTest(unittest.TestCase):
    def test_expected_and_strict_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "corpus"
            root.mkdir()
            (root / "a.md").write_text("The fleet has 20 trucks.", encoding="utf-8")
            (root / "broken.txt").write_bytes("café".encode("latin-1"))
            expected = Path(tmp) / "expected.json"
            expected.write_text('["a.md"]', encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            code = main(["verify", "--corpus", str(root), "--claims", "-", "--format", "json", "--expected", str(expected)],
                        stdin=io.StringIO("The fleet has 20 trucks."), stdout=out, stderr=err)
            self.assertEqual(code, EXIT_OK)
            self.assertEqual(json.loads(out.getvalue())["sources"]["accounting"]["completeness"], "complete_unversioned")
            code = main(["verify", "--corpus", str(root), "--claims", "-", "--strict"],
                        stdin=io.StringIO("x y z"), stdout=io.StringIO(), stderr=err)
            self.assertEqual(code, EXIT_INPUT_ERROR)
            expected.write_text("[]", encoding="utf-8")
            code = main(["verify", "--corpus", str(root), "--claims", "-", "--expected", str(expected)],
                        stdin=io.StringIO("x y z"), stdout=io.StringIO(), stderr=err)
            self.assertEqual(code, EXIT_INPUT_ERROR)


if __name__ == "__main__":
    unittest.main()
