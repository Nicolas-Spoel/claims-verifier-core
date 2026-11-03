"""Front matter, segmentation, corpus loading, claim extraction and retrieval.

`ClaimExtractionTest` keeps Spanish inputs on purpose (Spanish-language support test data): it exercises
the Spanish connectors and pleasantry patterns, which the engine keeps alongside English.
"""

import json
import tempfile
import unittest
from pathlib import Path

from claims_verifier.claims import AnswerError, claims_from_texts, extract_claims
from claims_verifier.corpus import (
    CorpusError,
    build_corpus,
    load_corpus,
    load_documents,
    make_document,
    parse_front_matter,
    segment_document,
)
from claims_verifier.retrieval import Bm25Index
from claims_verifier.text import content_stems

DOC = """---
title: Synthetic report
date: 2024-01-31
---

# Synthetic report

## Sales

Sales grew 10%. The margin was 5%.

- The fleet has 20 trucks.
"""


class FrontMatterTest(unittest.TestCase):
    def test_parses_metadata_and_body_offset(self):
        metadata, offset = parse_front_matter(DOC)
        self.assertEqual(metadata["title"], "Synthetic report")
        self.assertEqual(metadata["date"], "2024-01-31")
        self.assertTrue(DOC[offset:].lstrip().startswith("# Synthetic"))

    def test_no_front_matter(self):
        self.assertEqual(parse_front_matter("text"), ({}, 0))

    def test_malformed_front_matter_is_kept_as_body_text(self):
        self.assertEqual(parse_front_matter("---\ntitle: x\n"), ({}, 0))
        self.assertEqual(parse_front_matter("---\nBody after rule. More text.\n---\nTail."), ({}, 0))
        passages = segment_document(make_document("d", "---\nBody after rule.\n---\nTail."))
        self.assertIn("Body after rule.", [p.text for p in passages])


class SegmentationTest(unittest.TestCase):
    def setUp(self):
        self.doc = make_document("report", DOC, "report.md")
        self.passages = segment_document(self.doc)

    def test_passages_have_exact_source_spans(self):
        for passage in self.passages:
            raw = self.doc.text[passage.char_start:passage.char_end]
            self.assertIn(passage.text.split()[0], raw)

    def test_passage_text_line_and_heading(self):
        texts = [p.text for p in self.passages]
        self.assertEqual(texts, ["Sales grew 10%.", "The margin was 5%.", "The fleet has 20 trucks."])
        self.assertEqual(self.passages[0].heading, "Sales")
        self.assertEqual(self.passages[0].line, 10)
        self.assertEqual(self.passages[1].previous_text, "Sales grew 10%.")

    def test_document_title_and_hash(self):
        self.assertEqual(self.doc.title, "Synthetic report")
        self.assertEqual(len(self.doc.sha256), 64)
        self.assertEqual(self.doc.date, "2024-01-31")

    def test_title_falls_back_to_first_heading_then_id(self):
        self.assertEqual(make_document("x", "# Heading\n\nText.").title, "Heading")
        self.assertEqual(make_document("x", "Text.").title, "x")


class LoadingTest(unittest.TestCase):
    def test_loads_supported_formats_and_skips_hidden_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text(DOC, encoding="utf-8")
            (root / "b.txt").write_text("Plain text with data.", encoding="utf-8")
            (root / "c.json").write_text(json.dumps([{"id": "c1", "text": "One."}, {"text": "Two."}]), encoding="utf-8")
            (root / "d.jsonl").write_text('{"id": "d1", "text": "Three.", "date": "2024-02-01"}\n', encoding="utf-8")
            (root / ".hidden.md").write_text("Must not be loaded.", encoding="utf-8")
            (root / "image.png").write_bytes(b"\x89PNG")
            docs = load_documents(root)
        self.assertEqual([d.doc_id for d in docs], ["a", "b", "c1", "c#1", "d1"])
        self.assertEqual(docs[-1].date, "2024-02-01")

    def test_single_file_corpus(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "single.md"
            path.write_text(DOC, encoding="utf-8")
            corpus = load_corpus(path)
        self.assertEqual(len(corpus.documents), 1)
        self.assertEqual(len(corpus.passages), 3)

    def test_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(CorpusError, "no supported documents"):
                load_documents(root)
            with self.assertRaisesRegex(CorpusError, "not found"):
                load_documents(root / "missing")
            (root / "bad.json").write_text("{oops", encoding="utf-8")
            with self.assertRaisesRegex(CorpusError, "invalid JSON"):
                load_documents(root)
            (root / "bad.json").write_text('[{"id": "x"}]', encoding="utf-8")
            with self.assertRaisesRegex(CorpusError, "string 'text'"):
                load_documents(root)
            (root / "bad.json").unlink()
            (root / "latin1.txt").write_bytes("café".encode("latin-1"))
            with self.assertRaisesRegex(CorpusError, "UTF-8"):
                load_documents(root)

    def test_duplicate_ids_and_empty_corpus_are_rejected(self):
        with self.assertRaisesRegex(CorpusError, "duplicate"):
            build_corpus([make_document("a", "x."), make_document("a", "y.")])
        with self.assertRaisesRegex(CorpusError, "empty"):
            build_corpus([])

    def test_fingerprint_changes_with_content(self):
        first = build_corpus([make_document("a", "One.")]).fingerprint
        second = build_corpus([make_document("a", "Two.")]).fingerprint
        self.assertNotEqual(first, second)
        self.assertEqual(first, build_corpus([make_document("a", "One.")]).fingerprint)


class ClaimExtractionTest(unittest.TestCase):
    def test_extracts_claims_with_spans_and_skips_non_checkable(self):
        answer = (
            "## Resumen\n\nLas ventas crecieron 10% en 2023. ¿Algo más?\n"
            "- La flota es de 20 camiones; el margen fue de 5%.\nEspero que te sirva.\nOk."
        )
        extraction = extract_claims(answer)
        self.assertEqual(
            [c.text for c in extraction.claims],
            ["Las ventas crecieron 10% en 2023.", "La flota es de 20 camiones", "el margen fue de 5%."],
        )
        self.assertEqual([s.reason for s in extraction.skipped], ["heading", "question", "conversational", "no_factual_content"])
        first = extraction.claims[0]
        self.assertEqual(answer[first.char_start:first.char_end], first.text)

    def test_contrastive_clauses_become_separate_claims(self):
        extraction = extract_claims("Las ventas crecieron 10%, pero los costos subieron 4%.")
        self.assertEqual(len(extraction.claims), 2)

    def test_leading_connectors_are_removed(self):
        extraction = extract_claims("En resumen, las ventas crecieron 10%.")
        self.assertEqual(extraction.claims[0].text, "las ventas crecieron 10%.")

    def test_invalid_answers(self):
        with self.assertRaises(AnswerError):
            extract_claims("   ")
        with self.assertRaises(AnswerError):
            extract_claims("x" * 200_001)
        with self.assertRaises(AnswerError):
            claims_from_texts(["", "  "])

    def test_pre_extracted_claims_are_kept_verbatim(self):
        extraction = claims_from_texts(["One two three.", " Four five. "])
        self.assertEqual([c.claim_id for c in extraction.claims], ["C1", "C2"])
        self.assertEqual(extraction.claims[1].text, "Four five.")


class RetrievalTest(unittest.TestCase):
    def setUp(self):
        corpus = build_corpus(
            [
                make_document("a", "The fleet has 20 trucks. The margin was 5%."),
                make_document("b", "Sales grew 10%. The trucks are new."),
            ]
        )
        self.index = Bm25Index(corpus.passages)

    def test_ranks_most_relevant_passage_first(self):
        hits = self.index.search(content_stems("fleet of trucks"), k=3)
        self.assertEqual(hits[0][0].text, "The fleet has 20 trucks.")
        self.assertGreater(hits[0][1], hits[1][1])

    def test_statistics(self):
        truck = content_stems("trucks")[0]
        self.assertEqual(self.index.document_frequency(truck), 2)
        self.assertEqual(self.index.document_frequency("zzz"), 0)
        self.assertGreater(self.index.idf("zzz"), self.index.idf(truck))

    def test_no_hits_and_k_limit(self):
        self.assertEqual(self.index.search(["zzz"], k=5), ())
        self.assertEqual(len(self.index.search(content_stems("trucks sales margin"), k=2)), 2)


if __name__ == "__main__":
    unittest.main()
