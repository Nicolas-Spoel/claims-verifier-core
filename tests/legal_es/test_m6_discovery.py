"""M6-A: constrained discovery without case data, no legal-support overclaim."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keepmehonest_legal_es.m6_discovery import (
    CONTRACT, BOESearchTransport, DiscoveryError, TOPICS,
    _write_new, build_url, inventory, main, parse_listing, search,
)
from keepmehonest_legal_es.sources.transport import FetchError, Retrieved, SecureHTTP, SourceUnavailable

CORPUS = Path(__file__).resolve().parents[2] / "evals/legal_es/m5/pilot_candidates.json"


def response(*, topic="constitucional", limit=5, offset=0, records=None, code="200", data_override=None):
    if records is None:
        records = [{
            "identificador": "BOE-A-1978-31229",
            "titulo": "Constitución Española",
            "fecha_publicacion": "19781229",
            "fecha_actualizacion": "20260101T120000Z",
            "url_html_consolidada": "https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229",
        }]
    body = json.dumps({"status": {"code": code, "text": "ok"},
                       "data": data_override if data_override is not None else records},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return Retrieved(build_url(topic, limit, offset), body, "application/json",
                     sha256(body).hexdigest(), "2026-11-04T10:00:00+00:00")


class StubTransport:
    def __init__(self, result=None):
        self.result = result or response()
        self.calls = []

    def get(self, url, *, accept):
        self.calls.append((url, accept))
        return self.result


class M6URLTests(unittest.TestCase):
    def test_only_fixed_public_legal_topics(self):
        self.assertEqual(len(TOPICS), 5)
        with self.assertRaises(DiscoveryError):
            build_url("Juan Pérez, DNI 12345678Z")
        with self.assertRaises(DiscoveryError):
            build_url("La trabajadora fue despedida el lunes")

    def test_allowlisted_boe_request_passes(self):
        url = build_url("constitucional")
        BOESearchTransport.check_url(url)
        self.assertIn("www.boe.es", url)
        self.assertNotIn("client", url)

    def test_existing_m2_transport_rejects_search(self):
        with self.assertRaises(FetchError):
            SecureHTTP.check_url(build_url("constitucional"))

    def test_reject_external_hosts_and_path(self):
        valid = build_url("laboral")
        for changed in [valid.replace("www.boe.es", "evil.example"),
                        valid.replace("https", "http", 1),
                        valid.replace("/legislacion-consolidada?", "/legislacion-consolidada/id/BOE-A-1978-31229?"),
                        valid + "#frag", valid.replace("www.boe.es", "www.boe.es@evil.example")]:
            with self.subTest(changed=changed), self.assertRaises(DiscoveryError):
                BOESearchTransport.check_url(changed)

    def test_reject_repeated_parameters_and_extra(self):
        url = build_url("constitucional")
        for changed in [url + "&limit=10", url + "&foo=bar", url.replace("&offset=0", "")]:
            with self.subTest(changed=changed), self.assertRaises(DiscoveryError):
                BOESearchTransport.check_url(changed)

    def test_reject_noncanonical_encodings(self):
        url = build_url("constitucional")
        with self.assertRaises(DiscoveryError):
            BOESearchTransport.check_url(url.replace("&offset=0", "&offset=00"))

    def test_pagination_is_bounded(self):
        for limit, offset in [(0, 0), (21, 0), (5, -5), (5, 101), (5, 1), (True, 0), (5, False)]:
            with self.subTest(limit=limit, offset=offset), self.assertRaises(DiscoveryError):
                build_url("constitucional", limit=limit, offset=offset)
        BOESearchTransport.check_url(build_url("constitucional", limit=5, offset=10))


class M6ParseTests(unittest.TestCase):
    def test_one_public_candidate_not_a_legal_verdict(self):
        result = parse_listing(response(), topic="constitucional", limit=5, offset=0)
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["contract"], CONTRACT)
        self.assertFalse(result["coverage"]["exhaustive"])
        self.assertEqual(result["coverage"]["result_total"], "UNKNOWN")
        self.assertFalse(result["case_text_transmitted"])
        self.assertFalse(result["legal_support_assessed"])
        self.assertFalse(result["legal_accuracy_measured"])
        self.assertEqual(result["candidates"][0]["identifier"], "BOE-A-1978-31229")
        self.assertFalse(result["candidates"][0]["section_retrieved"])

    def test_empty_result_does_not_imply_no_source(self):
        result = parse_listing(response(data_override={}), topic="constitucional", limit=5, offset=0)
        self.assertEqual(result["candidate_count"], 0)
        self.assertTrue(result["coverage"]["not_found_is_not_no_authority"])
        self.assertFalse(result["coverage"]["exhaustive"])

    def test_full_page_is_explicitly_partial(self):
        rows=[]
        for n in range(5):
            rows.append({"identificador":f"BOE-A-2001-{100+n}",
                         "titulo":f"Norma {n}", "fecha_publicacion":"20010101",
                         "fecha_actualizacion":"20260101T120000Z"})
        result=parse_listing(response(records=rows),topic="constitucional",limit=5,offset=0)
        self.assertTrue(result["coverage"]["more_pages_possible"])
        self.assertFalse(result["coverage"]["exhaustive"])

    def test_invalid_status_never_means_no_authority(self):
        with self.assertRaises(SourceUnavailable):
            parse_listing(response(code="500"),topic="constitucional",limit=5,offset=0)

    def test_wrong_response_url_hash_or_format_rejected(self):
        resp=response()
        modified=[Retrieved(resp.url+"#x",resp.body,resp.content_type,resp.sha256,resp.retrieved_at),
                  Retrieved(resp.url,resp.body,resp.content_type,"0"*64,resp.retrieved_at),
                  Retrieved(resp.url,resp.body,"text/html",resp.sha256,resp.retrieved_at)]
        for item in modified:
            with self.subTest(item=item),self.assertRaises(DiscoveryError):
                parse_listing(item,topic="constitucional",limit=5,offset=0)

    def test_wrong_id_or_url_rejected(self):
        cases=[{"identificador":"BOE-A-1978-31229" ,"titulo":"Norma", "fecha_publicacion":"19781229", "fecha_actualizacion":"20260101T120000Z", "url_html_consolidada":"https://evil.example/fake"},
               {"identificador":"ECLI:ES:TC:2024:1","titulo":"TC", "fecha_publicacion":"19781229", "fecha_actualizacion":"20260101T120000Z"}]
        for case in cases:
            with self.assertRaises(DiscoveryError):
                parse_listing(response(records=[case]),topic="constitucional",limit=5,offset=0)

    def test_malformed_or_impossible_dates_rejected(self):
        for field, value in [("fecha_publicacion", "20260230"),("fecha_publicacion","2026-02-01"),("fecha_actualizacion","this morning")]:
            row = json.loads(response().body)["data"][0]
            row[field] = value
            with self.subTest(field=field),self.assertRaises(DiscoveryError):
                parse_listing(response(records=[row]),topic="constitucional",limit=5,offset=0)

    def test_duplicate_ids_rejected(self):
        row=json.loads(response().body)["data"][0]
        with self.assertRaises(DiscoveryError):
            parse_listing(response(records=[row,row]),topic="constitucional",limit=5,offset=0)

    def test_more_than_limit_refused(self):
        row=json.loads(response().body)["data"][0]
        with self.assertRaises(DiscoveryError):
            parse_listing(response(records=[row]*6),topic="constitucional",limit=5,offset=0)

    def test_duplicate_json_keys_rejected(self):
        body=b'{"status":{"code":"200","code":"500"},"data":[]}'
        v=Retrieved(build_url("constitucional"),body,"application/json",sha256(body).hexdigest(),"t")
        with self.assertRaises(DiscoveryError):
            parse_listing(v,topic="constitucional",limit=5,offset=0)

    def test_does_not_confuse_tc_discovery_with_retrieval(self):
        result=parse_listing(response(),topic="constitucional",limit=5,offset=0)
        self.assertEqual(result["coverage"]["tc_general_discovery"], "NOT_PERFORMED_NO_APPROVED_SEARCH_CONTRACT")
        self.assertEqual(result["coverage"]["ordinary_courts"],"NOT_SEARCHED_ACCESS_UNAUTHORIZED")

    def test_mocked_transport_receives_only_public_taxonomy(self):
        fake=StubTransport()
        result=search("constitucional",transport=fake)
        self.assertEqual(result["candidate_count"],1)
        self.assertEqual(fake.calls,[(build_url("constitucional"),"application/json")])


class M6CoverageTests(unittest.TestCase):
    def test_offline_inventory_is_not_coverage_of_all_law(self):
        corpus=json.loads(CORPUS.read_text(encoding="utf-8"))
        report=inventory(corpus)
        self.assertEqual(report["pilot_cases"],36)
        self.assertEqual(report["known_section_clusters"],13)
        self.assertEqual(report["expert_gold_cases"],0)
        self.assertEqual(report["source_universe_completeness"],"UNVERIFIABLE")
        self.assertEqual(report["tc_general_discovery"],"NOT_IMPLEMENTED")

    def test_invalid_annotated_corpus_not_silently_accepted(self):
        corpus=json.loads(CORPUS.read_text(encoding="utf-8"))
        corpus["cases"][0]["expert_label"]="DIRECT_SUPPORT"
        with self.assertRaises(Exception):
            inventory(corpus)

    def test_cli_plan_offline(self):
        with patch("keepmehonest_legal_es.m6_discovery.BOESearchTransport.get",side_effect=AssertionError("network")):
            self.assertEqual(main(["plan","--candidates",str(CORPUS)]),0)

    def test_cli_search_requires_opt_in(self):
        with patch("keepmehonest_legal_es.m6_discovery.BOESearchTransport.get",side_effect=AssertionError("network")):
            self.assertEqual(main(["search","--topic","constitucional"]),2)

    def test_public_report_new_file_only(self):
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/"search.json"
            _write_new(dest,{"contract":CONTRACT,"case_text_transmitted":False})
            self.assertTrue(dest.exists())
            with self.assertRaises(DiscoveryError):
                _write_new(dest,{"something":"else"})


if __name__ == "__main__":
    unittest.main()
