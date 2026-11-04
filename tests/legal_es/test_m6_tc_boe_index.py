"""M6-C2 offline fixtures for BOE's documented daily-sumario JSON response."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keepmehonest_legal_es.m6_tc_boe_index import (
    CONTRACT, BOESummaryTransport, TCBOEIndexError, build_url, handoff, main,
    parse_day, plan, search, _read_report, _write_outside_repo,
)
from keepmehonest_legal_es.sources.transport import Retrieved, SourceUnavailable

DAY = date(2024, 2, 20)
BOE_ID = "BOE-A-2024-3267"
TITLE = ("Sala Segunda. Sentencia 1/2024, de 15 de enero de 2024. "
         "Promovido por doña Nombre Apellido contra resoluciones judiciales.")


def make_payload(*, day="20240220", items=None, tc=True, status="200", code="T",
                 name="T.C. Sección del Tribunal Constitucional", second_edition=False, use_texto=False):
    tc_section = {
        "codigo": code, "nombre": name,
        "departamento": [{"codigo": "8600", "nombre": "TRIBUNAL CONSTITUCIONAL",
                          ("texto" if use_texto else "item"):
                              [{"identificador": BOE_ID, "titulo": TITLE}] if items is None else items}],
    }
    other_section = {"codigo": "2B", "nombre": "II. Autoridades y personal", "departamento": [
        {"nombre": "TRIBUNAL CONSTITUCIONAL", "item": [
            {"identificador": "BOE-A-2024-123", "titulo": "Convocatoria interna"}]}]}
    edition = {"numero": "45", "seccion": [other_section] + ([tc_section] if tc else [])}
    return {"status": {"code": status, "text": "ok"},
            "data": {"sumario": {"metadatos": {"publicacion": "BOE", "fecha_publicacion": day},
                                 "diario": [edition, {"numero": "46", "seccion": [other_section]}]
                                 if second_edition else [edition]}}}


def wire(payload=None, day=DAY):
    content = json.dumps(payload or make_payload(), ensure_ascii=False).encode("utf-8")
    return Retrieved(build_url(day), content, "application/json", sha256(content).hexdigest(),
                     "2026-11-04T11:25:00+00:00")


class FakeTransport:
    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def get(self, url, *, accept):
        BOESummaryTransport.check_url(url)
        self.calls.append((url, accept))
        day = url.rsplit("/", 1)[-1]
        return wire(self.responses.get(day, make_payload(day=day)),
                    day=date(int(day[:4]), int(day[4:6]), int(day[6:])))


class PlanTests(unittest.TestCase):
    def test_plan_is_offline_and_transmits_no_client_text(self):
        with patch("keepmehonest_legal_es.m6_tc_boe_index.BOESummaryTransport",
                   side_effect=AssertionError("no network in plan")):
            got = plan(start="2024-02-20", end="2024-02-20")
        self.assertEqual(got["mode"], "OFFLINE_BOUNDED_TC_BOE_PUBLICATION_PLAN")
        self.assertEqual(got["official_request_urls"], [build_url(DAY)])
        self.assertFalse(got["official_hj_search_automated"])
        self.assertFalse(got["coverage_exhaustive"])
        self.assertFalse(got["network_used"])

    def test_three_days_maximum(self):
        self.assertEqual(len(plan(start="2024-02-20", end="2024-02-22")["official_request_urls"]), 3)
        for start, end in (("2024-02-20", "2024-02-23"), ("2024-02-23", "2024-02-20")):
            with self.assertRaises(TCBOEIndexError):
                plan(start=start, end=end)

    def test_malformed_dates_fail(self):
        for invalid in ("20240220", "2024-02-30", "9999-01-01", "2024-2-20", "2024-02-20?x=2"):
            with self.subTest(invalid=invalid), self.assertRaises(TCBOEIndexError):
                plan(start=invalid, end="2024-02-20")

    def test_fixed_endpoint_does_not_accept_parameters_or_hosts(self):
        for url in (
            "http://www.boe.es/datosabiertos/api/boe/sumario/20240220",
            "https://evil.test/datosabiertos/api/boe/sumario/20240220",
            build_url(DAY) + "?client=secret", build_url(DAY) + "#x",
            "https://www.boe.es/datosabiertos/api/boe/sumario/20240230",
            "https://www.boe.es/datosabiertos/api/boe/sumario/20240220/../../etc",
            "https://www.boe.es:443/datosabiertos/api/boe/sumario/20240220",
            "https://www.boe.es@evil.test/datosabiertos/api/boe/sumario/20240220",
        ):
            with self.subTest(url=url), self.assertRaises(TCBOEIndexError):
                BOESummaryTransport.check_url(url)
        BOESummaryTransport.check_url(build_url(DAY))

    def test_client_rejects_other_accept(self):
        with self.assertRaises(TCBOEIndexError):
            BOESummaryTransport().get(build_url(DAY), accept="text/html")


class ParseTests(unittest.TestCase):
    def test_extract_only_tc_section_and_omit_personal_title(self):
        edition, found = parse_day(wire(), day=DAY)
        self.assertTrue(edition["tc_section_present"])
        self.assertEqual(edition["tc_publication_items"], 1)
        self.assertEqual(found[0]["identifier"], BOE_ID)
        self.assertEqual(found[0]["resolution_label"], "Sentencia 1/2024")
        self.assertEqual(found[0]["kind"], "SENTENCIA")
        self.assertNotIn("titulo", found[0])
        self.assertNotIn("Nombre Apellido", json.dumps(found))
        self.assertIsNone(found[0]["hj_document_id"])
        self.assertIsNone(found[0]["ecli"])
        self.assertFalse(found[0]["section_retrieved"])

    def test_single_dict_item_and_dict_sections_supported(self):
        payload = make_payload()
        first = payload["data"]["sumario"]["diario"][0]
        tc = first["seccion"][1]
        tc["departamento"] = tc["departamento"][0]
        tc["departamento"]["item"] = tc["departamento"]["item"][0]
        first["seccion"] = [tc]
        self.assertEqual(parse_day(wire(payload), day=DAY)[1][0]["identifier"], BOE_ID)

    def test_no_tc_section_does_not_yield_unrelated_department(self):
        day_report, found = parse_day(wire(make_payload(tc=False)), day=DAY)
        self.assertFalse(day_report["tc_section_present"])
        self.assertEqual(found, [])

    def test_tc_code_name_inconsistent_rejected(self):
        for kwargs in ({"code": "1"}, {"code": "TC"}, {"name": "II. Autoridades y personal"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(TCBOEIndexError):
                parse_day(wire(make_payload(**kwargs)), day=DAY)

    def test_real_tc_section_code_T_and_texto_list(self):
        # Live BOE 2024-02-20 structural observation: section code='T',
        # department keys include 'texto', not 'item' or 'epigrafe'.
        report, found = parse_day(wire(make_payload(use_texto=True)), day=DAY)
        self.assertTrue(report["tc_section_present"])
        self.assertEqual([r["identifier"] for r in found], [BOE_ID])
        self.assertNotIn("Nombre Apellido", json.dumps(found))

    def test_texto_as_single_record_or_explicit_item_wrapper(self):
        for wrapper in ("record", "item"):
            payload = make_payload(use_texto=True)
            dept = payload["data"]["sumario"]["diario"][0]["seccion"][1]["departamento"][0]
            record = dept["texto"][0]
            dept["texto"] = record if wrapper == "record" else {"item": record}
            with self.subTest(wrapper=wrapper):
                self.assertEqual(parse_day(wire(payload), day=DAY)[1][0]["identifier"], BOE_ID)

    def test_observed_real_json_shape_epigrafe_list_with_11_items(self):
        # Real BOE structural observation on 2024-02-20: texto is a dict
        # with epigrafe list; each heading has nombre and item list.
        # Titles and IDs apart from the public fixture are synthetic.
        payload = make_payload(use_texto=True)
        dept = payload["data"]["sumario"]["diario"][0]["seccion"][1]["departamento"][0]
        records = [{
            "control": "fixture", "identificador": f"BOE-A-2024-{3267 + n}",
            "titulo": TITLE if n == 0 else f"Sentencia {n + 1}/2024. Prueba sintética.",
            "url_html": "https://www.boe.es/", "url_pdf": "https://www.boe.es/",
            "url_xml": "https://www.boe.es/",
        } for n in range(11)]
        dept["texto"] = {"epigrafe": [{"nombre": "Sentencias", "item": records}]}
        edition, found = parse_day(wire(payload), day=DAY)
        self.assertTrue(edition["tc_section_present"])
        self.assertEqual(edition["tc_publication_items"], 11)
        self.assertEqual(len(found), 11)
        self.assertEqual(found[0]["identifier"], BOE_ID)
        self.assertEqual(found[0]["resolution_label"], "Sentencia 1/2024")
        self.assertNotIn("Nombre Apellido", json.dumps(found))
        self.assertTrue(all("titulo" not in row and row["ecli"] is None for row in found))

    def test_single_heading_dict_and_multiple_headings_supported(self):
        payload = make_payload(use_texto=True)
        dept = payload["data"]["sumario"]["diario"][0]["seccion"][1]["departamento"][0]
        first = {"identificador": BOE_ID, "titulo": TITLE}
        second = {"identificador": "BOE-A-2024-9999", "titulo": "Auto 2/2024. Ficticio."}
        for raw in (
            {"epigrafe": {"nombre": "Sentencias", "item": first}},
            {"epigrafe": [{"nombre": "Sentencias", "item": [first]},
                          {"nombre": "Autos", "item": [second]}]},
        ):
            with self.subTest(single=isinstance(raw["epigrafe"], dict)):
                dept["texto"] = raw
                count = 1 if isinstance(raw["epigrafe"], dict) else 2
                self.assertEqual(len(parse_day(wire(payload), day=DAY)[1]), count)

    def test_nested_epigrafe_unknown_or_ambiguous_rejected(self):
        invalid = (
            {"epigrafe": []},
            {"epigrafe": [{"nombre": "Sentencias"}]},
            {"epigrafe": [{"nombre": "Sentencias", "item": []}]},
            {"epigrafe": [{"nombre": "Sentencias", "item": "bad"}]},
            {"epigrafe": [{"nombre": "", "item": [{"identificador": BOE_ID, "titulo": TITLE}]}]},
            {"epigrafe": [{"nombre": "Sentencias", "item": [{"identificador": BOE_ID, "titulo": TITLE}], "extra": 1}]},
            {"epigrafe": [{"nombre": "Sentencias", "item": [{"identificador": BOE_ID, "titulo": TITLE}]}], "item": []},
        )
        for raw in invalid:
            payload = make_payload(use_texto=True)
            dept = payload["data"]["sumario"]["diario"][0]["seccion"][1]["departamento"][0]
            dept["texto"] = raw
            with self.subTest(raw=str(raw)[:80]), self.assertRaises(TCBOEIndexError):
                parse_day(wire(payload), day=DAY)

    def test_nested_epigrafe_duplicate_identifiers_rejected(self):
        payload = make_payload(use_texto=True)
        dept = payload["data"]["sumario"]["diario"][0]["seccion"][1]["departamento"][0]
        row = {"identificador": BOE_ID, "titulo": TITLE}
        dept["texto"] = {"epigrafe": [
            {"nombre": "Sentencias", "item": [row]},
            {"nombre": "Autos", "item": [row]},
        ]}
        with self.assertRaisesRegex(TCBOEIndexError, "duplicate"):
            parse_day(wire(payload), day=DAY)

    def test_nested_epigrafe_document_without_required_fields_rejected(self):
        payload = make_payload(use_texto=True)
        dept = payload["data"]["sumario"]["diario"][0]["seccion"][1]["departamento"][0]
        dept["texto"] = {"epigrafe": [{"nombre": "Sentencias", "item": [{"identificador": BOE_ID}]}]}
        with self.assertRaisesRegex(TCBOEIndexError, "unrecognised"):
            parse_day(wire(payload), day=DAY)

    def test_unknown_texto_shape_fails_closed_not_empty(self):
        for invalid in ("undocumented plain text", {}, [], {"texto": "unexpected"},
                        {"item": {"identificador": BOE_ID, "titulo": TITLE}, "wrong": "extra"}):
            payload = make_payload(use_texto=True)
            dept = payload["data"]["sumario"]["diario"][0]["seccion"][1]["departamento"][0]
            dept["texto"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(TCBOEIndexError):
                parse_day(wire(payload), day=DAY)

    def test_ambiguous_tc_containers_fail_closed(self):
        payload = make_payload(use_texto=True)
        dept = payload["data"]["sumario"]["diario"][0]["seccion"][1]["departamento"][0]
        dept["item"] = {"identificador": "BOE-A-2024-9999", "titulo": TITLE}
        with self.assertRaises(TCBOEIndexError):
            parse_day(wire(payload), day=DAY)

    def test_texto_duplicate_identifiers_are_rejected(self):
        duplicate = {"identificador": BOE_ID, "titulo": TITLE}
        payload = make_payload(items=[duplicate, duplicate], use_texto=True)
        with self.assertRaisesRegex(TCBOEIndexError, "duplicate"):
            parse_day(wire(payload), day=DAY)

    def test_wrong_publication_date_rejected(self):
        with self.assertRaisesRegex(TCBOEIndexError, "date identity"):
            parse_day(wire(make_payload(day="20240221")), day=DAY)

    def test_non_success_status_is_not_no_tc(self):
        with self.assertRaises(SourceUnavailable):
            parse_day(wire(make_payload(status="404")), day=DAY)

    def test_duplicate_json_key_rejected(self):
        payload = wire().body.replace(b'"code": "200"', b'"code": "200", "code": "200"')
        response = Retrieved(build_url(DAY), payload, "application/json", sha256(payload).hexdigest(), "now")
        with self.assertRaisesRegex(TCBOEIndexError, "duplicate"):
            parse_day(response, day=DAY)

    def test_wrong_hash_and_endpoint_rejected(self):
        good = wire()
        for bad in (Retrieved(good.url, good.body, good.content_type, "0"*64, good.retrieved_at),
                    Retrieved("https://evil.test/", good.body, good.content_type, good.sha256, good.retrieved_at),
                    Retrieved(good.url, good.body, "text/html", good.sha256, good.retrieved_at)):
            with self.subTest(bad=bad), self.assertRaises(TCBOEIndexError):
                parse_day(bad, day=DAY)

    def test_malformed_item_and_boe_identifier_rejected(self):
        for identifier in ("BOE-B-2024-3267", "BOE-A-2024-3267?x", "BOE-A-2024-0"):
            payload = make_payload(items=[{"identificador": identifier, "titulo": TITLE}])
            with self.subTest(identifier=identifier), self.assertRaises(TCBOEIndexError):
                parse_day(wire(payload), day=DAY)

    def test_duplicate_identifier_rejected(self):
        record = {"identificador": BOE_ID, "titulo": TITLE}
        with self.assertRaisesRegex(TCBOEIndexError, "duplicate"):
            parse_day(wire(make_payload(items=[record, record])), day=DAY)

    def test_unclassified_publication_is_retained_not_mislabeled(self):
        payload = make_payload(items=[{"identificador": BOE_ID, "titulo": "Providencia relativa a un expediente"}])
        found = parse_day(wire(payload), day=DAY)[1]
        self.assertEqual(found[0]["kind"], "TC_PUBLICATION_UNCLASSIFIED")
        self.assertIsNone(found[0]["resolution_label"])

    def test_date_identity_and_section_shape_required(self):
        payload = make_payload()
        payload["data"]["sumario"]["diario"] = "not-a-list"
        with self.assertRaises(TCBOEIndexError):
            parse_day(wire(payload), day=DAY)

    def test_allows_multiple_diarios_without_duplicate(self):
        report, found = parse_day(wire(make_payload(second_edition=True)), day=DAY)
        self.assertEqual(len(found), 1)
        self.assertEqual(report["tc_publication_items"], 1)


class SearchTests(unittest.TestCase):
    def test_one_public_get_and_report_metadata_only(self):
        client = FakeTransport()
        got = search(start="2024-02-20", end="2024-02-20", transport=client)
        self.assertEqual(client.calls, [(build_url(DAY), "application/json")])
        self.assertEqual(got["contract"], CONTRACT)
        self.assertEqual(got["candidate_count"], 1)
        self.assertFalse(got["coverage"]["coverage_exhaustive"])
        self.assertFalse(got["coverage"]["hj_general_search_automated"])
        self.assertFalse(got["legal_support_assessed"])
        self.assertFalse(got["rights_cleared"])
        self.assertNotIn("Nombre Apellido", json.dumps(got, ensure_ascii=False))
        self.assertIn("Agencia Estatal Boletín Oficial", got["source_attribution"])

    def test_two_requests_are_prevalidated_no_crawl(self):
        second = make_payload(day="20240221", items=[
            {"identificador": "BOE-A-2024-3268", "titulo": "Sala Primera. Sentencia 2/2024"}])
        client = FakeTransport({"20240221": second})
        got = search(start="2024-02-20", end="2024-02-21", transport=client)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(got["coverage"]["dates_processed"], 2)
        self.assertEqual(got["candidate_count"], 1 + 1)

    def test_four_days_rejected_before_network(self):
        client = FakeTransport()
        with self.assertRaises(TCBOEIndexError):
            search(start="2024-02-20", end="2024-02-23", transport=client)
        self.assertEqual(client.calls, [])

    def test_failure_on_second_day_is_not_partial_success(self):
        class Broken:
            def __init__(self):
                self.calls = []
            def get(self, url, *, accept):
                self.calls.append(url)
                if len(self.calls) == 2:
                    raise SourceUnavailable("simulated 404")
                return wire()
        client = Broken()
        with self.assertRaises(SourceUnavailable):
            search(start="2024-02-20", end="2024-02-21", transport=client)
        self.assertEqual(len(client.calls), 2)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.report = search(start="2024-02-20", end="2024-02-20", transport=FakeTransport())

    def test_handoff_requires_manual_ecli_and_hj_id(self):
        out = handoff(self.report, boe_id=BOE_ID, ecli="ECLI:ES:TC:2024:1", hj_id=30062,
                      section="FJ1", topic="constitucional")
        self.assertEqual(out["mode"], "OFFLINE_BOE_TO_HJ_MANUAL_SELECTION_UNVERIFIED")
        self.assertFalse(out["boe_to_hj_pair_verified"])
        self.assertFalse(out["m6c1_plan"]["network_used"])
        self.assertEqual(out["m6c1_plan"]["hj_document_id"], 30062)

    def test_no_automatic_hj_id_or_wrong_ecli(self):
        for bad in ("ECLI:ES:TC:2024:2", "ECLI:ES:TC:2025:1", "ECLI:ES:TS:2024:1"):
            with self.subTest(bad=bad), self.assertRaises(TCBOEIndexError):
                handoff(self.report, boe_id=BOE_ID, ecli=bad, hj_id=30062,
                        section="FJ1", topic="constitucional")

    def test_unclassified_tc_publication_cannot_handoff(self):
        self.report["candidates"][0]["kind"] = "TC_PUBLICATION_UNCLASSIFIED"
        with self.assertRaises(TCBOEIndexError):
            handoff(self.report, boe_id=BOE_ID, ecli="ECLI:ES:TC:2024:1", hj_id=30062,
                    section="FJ1", topic="constitucional")

    def test_nonexistent_publication_and_wrong_contract_rejected(self):
        for report, identifier in ((self.report, "BOE-A-2024-3268"), ({}, BOE_ID)):
            with self.assertRaises(TCBOEIndexError):
                handoff(report, boe_id=identifier, ecli="ECLI:ES:TC:2024:1", hj_id=30062,
                        section="FJ1", topic="constitucional")


class CommandTests(unittest.TestCase):
    def test_search_requires_explicit_network_optin(self):
        with patch("keepmehonest_legal_es.m6_tc_boe_index.BOESummaryTransport",
                   side_effect=AssertionError("unexpected network")):
            self.assertEqual(main(["search", "--from-date", "2024-02-20", "--to-date", "2024-02-20"]), 2)

    def test_plan_cli_no_network(self):
        self.assertEqual(main(["plan", "--from-date", "2024-02-20", "--to-date", "2024-02-20"]), 0)

    def test_output_is_private_and_refuses_repo(self):
        content = {"contract": CONTRACT, "item": BOE_ID}
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/"local.json"
            _write_outside_repo(target, content)
            self.assertEqual(_read_report(target), content)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(TCBOEIndexError):
                _write_outside_repo(target, content)
            p = Path.cwd()/"unsafe-report.json"
            with self.assertRaises(TCBOEIndexError):
                _write_outside_repo(p, content)
            self.assertFalse(p.exists())

    def test_handoff_cli_offline_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)/"report.json"
            p.write_text(json.dumps(search(start="2024-02-20", end="2024-02-20", transport=FakeTransport())))
            with patch("keepmehonest_legal_es.m6_tc_boe_index.BOESummaryTransport",
                       side_effect=AssertionError("unexpected network")):
                self.assertEqual(main(["handoff", "--report", str(p), "--boe-id", BOE_ID,
                                       "--ecli", "ECLI:ES:TC:2024:1", "--hj-id", "30062",
                                       "--section", "FJ1", "--topic", "constitucional"]), 0)


if __name__ == "__main__":
    unittest.main()
