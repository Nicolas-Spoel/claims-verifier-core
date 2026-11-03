"""Input-hardening tests: skipped segments, limits, provenance flags and output sanitising."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from claims_verifier import ClaimsVerifier, make_document
from claims_verifier.claims import MAX_CLAIM_CHARS, claims_from_texts, extract_claims
from claims_verifier.cli import EXIT_FAIL_ON, EXIT_INPUT_ERROR, main
from claims_verifier.corpus import load_corpus
from claims_verifier.inventory import Completeness, ExpectedSource, account
from claims_verifier.report import to_json


class SkipBypassTest(unittest.TestCase):
    def test_pleasantry_cannot_hide_a_factual_claim(self):
        extraction = extract_claims("Revenue in 2025 fell 40%, hope this helps.")
        self.assertEqual(len(extraction.claims), 1)

    def test_plain_pleasantry_is_still_skipped(self):
        extraction = extract_claims("I hope this information is useful to you.")
        self.assertEqual((len(extraction.claims), extraction.skipped[0].factual), (0, False))

    def test_factual_question_and_heading_are_reported_unchecked(self):
        extraction = extract_claims("# Revenue 2025: 48 million\nDid you know that revenue fell 40% in 2025?")
        self.assertTrue(all(s.factual for s in extraction.skipped))

    def test_too_long_claims_are_unchecked_not_dropped(self):
        extraction = claims_from_texts(["The fleet has 20 trucks.", "x " * MAX_CLAIM_CHARS])
        self.assertEqual(len(extraction.claims), 1)
        self.assertEqual((extraction.skipped[0].reason, extraction.skipped[0].factual), ("too_long", True))

    def test_fail_on_unchecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.md").write_text("The fleet has 20 trucks.", encoding="utf-8")
            err = io.StringIO()
            code = main(["verify", "--corpus", tmp, "--answer", "-", "--fail-on", "UNCHECKED"],
                        stdin=io.StringIO("Did you know that the fleet has 90 new trucks?"), stdout=io.StringIO(), stderr=err)
        self.assertEqual(code, EXIT_FAIL_ON)
        self.assertIn("UNCHECKED", err.getvalue())


class UnexpectedSourcesTest(unittest.TestCase):
    def test_extra_sources_prevent_completeness_and_are_flagged_on_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("The fleet has 20 trucks.", encoding="utf-8")
            (root / "z.md").write_text("The plant has 9 kilns.", encoding="utf-8")
            corpus = load_corpus(root)
            sha_a = next(s.sha256 for s in corpus.sources if s.path == "a.md")
            expected = [ExpectedSource("a.md", sha_a)]
            self.assertIs(account(corpus.sources, expected).completeness, Completeness.UNEXPECTED_SOURCES)
            report = ClaimsVerifier(corpus, expected=expected).verify_claims(["The plant has 9 kilns."])
        data = json.loads(to_json(report))
        self.assertFalse(data["claims"][0]["evidence"][0]["source_in_expected_inventory"])


class IngestionRobustnessTest(unittest.TestCase):
    def test_hostile_entries_are_excluded_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ok.md").write_text("The fleet has 20 trucks.", encoding="utf-8")
            (root / "surrogate.json").write_text('[{"text": "\\ud800 text"}]', encoding="utf-8")
            (root / "deep.json").write_text("[" * 100_000 + "]" * 100_000, encoding="utf-8")
            os.symlink(root / "missing.md", root / "dangling.md")
            os.mkfifo(root / "pipe.md")
            corpus = load_corpus(root)
        status = {s.path: s.status.value for s in corpus.sources}
        self.assertEqual(status["ok.md"], "examined")
        for name in ("surrogate.json", "deep.json", "dangling.md", "pipe.md"):
            self.assertEqual(status[name], "excluded", name)

    def test_long_runs_of_punctuation_are_linear(self):
        import time
        from claims_verifier.text import split_sentences
        started = time.perf_counter()
        list(split_sentences("a" + "!" * 100_000 + "b"))
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_long_whitespace_runs_in_claims_are_bounded(self):
        import time
        started = time.perf_counter()
        ClaimsVerifier.from_documents([make_document("d", "The fleet has 20 trucks.")]).verify_claims(
            ["a" + " " * 1990 + "b"])
        self.assertLess(time.perf_counter() - started, 2.0)


class OutputSanitisingTest(unittest.TestCase):
    def test_json_escapes_c1_controls(self):
        report = ClaimsVerifier.from_documents([make_document("d", "The fleet\x9b has 20 trucks.")]).verify_claims(
            ["The fleet has 20 trucks."])
        self.assertNotIn("\x9b", to_json(report))

    def test_cli_errors_neutralise_control_characters(self):
        err = io.StringIO()
        code = main(["verify", "--corpus", "/nonexistent/\x1b[31mred", "--answer", "-"], stdin=io.StringIO("x"),
                    stdout=io.StringIO(), stderr=err)
        self.assertEqual(code, EXIT_INPUT_ERROR)
        self.assertNotIn("\x1b", err.getvalue())


if __name__ == "__main__":
    unittest.main()
