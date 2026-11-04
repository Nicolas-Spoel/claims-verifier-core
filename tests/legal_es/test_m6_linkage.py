"""M6-B: explicit BOE ID/article/as-of linkage; synthetic official-wire fixtures only."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keepmehonest_legal_es.m6_discovery import build_url, parse_listing
from keepmehonest_legal_es.m6_linkage import (
    CONTRACT, LinkageError, _private_output, load_discovery_report, main,
    plan, resolve, select,
)
from keepmehonest_legal_es.sources.boe import BOEClient
from keepmehonest_legal_es.sources.transport import FetchError, Retrieved, SecureHTTP, SourceUnavailable

BOE = "BOE-A-1978-31229"
AS_OF = "2024-01-15"


def listing():
    body = json.dumps({
        "status": {"code": "200"},
        "data": [{
            "identificador": BOE,
            "titulo": "Constitución Española.",
            "fecha_publicacion": "19781229",
            "fecha_actualizacion": "20261104T091715Z",
            "url_html_consolidada": f"https://www.boe.es/buscar/act.php?id={BOE}",
        }],
    }, ensure_ascii=False).encode("utf-8")
    r = Retrieved(build_url("constitucional"), body, "application/json", sha256(body).hexdigest(),
                  "2026-11-04T10:30:26+00:00")
    return parse_listing(r, topic="constitucional", limit=5, offset=0)


class FakeHTTP:
    index = (b'<?xml version="1.0"?><response><status><code>200</code></status><data>'
             b'<bloque><id>a24</id><titulo>Art\xc3\xadculo 24</titulo></bloque>'
             b'</data></response>')
    block = (b'<?xml version="1.0"?><response><status><code>200</code></status><data>'
             b'<bloque id="a24" tipo="precepto">'
             b'<version id_norma="BOE-A-1978-31229" fecha_publicacion="19781229" fecha_vigencia="19781229">'
             b'<p>Art\xc3\xadculo 24.</p><p>Texto sint\xc3\xa9tico exclusivamente para pruebas.</p></version>'
             b'</bloque></data></response>')

    def __init__(self, *, index=None, block=None):
        self.calls = []
        self._index = index if index is not None else self.index
        self._block = block if block is not None else self.block

    def get(self, url, *, accept):
        SecureHTTP.check_url(url)
        self.calls.append((url, accept))
        data = self._index if url.endswith("/indice") else self._block
        return Retrieved(url, data, "application/xml", sha256(data).hexdigest(),
                         "2026-11-04T10:30:26+00:00")


class M6BSelectionTests(unittest.TestCase):
    def setUp(self):
        self.r = listing()

    def test_offline_plan_explicit_no_legal_merits(self):
        p = plan(self.r, identifier=BOE, article=24, as_of=AS_OF, discovery_file_sha256="a"*64)
        self.assertEqual(p["contract"], CONTRACT)
        self.assertEqual(p["mode"], "OFFLINE_EXPLICIT_SECTION_SELECTION")
        self.assertFalse(p["network_used"])
        self.assertFalse(p["section_retrieved"])
        self.assertFalse(p["legal_support_assessed"])
        self.assertEqual(p["article_requested"], 24)

    def test_discovered_identifier_is_required(self):
        with self.assertRaisesRegex(LinkageError, "not present"):
            select(self.r, identifier="BOE-A-2015-10565", article=24, as_of=AS_OF)

    def test_non_boe_identifier_refused(self):
        with self.assertRaises(LinkageError):
            select(self.r, identifier="ECLI:ES:TC:2024:1", article=1, as_of=AS_OF)

    def test_article_never_inferred_and_requires_integer(self):
        for x in (True, "24", 0, 10000, None):
            with self.subTest(article=x), self.assertRaises(LinkageError):
                select(self.r, identifier=BOE, article=x, as_of=AS_OF)

    def test_historical_publication_precheck(self):
        with self.assertRaisesRegex(LinkageError, "predates"):
            select(self.r, identifier=BOE, article=24, as_of="1978-12-28")

    def test_invalid_dates_and_future_rejected(self):
        for date in ("2024-02-30", "20240115", "2030-01-01", "1978-13-01"):
            with self.subTest(date=date), self.assertRaises(LinkageError):
                select(self.r, identifier=BOE, article=24, as_of=date)

    def test_malformed_reports_not_accepted(self):
        mods = [
            ("contract", "wrong"), ("mode", "VERIFIED_GOLD"),
            ("request_url", "https://attacker.example"), ("topic", "custom free text"),
            ("candidate_count", 3), ("raw_sha256", "no-hash"),
            ("case_text_transmitted", True), ("rights_cleared", True),
            ("legal_support_assessed", True), ("legal_accuracy_measured", True),
            ("retrieved_at", "yesterday"),
        ]
        for k, v in mods:
            with self.subTest(field=k), self.assertRaises((LinkageError, ValueError)):
                select({**self.r, k: v}, identifier=BOE, article=24, as_of=AS_OF)

    def test_reject_overclaimed_coverage(self):
        r = {**self.r, "coverage": {**self.r["coverage"], "exhaustive": True}}
        with self.assertRaises(LinkageError):
            select(r, identifier=BOE, article=24, as_of=AS_OF)

    def test_reject_bad_candidate_url_and_fake_status(self):
        for changes in ({"official_url": "https://evil.test/a"},
                        {"section_retrieved": True},
                        {"candidate_status": "LEGAL_SUPPORT_CONFIRMED"},
                        {"published_on": "garbage"}):
            r = {**self.r, "candidates": [{**self.r["candidates"][0], **changes}]}
            with self.subTest(changes=changes), self.assertRaises(LinkageError):
                select(r, identifier=BOE, article=24, as_of=AS_OF)

    def test_duplicates_refused_even_if_requested_first(self):
        r = {**self.r, "candidates": self.r["candidates"] * 2, "candidate_count": 2}
        with self.assertRaises(LinkageError):
            select(r, identifier=BOE, article=24, as_of=AS_OF)

    def test_no_candidates_never_infers_absence(self):
        r = {**self.r, "candidates": [], "candidate_count": 0}
        with self.assertRaisesRegex(LinkageError, "not present"):
            select(r, identifier=BOE, article=24, as_of=AS_OF)


class M6BRetrievalTests(unittest.TestCase):
    def test_real_m2_parser_on_synthetic_wire_two_requests(self):
        http = FakeHTTP()
        report, text = resolve(listing(), identifier=BOE, article=24, as_of=AS_OF,
                               discovery_file_sha256="1"*64, client=BOEClient(http))
        self.assertEqual(len(http.calls), 2)
        self.assertEqual(report["section_id"], "a24")
        self.assertEqual(report["selected_version_effective_from"], "1978-12-29")
        self.assertEqual(report["selected_version_published_on"], "1978-12-29")
        self.assertEqual(report["section_text_sha256"], sha256(text.encode("utf-8")).hexdigest())
        self.assertNotIn(text, json.dumps(report, ensure_ascii=False))
        self.assertFalse(report["section_text_in_report"])
        self.assertFalse(report["index_response_sealed"])
        self.assertFalse(report["legal_support_assessed"])
        self.assertEqual(report["legal_applicability"], "NOT_ASSESSED")
        self.assertEqual(report["temporal_status"], "CHECK_REQUIRED")
        self.assertFalse(report["rights_cleared"])

    def test_expired_block_fail_closed(self):
        block = FakeHTTP.block.replace(b'<bloque id="a24"', b'<bloque fecha_caducidad="20000101" id="a24"')
        with self.assertRaisesRegex(FetchError, "expired"):
            resolve(listing(), identifier=BOE, article=24, as_of=AS_OF,
                    discovery_file_sha256="1"*64, client=BOEClient(FakeHTTP(block=block)))

    def test_wrong_article_fail_closed(self):
        with self.assertRaisesRegex(FetchError, "not uniquely"):
            resolve(listing(), identifier=BOE, article=25, as_of=AS_OF,
                    discovery_file_sha256="1"*64, client=BOEClient(FakeHTTP()))

    def test_malformed_or_wrong_version_fail_closed(self):
        block = FakeHTTP.block.replace(b'fecha_vigencia="19781229"', b'fecha_vigencia="20300101"')
        with self.assertRaises(FetchError):
            resolve(listing(), identifier=BOE, article=24, as_of=AS_OF,
                    discovery_file_sha256="1"*64, client=BOEClient(FakeHTTP(block=block)))

    def test_wrong_identifier_from_client_fail_closed(self):
        real = BOEClient(FakeHTTP()).get_article(BOE, 24, AS_OF)
        class BadClient:
            def get_article(self, *args):
                return replace(real, requested_as_of="2026-11-04")
        with self.assertRaisesRegex(LinkageError, "mismatched"):
            resolve(listing(), identifier=BOE, article=24, as_of=AS_OF,
                    discovery_file_sha256="1"*64, client=BadClient())

    def test_raw_block_hash_not_claimed_index_seal(self):
        out, _ = resolve(listing(), identifier=BOE, article=24, as_of=AS_OF,
                         discovery_file_sha256="1"*64, client=BOEClient(FakeHTTP()))
        self.assertTrue(len(out["block_raw_response_sha256"]) == 64)
        self.assertIs(out["index_response_sealed"], False)


class M6BFileAndCLITests(unittest.TestCase):
    def test_report_file_fingerprint_and_duplicate_key_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"report.json"
            b = json.dumps(listing(), ensure_ascii=False).encode()
            path.write_bytes(b)
            r, digest = load_discovery_report(path)
            self.assertEqual(r["contract"], listing()["contract"])
            self.assertEqual(digest, sha256(b).hexdigest())
            path.write_text('{"a":1,"a":2}', encoding="utf-8")
            with self.assertRaisesRegex(LinkageError, "duplicate"):
                load_discovery_report(path)

    def test_report_symlink_and_oversized_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base/"payload.json").write_text("{}", encoding="utf-8")
            (base/"link.json").symlink_to(base/"payload.json")
            with self.assertRaises(OSError):
                load_discovery_report(base/"link.json")
            (base/"payload.json").write_bytes(b" "*256001)
            with self.assertRaises(LinkageError):
                load_discovery_report(base/"payload.json")

    def test_plan_cli_is_strictly_offline(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"listing.json"
            path.write_text(json.dumps(listing()), encoding="utf-8")
            with patch("keepmehonest_legal_es.m6_linkage.BOEClient", side_effect=AssertionError("unexpected network")):
                self.assertEqual(main(["plan", "--discovery-report", str(path),
                                       "--identifier", BOE, "--article", "24", "--as-of", AS_OF]), 0)

    def test_resolve_cli_without_opt_in_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"listing.json"
            path.write_text(json.dumps(listing()), encoding="utf-8")
            with patch("keepmehonest_legal_es.m6_linkage.BOEClient", side_effect=AssertionError("unexpected network")):
                self.assertEqual(main(["resolve", "--discovery-report", str(path),
                                       "--identifier", BOE, "--article", "24", "--as-of", AS_OF]), 2)

    def test_private_output_rejects_repo_location(self):
        with tempfile.TemporaryDirectory() as d:
            working = Path(d) / "repo"
            working.mkdir()
            old = Path.cwd()
            try:
                import os
                os.chdir(working)
                with self.assertRaises(LinkageError):
                    _private_output(working / "evidence.json", {"text": "public source"})
            finally:
                os.chdir(old)

    def test_private_output_new_file_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/"article.json"
            _private_output(path, {"text": "public synthetic fixture"})
            self.assertTrue(path.exists())
            with self.assertRaises(Exception):
                _private_output(path, {"text": "overwritten"})

    def test_resolve_cli_report_without_raw_text(self):
        with tempfile.TemporaryDirectory() as d:
            listing_path = Path(d)/"listing.json"
            listing_path.write_text(json.dumps(listing()), encoding="utf-8")
            report_path = Path(d)/"metadata.json"
            with patch("keepmehonest_legal_es.m6_linkage.BOEClient", return_value=BOEClient(FakeHTTP())):
                code = main(["resolve", "--discovery-report", str(listing_path),
                             "--identifier", BOE, "--article", "24", "--as-of", AS_OF,
                             "--allow-official-network", "--output", str(report_path)])
            self.assertEqual(code, 0)
            self.assertIn("section_text_sha256", report_path.read_text(encoding="utf-8"))
            self.assertNotIn("Texto sintético", report_path.read_text(encoding="utf-8"))

    def test_private_evidence_is_created_separately_and_not_in_report(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            src = base / "listing.json"
            src.write_text(json.dumps(listing()), encoding="utf-8")
            metadata = base / "metadata.json"
            private = base / "private-article.json"
            with patch("keepmehonest_legal_es.m6_linkage.BOEClient", return_value=BOEClient(FakeHTTP())):
                rc = main(["resolve", "--discovery-report", str(src),
                           "--identifier", BOE, "--article", "24", "--as-of", AS_OF,
                           "--allow-official-network", "--output", str(metadata),
                           "--private-evidence-output", str(private)])
            self.assertEqual(rc, 0)
            self.assertNotIn("Texto sintético", metadata.read_text(encoding="utf-8"))
            self.assertIn("Texto sintético", private.read_text(encoding="utf-8"))
            self.assertEqual(private.stat().st_mode & 0o777, 0o600)
            self.assertFalse(json.loads(private.read_text(encoding="utf-8"))["rights_cleared"])

    def test_same_private_and_public_output_refused(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "listing.json"
            src.write_text(json.dumps(listing()), encoding="utf-8")
            out = Path(d) / "same.json"
            with patch("keepmehonest_legal_es.m6_linkage.BOEClient", return_value=BOEClient(FakeHTTP())):
                rc = main(["resolve", "--discovery-report", str(src),
                           "--identifier", BOE, "--article", "24", "--as-of", AS_OF,
                           "--allow-official-network", "--output", str(out),
                           "--private-evidence-output", str(out)])
            self.assertEqual(rc, 2)
            self.assertFalse(out.exists())

    def test_no_source_text_written_when_retrieval_fails(self):
        with tempfile.TemporaryDirectory() as d:
            listing_path = Path(d)/"listing.json"
            listing_path.write_text(json.dumps(listing()), encoding="utf-8")
            private_path = Path(d)/"private.json"
            with patch("keepmehonest_legal_es.m6_linkage.BOEClient", return_value=BOEClient(FakeHTTP(index=b"garbage"))):
                rc = main(["resolve", "--discovery-report", str(listing_path),
                           "--identifier", BOE, "--article", "24", "--as-of", AS_OF,
                           "--allow-official-network", "--private-evidence-output", str(private_path)])
            self.assertEqual(rc, 2)
            self.assertFalse(private_path.exists())


if __name__ == "__main__":
    unittest.main()
