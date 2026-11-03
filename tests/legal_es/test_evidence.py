import dataclasses
import unittest

from keepmehonest_legal_es import LegalEvidence, Origin, SourceKind


def tc_evidence(**kw):
    fields = dict(
        source=SourceKind.TC,
        identifier="ECLI:ES:TC:2024:1",
        section_id="FJ3",
        text="TEXTO SINTÉTICO: La solicitud fue admitida por el órgano ficticio.",
        official_url="https://hj.tribunalconstitucional.es/HJ/es/Resolucion/Show/99999",
        title="Resolución ficticia para pruebas",
        decision_date="2024-01-11",
        origin=Origin.TEST_FIXTURE,
    )
    fields.update(kw)
    return LegalEvidence(**fields)


class EvidenceTests(unittest.TestCase):
    def test_provenance_hash_is_content_sensitive(self):
        a = tc_evidence()
        b = tc_evidence(text=a.text + " Adición.")
        self.assertNotEqual(a.sha256, b.sha256)
        self.assertNotEqual(a.evidence_key, b.evidence_key)
        self.assertEqual(a.date, "2024-01-11")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            a.text = "alterado"

    def test_reject_bad_host_and_credentials(self):
        for url in [
            "https://hj.tribunalconstitucional.es.evil.test/HJ/es/Resolucion/Show/1",
            "http://hj.tribunalconstitucional.es/HJ/es/Resolucion/Show/1",
            "https://attacker@hj.tribunalconstitucional.es/HJ/es/Resolucion/Show/1",
            "https://hj.tribunalconstitucional.es:444/HJ/es/Resolucion/Show/1",
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                tc_evidence(official_url=url)

    def test_source_reference_matching(self):
        with self.assertRaises(ValueError):
            tc_evidence(identifier="BOE-A-1978-31229")
        boe = LegalEvidence(
            source=SourceKind.BOE,
            identifier="BOE-A-1978-31229",
            section_id="art24",
            title="Constitución española — texto de prueba",
            text="TEXTO SINTÉTICO, no artículo oficial: Toda persona ficticia tiene acceso a la revisión.",
            official_url="https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229",
            version_date="2024-01-01",
            origin=Origin.TEST_FIXTURE,
        )
        self.assertEqual(boe.date, "2024-01-01")

    def test_ordinary_courts_remain_closed_for_live_fetch(self):
        with self.assertRaises(ValueError):
            LegalEvidence(source=SourceKind.ORDINARY_COURTS, identifier="Roj: STS 123/2024",
                          section_id="FJ1", title="test", text="texto sintético",
                          official_url="https://www.poderjudicial.es/", origin=Origin.OFFICIAL_FETCH,
                          retrieved_at="2026-11-03T12:00:00+01:00")

    def test_require_dates_and_fetch_provenance(self):
        with self.assertRaises(ValueError):
            tc_evidence(decision_date=None)
        with self.assertRaises(ValueError):
            tc_evidence(origin=Origin.OFFICIAL_FETCH)
        with self.assertRaises(ValueError):
            tc_evidence(origin=Origin.OFFICIAL_FETCH, retrieved_at="2026-11-03T12:00:00")
        v = tc_evidence(origin=Origin.OFFICIAL_FETCH, retrieved_at="2026-11-03T12:00:00+01:00")
        self.assertEqual(v.retrieved_at, "2026-11-03T12:00:00+01:00")
