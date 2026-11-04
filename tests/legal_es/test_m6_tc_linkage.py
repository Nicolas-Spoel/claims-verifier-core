"""M6-C1: synthetic TC wire only. No automated search or network in tests."""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from keepmehonest_legal_es.evidence import Origin
from keepmehonest_legal_es.m6_tc_linkage import (
    CONTRACT, TCLinkageError, SEARCH_PAGE, main, plan, resolve,
)
from keepmehonest_legal_es.sources.tc import TCClient
from keepmehonest_legal_es.sources.transport import FetchError, Retrieved, SecureHTTP

ECLI = "ECLI:ES:TC:2024:1"
HJ_ID = 30062
SECTION_TEXT = "Fundamento jurídico primero sobre la tutela judicial efectiva, en un supuesto ficticio y solo para pruebas."


def tc_bytes(*, number=1, fj=1):
    return json.dumps({
        "ID": HJ_ID,
        "TIPO_RESOLUCION": "SENTENCIA",
        "NUMERO_RESOLUCION": number,
        "ANNO_RESOLUCION": 2024,
        "FECHA_REGISTRO": "2024-01-15T00:00:00",
        "RESOLUCIONES_FUNDAMENTOS": [{"NUMERO": fj, "TEXTO": SECTION_TEXT}],
        "RESOLUCIONES_DICTAMEN": [{"TITULO": "FALLO", "TEXTO": "El Tribunal Constitucional decide estimar el recurso de manera exclusivamente ficticia para estas pruebas."}],
    }, ensure_ascii=False).encode("utf-8")


class FakeWire:
    def __init__(self, data=None):
        self.data = tc_bytes() if data is None else data
        self.calls = []

    def get(self, url, *, accept):
        SecureHTTP.check_url(url)
        self.calls.append((url, accept))
        return Retrieved(url, self.data, "application/json", sha256(self.data).hexdigest(),
                         "2026-11-04T10:00:00+00:00")


def case(**kwargs):
    return dict(ecli=ECLI, hj_id=HJ_ID, section="FJ1", topic="constitucional", **kwargs)


class TCPlanTests(unittest.TestCase):
    def test_plan_offline_explicit_and_honest(self):
        got = plan(**case())
        self.assertEqual(got["contract"], CONTRACT)
        self.assertEqual(got["mode"], "OFFLINE_MANUAL_TC_SELECTION")
        self.assertEqual(got["search_page"], SEARCH_PAGE)
        self.assertFalse(got["network_used"])
        self.assertFalse(got["user_supplied_pair_verified"])
        self.assertFalse(got["coverage"]["search_executed_by_tool"])
        self.assertFalse(got["coverage"]["exhaustive"])
        self.assertFalse(got["legal_support_assessed"])
        self.assertFalse(got["rights_cleared"])
        self.assertFalse(got["source_text_in_report"])

    def test_plan_never_calls_network(self):
        with patch("keepmehonest_legal_es.m6_tc_linkage.TCClient", side_effect=AssertionError("unexpected network")):
            self.assertEqual(plan(**case())["mode"], "OFFLINE_MANUAL_TC_SELECTION")

    def test_invalid_ecli(self):
        for ecli in ("ECLI:ES:TS:2024:1", "ECLI:ES:TC:2024:1A", "ECLI:ES:TC:2024:0", "ECLI:ES:TC:2100:1", "ECLI:ES:TC:24:1", "ECLI:ES:TC:2024:1;open"):
            with self.subTest(ecli=ecli), self.assertRaises(TCLinkageError):
                plan(**{**case(), "ecli": ecli})

    def test_invalid_hj_id(self):
        for value in (-1, 0, True, "30062", 1_000_000_000):
            with self.subTest(value=value), self.assertRaises(TCLinkageError):
                plan(**{**case(), "hj_id": value})

    def test_invalid_section(self):
        for section in ("fj1", "FJ0", "FJ100", "FJ1;rm", "ALL", "FJ-1", ""):
            with self.subTest(section=section), self.assertRaises(TCLinkageError):
                plan(**{**case(), "section": section})

    def test_explicit_fallo_allowed(self):
        self.assertEqual(plan(**{**case(), "section": "FALLO"})["section_id"], "FALLO")

    def test_topics_are_fixed_public_categories(self):
        for topic in ("", "nombre_persona", "procedimiento_123", "constitucional?dni=11111111"):
            with self.subTest(topic=topic), self.assertRaises(TCLinkageError):
                plan(**{**case(), "topic": topic})


class TCResolveTests(unittest.TestCase):
    def test_resolve_one_official_fj_provenance(self):
        wire = FakeWire()
        got, text = resolve(**case(), client=TCClient(wire))
        self.assertEqual(len(wire.calls), 1)
        self.assertEqual(wire.calls[0][1], "application/json")
        self.assertEqual(got["mode"], "TC_SECTION_RETRIEVED_DOCUMENTARY_ONLY")
        self.assertTrue(got["user_supplied_pair_verified"])
        self.assertEqual(got["decision_date"], "2024-01-15")
        self.assertEqual(got["raw_response_sha256"], sha256(wire.data).hexdigest())
        self.assertEqual(got["section_text_sha256"], sha256(text.encode()).hexdigest())
        self.assertNotIn(text, json.dumps(got, ensure_ascii=False))
        self.assertFalse(got["coverage"]["tc_general_search_automated"])
        self.assertEqual(got["coverage"]["manual_search_results_total"], "UNVERIFIABLE")
        self.assertFalse(got["legal_accuracy_measured"])
        self.assertFalse(got["rights_cleared"])

    def test_fallo_isolated(self):
        got, txt = resolve(**{**case(), "section": "FALLO"}, client=TCClient(FakeWire()))
        self.assertIn("estimar", txt)
        self.assertNotIn("Fundamento", txt)
        self.assertEqual(got["section_id"], "FALLO")

    def test_wrong_ecli_fails_from_official_identity(self):
        with self.assertRaisesRegex(FetchError, "identity"):
            resolve(**{**case(), "ecli": "ECLI:ES:TC:2024:2"}, client=TCClient(FakeWire()))

    def test_wrong_hj_id_fails(self):
        with self.assertRaisesRegex(FetchError, "identity"):
            resolve(**{**case(), "hj_id": 30063}, client=TCClient(FakeWire()))

    def test_missing_section_fails(self):
        with self.assertRaises(FetchError):
            resolve(**{**case(), "section": "FJ2"}, client=TCClient(FakeWire()))

    def test_duplicate_json_identity_fails(self):
        data = tc_bytes().replace(b'"ID": 30062', b'"ID": 30062, "ID": 30062')
        with self.assertRaises(FetchError):
            resolve(**case(), client=TCClient(FakeWire(data)))

    def test_spoofed_m2_result_fails(self):
        good = TCClient(FakeWire()).get_section(ECLI, HJ_ID, "FJ1")
        class Spoof:
            def get_section(self, *args):
                return replace(good, raw_sha256="x" * 64)
        with self.assertRaisesRegex(TCLinkageError, "provenance"):
            resolve(**case(), client=Spoof())

    def test_fake_section_url_rejected(self):
        good = TCClient(FakeWire()).get_section(ECLI, HJ_ID, "FJ1")
        class Spoof:
            def get_section(self, *args):
                return replace(good, api_url="https://example.com/evil")
        with self.assertRaises(FetchError):
            resolve(**case(), client=Spoof())

    def test_local_user_content_not_in_network_url(self):
        wire = FakeWire()
        resolve(**{**case(), "topic": "proteccion_datos"}, client=TCClient(wire))
        self.assertEqual(wire.calls, [("https://hj.tribunalconstitucional.es/HJ/Resolucion/Api/json/30062", "application/json")])


class TCCommandTests(unittest.TestCase):
    def test_plan_cli_has_no_side_effects(self):
        rc = main(["plan", "--ecli", ECLI, "--hj-id", str(HJ_ID), "--section", "FJ1", "--topic", "constitucional"])
        self.assertEqual(rc, 0)

    def test_resolve_requires_explicit_network_optin(self):
        rc = main(["resolve", "--ecli", ECLI, "--hj-id", str(HJ_ID), "--section", "FJ1", "--topic", "constitucional"])
        self.assertEqual(rc, 2)

    def test_private_output_rejects_repository_path(self):
        with tempfile.TemporaryDirectory() as d:
            # Using the M6-B validated helper; never stage protected text.
            p = Path.cwd()/"some-private-source.json"
            from keepmehonest_legal_es.m6_tc_linkage import _private_output
            with self.assertRaises(Exception):
                _private_output(p, {"text": "secret"})
            self.assertFalse(p.exists())

    def test_resolve_cli_writes_separate_report_outside_repository(self):
        with tempfile.TemporaryDirectory() as d:
            public = Path(d)/"metadata.json"
            private = Path(d)/"private.json"
            args = ["resolve", "--ecli", ECLI, "--hj-id", str(HJ_ID), "--section", "FJ1",
                    "--topic", "constitucional", "--allow-official-network", "--output", str(public),
                    "--private-evidence-output", str(private)]
            with patch("keepmehonest_legal_es.m6_tc_linkage.TCClient", return_value=TCClient(FakeWire())):
                self.assertEqual(main(args), 0)
            pub = json.loads(public.read_text())
            priv = json.loads(private.read_text())
            self.assertNotIn("text", pub)
            self.assertEqual(priv["text_sha256"], pub["section_text_sha256"])
            self.assertIn(SECTION_TEXT, priv["text"])
            self.assertEqual(public.stat().st_mode & 0o777, 0o600)
            self.assertEqual(private.stat().st_mode & 0o777, 0o600)

    def test_no_writes_on_same_public_private_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/"same.json"
            args = ["resolve", "--ecli", ECLI, "--hj-id", str(HJ_ID), "--section", "FJ1",
                    "--topic", "constitucional", "--allow-official-network", "--output", str(p),
                    "--private-evidence-output", str(p)]
            with patch("keepmehonest_legal_es.m6_tc_linkage.TCClient", side_effect=AssertionError("network must not execute")):
                self.assertEqual(main(args), 2)
            self.assertFalse(p.exists())


if __name__ == "__main__":
    unittest.main()
