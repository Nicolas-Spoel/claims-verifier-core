"""Integration and end-to-end tests: report rendering, CLI and the reproducible demo."""

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from claims_verifier import ClaimsVerifier, make_document
from claims_verifier.cli import EXIT_FAIL_ON, EXIT_INPUT_ERROR, EXIT_OK, main
from claims_verifier.evaluation import CasesError, LabelledClaim, evaluate, load_cases
from claims_verifier.models import Verdict
from claims_verifier.report import to_dict, to_json, to_markdown
from claims_verifier.text import strip_markdown

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "demo"
BENCHMARK = ROOT / "examples" / "benchmark"


def run_cli(*argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    code = main(list(argv), stdin=io.StringIO(stdin), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


class ReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        docs = [make_document("d", "---\ndate: 2024-01-01\n---\nThe fleet has 20 <b>new</b> trucks | ok.")]
        cls.report = ClaimsVerifier.from_documents(docs).verify_answer(
            "The fleet has 20 trucks. The fleet has 25 trucks. There are offices on Mars. Anything else?"
        )

    def test_json_contains_traceable_evidence(self):
        data = to_dict(self.report)
        evidence = data["claims"][0]["evidence"][0]
        doc_text = self.report.documents[0].text
        start, end = evidence["char_span"]
        self.assertEqual(doc_text[start:end], evidence["quote"])
        self.assertEqual(evidence["document_sha256"], self.report.documents[0].sha256)
        self.assertEqual(evidence["document_date"], "2024-01-01")
        self.assertEqual(data["schema_version"], "2.0")

    def test_summary(self):
        summary = to_dict(self.report)["summary"]
        self.assertEqual(summary["total_claims"], 3)
        self.assertEqual(summary["by_verdict"]["SUPPORTED"], 1)
        self.assertEqual(summary["by_verdict"]["CONTRADICTED"], 1)
        self.assertEqual(summary["needs_review"], 2)
        self.assertEqual(summary["skipped_segments"], 1)
        self.assertAlmostEqual(summary["claims_with_related_evidence"], 0.67)
        self.assertEqual(summary["documents_not_cited"], [])

    def test_json_round_trips(self):
        self.assertEqual(json.loads(to_json(self.report))["summary"]["total_claims"], 3)

    def test_markdown_escapes_evidence_and_lists_limits(self):
        markdown = to_markdown(self.report)
        self.assertIn("&lt;b&gt;new&lt;/b&gt; trucks \\| ok.", markdown)
        self.assertNotIn("<b>", markdown)
        self.assertIn("## Verifier limitations", markdown)
        self.assertIn("## Skipped segments", markdown)


class CliTest(unittest.TestCase):
    def test_verify_markdown_to_stdout(self):
        code, out, _ = run_cli("verify", "--corpus", str(DEMO / "corpus"), "--answer", str(DEMO / "answer.md"))
        self.assertEqual(code, EXIT_OK)
        self.assertTrue(out.startswith("# Claim verification report"))

    def test_fail_on_returns_one_and_names_claims(self):
        code, _, err = run_cli(
            "verify", "--corpus", str(DEMO / "corpus"), "--answer", str(DEMO / "answer.md"),
            "--format", "json", "--fail-on", "contradicted,CONFLICTING",
        )
        self.assertEqual(code, EXIT_FAIL_ON)
        self.assertIn("C2, C5, C9", err)

    def test_claims_from_stdin_json_and_out_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_file = Path(tmp) / "sub" / "r.json"
            code, out, _ = run_cli(
                "verify", "--corpus", str(DEMO / "corpus"), "--claims", "-", "--format", "json", "--out", str(out_file),
                stdin='["The general manager is Lucía Ramos."]',
            )
            data = json.loads(out_file.read_text(encoding="utf-8"))
        self.assertEqual((code, out), (EXIT_OK, ""))
        self.assertEqual(data["claims"][0]["verdict"], "SUPPORTED")

    def test_claims_one_per_line_and_custom_synonyms(self):
        with tempfile.TemporaryDirectory() as tmp:
            corpus = Path(tmp) / "c.txt"
            corpus.write_text("The central warehouse has 5 loading docks.", encoding="utf-8")
            synonyms = Path(tmp) / "s.json"
            synonyms.write_text('[["warehouse", "depot"]]', encoding="utf-8")
            code, out, _ = run_cli(
                "verify", "--corpus", str(corpus), "--claims", "-", "--format", "json", "--synonyms", str(synonyms),
                stdin="The central depot has 5 loading docks.\n\n",
            )
        self.assertEqual(code, EXIT_OK)
        self.assertEqual(json.loads(out)["claims"][0]["verdict"], "SUPPORTED")

    def test_input_errors_exit_with_two(self):
        corpus = str(DEMO / "corpus")
        cases = [
            (("verify", "--corpus", "/nonexistent", "--answer", "-"), "", "corpus path not found"),
            (("verify", "--corpus", corpus, "--answer", "/nonexistent.md"), "", "file not found"),
            (("verify", "--corpus", corpus, "--answer", "-"), "  ", "answer is empty"),
            (("verify", "--corpus", corpus, "--claims", "-"), "[1, 2]", "array of strings"),
            (("verify", "--corpus", corpus, "--answer", "-", "--fail-on", "WRONG"), "x", "unknown verdict"),
            (("verify", "--corpus", corpus, "--answer", "-", "--top-k", "0"), "x", "--top-k"),
            (("verify", "--corpus", corpus, "--answer", "-", "--synonyms", "-"), "{", "synonyms JSON is invalid"),
        ]
        for argv, stdin, message in cases:
            with self.subTest(argv=argv):
                code, _, err = run_cli(*argv, stdin=stdin)
                self.assertEqual(code, EXIT_INPUT_ERROR)
                self.assertIn(message, err)

    def test_invalid_synonym_shape(self):
        code, _, err = run_cli(
            "verify", "--corpus", str(DEMO / "corpus"), "--claims", str(DEMO / "answer.md"), "--synonyms", "-",
            stdin='[["only"]]',
        )
        self.assertEqual(code, EXIT_INPUT_ERROR)
        self.assertIn("at least two strings", err)

    def test_evaluate_command(self):
        code, out, _ = run_cli(
            "evaluate", "--corpus", str(BENCHMARK / "corpus"), "--cases", str(BENCHMARK / "cases.json"),
            "--min-accuracy", "0.9",
        )
        self.assertEqual(code, EXIT_OK)
        self.assertGreaterEqual(json.loads(out)["accuracy"], 0.9)

    def test_evaluate_command_errors_and_threshold(self):
        code, _, err = run_cli("evaluate", "--corpus", str(BENCHMARK / "corpus"), "--cases", "/nonexistent.json")
        self.assertEqual(code, EXIT_INPUT_ERROR)
        self.assertIn("cannot read cases", err)
        code, _, _ = run_cli(
            "evaluate", "--corpus", str(BENCHMARK / "corpus"), "--cases", str(BENCHMARK / "cases.json"),
            "--min-accuracy", "1.01",
        )
        self.assertEqual(code, EXIT_FAIL_ON)


class EvaluationTest(unittest.TestCase):
    def test_confusion_and_misses(self):
        verifier = ClaimsVerifier.from_documents([make_document("d", "The fleet has 20 trucks.")])
        cases = [
            LabelledClaim("The fleet has 20 trucks.", Verdict.SUPPORTED),
            LabelledClaim("The fleet has 30 trucks.", Verdict.SUPPORTED),
        ]
        result = evaluate(verifier, cases)
        self.assertEqual((result.total, result.correct, result.accuracy), (2, 1, 0.5))
        self.assertEqual(result.confusion["SUPPORTED"]["CONTRADICTED"], 1)
        self.assertEqual(result.misses[0].actual, Verdict.CONTRADICTED)

    def test_invalid_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.json"
            for content, message in (("[]", "non-empty"), ('[{"claim": "x", "expected": "MAYBE"}]', "case 0")):
                path.write_text(content, encoding="utf-8")
                with self.assertRaisesRegex(CasesError, message):
                    load_cases(path)

    def test_unevaluable_cases_are_rejected_not_misaligned(self):
        """An empty or over-long case is rejected instead of shifting every later result onto the wrong case."""
        verifier = ClaimsVerifier.from_documents([make_document("d", "The fleet has 20 trucks.")])
        good = LabelledClaim("The fleet has 20 trucks.", Verdict.SUPPORTED)
        for bad in ("  ", "x " * 1500, "x" * 2001):
            with self.subTest(length=len(bad)):
                with self.assertRaisesRegex(CasesError, "case 0"):
                    evaluate(verifier, [LabelledClaim(bad, Verdict.NOT_ENOUGH_EVIDENCE), good])
        edge = LabelledClaim(" " + "x" * 2000 + " ", Verdict.NOT_ENOUGH_EVIDENCE)  # trimmed length is the limit
        self.assertEqual(evaluate(verifier, [edge, good]).total, 2)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.json"
            path.write_text('[{"claim": "", "expected": "SUPPORTED"}]', encoding="utf-8")
            code, _, err = run_cli("evaluate", "--corpus", str(BENCHMARK / "corpus"), "--cases", str(path))
        self.assertEqual(code, EXIT_INPUT_ERROR)
        self.assertIn("case 0", err)


class BenchmarkGuardTest(unittest.TestCase):
    """Every labelled benchmark case gets its expected verdict, except the documented residual cases, which
    must still never receive a false SUPPORTED or CONTRADICTED (see "Known issues" in the README)."""

    RESIDUAL = {BENCHMARK: {13, 18}, BENCHMARK / "extra": {2, 3, 6, 7, 9, 10, 24}}
    DECISIVE = {Verdict.SUPPORTED, Verdict.CONTRADICTED}

    def results(self, folder):
        cases = load_cases(folder / "cases.json")
        verifier = ClaimsVerifier.from_path(folder / "corpus")
        return [(i, case, verifier.verify_claims([case.claim]).results[0].verdict) for i, case in enumerate(cases, 1)]

    def test_cases_get_their_expected_verdict(self):
        for folder, residual in self.RESIDUAL.items():
            for index, case, actual in self.results(folder):
                if index not in residual:
                    with self.subTest(benchmark=folder.name, case=index):
                        self.assertIs(actual, case.expected, case.claim)

    def test_no_case_is_falsely_supported_or_contradicted(self):
        for folder in self.RESIDUAL:
            for index, case, actual in self.results(folder):
                with self.subTest(benchmark=folder.name, case=index):
                    self.assertFalse(actual in self.DECISIVE and actual is not case.expected, f"{case.claim}: {actual}")


class DemoGoldenTest(unittest.TestCase):
    """The reproducible demo must keep producing the documented verdicts, byte-for-byte deterministic."""

    def test_demo_verdicts_match_expected(self):
        expected = json.loads((DEMO / "expected_verdicts.json").read_text(encoding="utf-8"))
        report = ClaimsVerifier.from_path(DEMO / "corpus").verify_answer((DEMO / "answer.md").read_text(encoding="utf-8"))
        actual = {r.claim.claim_id: r.verdict.value for r in report.results}
        self.assertEqual(actual, expected)

    def test_demo_report_is_deterministic(self):
        answer = (DEMO / "answer.md").read_text(encoding="utf-8")
        first = to_json(ClaimsVerifier.from_path(DEMO / "corpus").verify_answer(answer))
        second = to_json(ClaimsVerifier.from_path(DEMO / "corpus").verify_answer(answer))
        self.assertEqual(first, second)

    def test_every_non_supported_claim_explains_itself(self):
        report = ClaimsVerifier.from_path(DEMO / "corpus").verify_answer((DEMO / "answer.md").read_text(encoding="utf-8"))
        for result in report.results:
            with self.subTest(claim=result.claim.claim_id):
                self.assertTrue(result.rationale)
                if result.verdict is not Verdict.SUPPORTED:
                    self.assertTrue(result.uncertainty or result.evidence)


class ExampleReproducibilityTest(unittest.TestCase):
    """The committed example reports are reproduced byte for byte and their evidence points into the original files."""

    def test_cli_reproduces_committed_reports(self):
        for fmt, name in (("json", "report.json"), ("markdown", "report.md")):
            with self.subTest(format=fmt), tempfile.TemporaryDirectory() as tmp:
                out_file = Path(tmp) / name
                code, _, _ = run_cli("verify", "--corpus", str(DEMO / "corpus"), "--answer", str(DEMO / "answer.md"),
                                     "--format", fmt, "--out", str(out_file))
                self.assertEqual(code, EXIT_OK)
                self.assertEqual(out_file.read_bytes(), (DEMO / "expected" / name).read_bytes())

    def test_evidence_offsets_and_hashes_match_original_files(self):
        report = json.loads((DEMO / "expected" / "report.json").read_text(encoding="utf-8"))
        corpus = DEMO / "corpus"
        for record in report["sources"]["records"]:
            self.assertEqual(record["sha256"], hashlib.sha256((corpus / record["path"]).read_bytes()).hexdigest())
        checked = 0
        for claim in report["claims"]:
            for item in claim["evidence"]:
                path, _, index = item["source_path"].partition("#")
                text = (corpus / path).read_bytes().decode("utf-8-sig")
                if index:  # JSON record: the document text is the record's "text" field
                    data = json.loads(text)
                    text = (data if isinstance(data, dict) else data[int(index)])["text"]
                start, end = item["char_span"]
                with self.subTest(claim=claim["claim_id"], passage=item["passage_id"]):
                    self.assertEqual(text[start:end], item["quote"])
                    self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(), item["document_sha256"])
                    self.assertEqual(text.count("\n", 0, start) + 1, item["line"])
                checked += 1
        self.assertGreater(checked, 0)

    def test_example_inventories_report_completeness(self):
        for name, state, missing in (("inventory.json", "complete", []),
                                     ("inventory_incomplete.json", "incomplete", ["financial_statements_2023.md"])):
            with self.subTest(inventory=name):
                code, out, _ = run_cli("verify", "--corpus", str(DEMO / "corpus"), "--answer", str(DEMO / "answer.md"),
                                       "--format", "json", "--expected", str(DEMO / name))
                self.assertEqual(code, EXIT_OK)
                accounting = json.loads(out)["sources"]["accounting"]
                self.assertEqual((accounting["completeness"], accounting["missing"]), (state, missing))

    def test_passage_hash_follows_the_documented_normalisation(self):
        report = json.loads((DEMO / "expected" / "report.json").read_text(encoding="utf-8"))
        items = [item for claim in report["claims"] for item in claim["evidence"]]
        self.assertTrue(items)
        for item in items:
            normalised = " ".join(strip_markdown(line) for line in item["quote"].splitlines()).strip()
            with self.subTest(passage=item["passage_id"]):
                self.assertEqual(hashlib.sha256(normalised.encode("utf-8")).hexdigest(), item["passage_sha256"])

    def test_markdown_extension_is_loaded_with_offsets(self):
        text = "# Note\n\nThe fleet has 20 trucks."
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "note.markdown").write_text(text, encoding="utf-8")
            report = ClaimsVerifier.from_path(Path(tmp)).verify_claims(["The fleet has 20 trucks."])
        evidence = to_dict(report)["claims"][0]["evidence"][0]
        self.assertIs(report.results[0].verdict, Verdict.SUPPORTED)
        self.assertEqual(evidence["source_path"], "note.markdown")
        self.assertEqual(text[slice(*evidence["char_span"])], evidence["quote"])


if __name__ == "__main__":
    unittest.main()
