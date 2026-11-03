"""M2: synthetic wire fixtures shaped after 2025 AEBOE API and HJ docs.
No external requests run in unit tests; live smoke is deliberately separate.
"""
from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
import unittest

from keepmehonest_legal_es.sources import BOEClient, TCClient, SecureHTTP, FetchError
from keepmehonest_legal_es.sources.transport import Retrieved
from keepmehonest_legal_es.evidence import Origin

BOE_ID = "BOE-A-1978-31229"
XML_INDEX = b'''<?xml version="1.0"?><response><status><code>200</code></status><data>
<bloque><id>a24</id><titulo>Art\xc3\xadculo 24</titulo><fecha_actualizacion>20240115</fecha_actualizacion></bloque>
<bloque><id>a25</id><titulo>Art\xc3\xadculo 25</titulo></bloque>
</data></response>'''
XML_BLOCK = b'''<?xml version="1.0"?><response><status><code>200</code></status><data>
<bloque id="a24" tipo="precepto" titulo="Art\xc3\xadculo 24">
 <version id_norma="BOE-A-1978-31229" fecha_publicacion="19781229" fecha_vigencia="19781229"><p>Art\xc3\xadculo 24.</p><p>Todos tienen derecho a obtener tutela judicial efectiva de los jueces y tribunales.</p></version>
 <version id_norma="BOE-A-2023-12" fecha_publicacion="20230101" fecha_vigencia="20230102"><p>Art\xc3\xadculo 24.</p><p>Texto ficticio modificado para pruebas exclusivamente sint\xc3\xa9ticas.</p><blockquote><p>Nota editorial que NO integra el art\xc3\xadculo.</p></blockquote></version>
</bloque></data></response>'''
ECLI = "ECLI:ES:TC:2024:1"
# Synthetic response following the official HJ JSON/30062 schema, not a copy
# of the full judgment. The key names were checked against the live HJ export.
JSON_TC = json.dumps({
    "ID": 30062, "TIPO_RESOLUCION": "SENTENCIA", "NUMERO_RESOLUCION": 1,
    "ANNO_RESOLUCION": 2024, "FECHA_REGISTRO": "2024-01-15T00:00:00",
    "RESOLUCIONES_ANTECEDENTES": [{"NUMERO": 1, "TEXTO": "Antecedentes que no deben mezclarse en FJ1."}],
    "RESOLUCIONES_FUNDAMENTOS": [
        {"ID": 84314, "NUMERO": 1, "TEXTO": "Delimitación del objeto del recurso de amparo; especial trascendencia constitucional\n\nEl recurso examina la suficiencia de una investigación judicial y el deber de tutela."},
        {"ID": 84315, "NUMERO": 2, "TEXTO": "Doctrina jurisprudencial aplicable al contexto de la presente sentencia, con circunstancias y excepciones relevantes."},
    ],
    "RESOLUCIONES_DICTAMEN": [{"ID": 30051, "TITULO": "FALLO", "TEXTO": "En atención a lo expuesto, el Tribunal acuerda estimar el recurso y restablecer la tutela judicial efectiva de la parte demandante."}],
    "RESOLUCIONES_EXTRACTOS": [{"NUMERO": 1, "TEXTO": "Resumen NO literal que nunca es fundamento jurídico."}],
}, ensure_ascii=False).encode("utf-8")


class StubHTTP:
    def __init__(self, index=XML_INDEX, block=XML_BLOCK, tc_json=JSON_TC):
        self.index, self.block, self.tc_json = index, block, tc_json
        self.calls = []
    def get(self, url, *, accept):
        SecureHTTP.check_url(url)
        self.calls.append((url, accept))
        body = self.index if url.endswith('/indice') else (self.block if '/bloque/' in url else self.tc_json)
        return Retrieved(url, body, 'application/xml' if accept == 'application/xml' else 'application/json', sha256(body).hexdigest(), '2026-11-04T00:00:00+00:00')


class BOETests(unittest.TestCase):
    def test_select_historical_before_amendment(self):
        stub=StubHTTP()
        out=BOEClient(stub).get_article(BOE_ID,24,'1980-01-01')
        self.assertEqual(out.evidence.version_date, '1978-12-29')
        self.assertIn('tutela judicial',out.evidence.text)
        self.assertEqual(out.temporal_status,'CHECK_REQUIRED')
        self.assertEqual(len(stub.calls),2)
        self.assertEqual(out.evidence.origin,Origin.OFFICIAL_FETCH)
    def test_select_newer_version_and_strip_notes(self):
        out=BOEClient(StubHTTP()).get_article(BOE_ID,24,'2024-01-15')
        self.assertEqual(out.evidence.version_date,'2023-01-02')
        self.assertIn('ficticio',out.evidence.text)
        self.assertNotIn('Nota editorial',out.evidence.text)
    def test_no_future_version_guess(self):
        with self.assertRaisesRegex(FetchError, 'no dated'):
            BOEClient(StubHTTP()).get_article(BOE_ID,24,'1978-12-28')
    def test_refuse_missing_temporal_metadata(self):
        altered=XML_BLOCK.replace(b' fecha_vigencia="20230102"',b'')
        with self.assertRaisesRegex(FetchError, 'missing temporal'):
            BOEClient(StubHTTP(block=altered)).get_article(BOE_ID,24,'2024-01-15')
    def test_no_ambiguous_block(self):
        duplicated=XML_INDEX.replace(b'</data>',b'<bloque><id>b24</id><titulo>Art\xc3\xadculo 24</titulo></bloque></data>')
        with self.assertRaisesRegex(FetchError,'not uniquely'):
            BOEClient(StubHTTP(index=duplicated)).get_article(BOE_ID,24,'2024-01-15')
    def test_prohibit_dtd(self):
        altered=XML_BLOCK.replace(b'<response>',b'<!DOCTYPE foo [<!ENTITY y SYSTEM "file:///tmp/x">]><response>')
        with self.assertRaisesRegex(FetchError,'DTD'):
            BOEClient(StubHTTP(block=altered)).get_article(BOE_ID,24,'2024-01-15')
    def test_reject_api_status(self):
        altered=XML_BLOCK.replace(b'<code>200</code>',b'<code>404</code>')
        with self.assertRaisesRegex(FetchError,'not 200'):
            BOEClient(StubHTTP(block=altered)).get_article(BOE_ID,24,'2024-01-15')
    def test_reject_wrong_identifier(self):
        with self.assertRaises(ValueError): BOEClient(StubHTTP()).get_article(ECLI,24,'2024-01-15')
    def test_reject_invalid_article(self):
        with self.assertRaises(ValueError): BOEClient(StubHTTP()).get_article(BOE_ID,True,'2024-01-15')
    def test_expired_block_not_reused(self):
        altered=XML_BLOCK.replace(b'<bloque id="a24"',b'<bloque fecha_caducidad="20000101" id="a24"')
        with self.assertRaisesRegex(FetchError,'expired'):
            BOEClient(StubHTTP(block=altered)).get_article(BOE_ID,24,'2024-01-15')
    def test_ambiguous_versions_same_date(self):
        block=XML_BLOCK.replace(b'</bloque></data>',b'<version id_norma="BOE-A-2023-13" fecha_publicacion="20230101" fecha_vigencia="20230102"><p>Duplicado.</p></version></bloque></data>')
        with self.assertRaisesRegex(FetchError,'ambiguous'):
            BOEClient(StubHTTP(block=block)).get_article(BOE_ID,24,'2024-01-15')


class TCTests(unittest.TestCase):
    def test_fj_isolates_without_antecedents(self):
        stub=StubHTTP()
        out=TCClient(stub).get_section(ECLI,30062,'FJ1')
        self.assertEqual(out.evidence.section_id,'FJ1')
        self.assertEqual(out.evidence.decision_date,'2024-01-15')
        self.assertNotIn('Antecedentes que',out.evidence.text)
        self.assertNotIn('Doctrina jurisprudencial',out.evidence.text)
        self.assertNotIn('Resumen NO literal',out.evidence.text)
        self.assertIn('suficiencia de una investigación',out.evidence.text)
        self.assertTrue(out.api_url.endswith('/Api/json/30062'))
        self.assertEqual(len(stub.calls),1)
        self.assertEqual(stub.calls[0][1], 'application/json')
        self.assertEqual(out.evidence.origin,Origin.OFFICIAL_FETCH)

    def test_fallo_isolates_structured_dictamen(self):
        out=TCClient(StubHTTP()).get_section(ECLI,30062,'FALLO')
        self.assertIn('estimar el recurso',out.evidence.text)
        self.assertNotIn('Doctrina jurisprudencial',out.evidence.text)

    def test_wrong_ecli_fails_closed(self):
        with self.assertRaisesRegex(FetchError,'identity does not match'):
            TCClient(StubHTTP()).get_section('ECLI:ES:TC:2024:2',30062,'FJ1')

    def test_wrong_year_fails_closed(self):
        with self.assertRaisesRegex(FetchError,'identity does not match'):
            TCClient(StubHTTP()).get_section('ECLI:ES:TC:2023:1',30062,'FJ1')

    def test_wrong_hj_id_fails_closed(self):
        with self.assertRaisesRegex(FetchError,'identity does not match'):
            TCClient(StubHTTP()).get_section(ECLI,30063,'FJ1')

    def test_wrong_fj_does_not_fallback(self):
        with self.assertRaisesRegex(FetchError,'not uniquely'):
            TCClient(StubHTTP()).get_section(ECLI,30062,'FJ3')

    def test_duplicate_fj_is_not_accepted(self):
        raw=json.loads(JSON_TC)
        raw['RESOLUCIONES_FUNDAMENTOS'].append({'NUMERO':1,'TEXTO':'Otro fundamento suficientemente largo para duplicar el numero uno.'})
        with self.assertRaisesRegex(FetchError,'not uniquely'):
            TCClient(StubHTTP(tc_json=json.dumps(raw).encode())).get_section(ECLI,30062,'FJ1')

    def test_duplicate_fallo_is_not_accepted(self):
        raw=json.loads(JSON_TC)
        raw['RESOLUCIONES_DICTAMEN'].append({'TITULO':'FALLO','TEXTO':'Otro fallo largo en el mismo documento que crea ambigüedad.'})
        with self.assertRaisesRegex(FetchError,'not uniquely'):
            TCClient(StubHTTP(tc_json=json.dumps(raw).encode())).get_section(ECLI,30062,'FALLO')

    def test_missing_fundamentals_does_not_use_summary(self):
        raw=json.loads(JSON_TC)
        del raw['RESOLUCIONES_FUNDAMENTOS']
        with self.assertRaisesRegex(FetchError,'collection absent'):
            TCClient(StubHTTP(tc_json=json.dumps(raw).encode())).get_section(ECLI,30062,'FJ1')

    def test_invalid_json_and_duplicate_keys_fail_closed(self):
        with self.assertRaisesRegex(FetchError,'JSON response invalid'):
            TCClient(StubHTTP(tc_json=b'<html>Not JSON</html>')).get_section(ECLI,30062,'FJ1')
        malicious=JSON_TC.replace(b'"ID": 30062',b'"ID": 30062, "ID": 30063')
        with self.assertRaisesRegex(FetchError,'JSON response invalid'):
            TCClient(StubHTTP(tc_json=malicious)).get_section(ECLI,30062,'FJ1')

    def test_date_year_mismatch_fails_closed(self):
        raw=json.loads(JSON_TC)
        raw['FECHA_REGISTRO']='2023-12-15T00:00:00'
        with self.assertRaisesRegex(FetchError,'decision year'):
            TCClient(StubHTTP(tc_json=json.dumps(raw).encode())).get_section(ECLI,30062,'FJ1')

    def test_malformed_timestamp_is_not_accepted(self):
        raw=json.loads(JSON_TC)
        raw['FECHA_REGISTRO']='2024-01-15Tinvalid'
        with self.assertRaisesRegex(FetchError,'date missing or invalid'):
            TCClient(StubHTTP(tc_json=json.dumps(raw).encode())).get_section(ECLI,30062,'FJ1')

    def test_other_resolution_types_rejected(self):
        raw=json.loads(JSON_TC)
        raw['TIPO_RESOLUCION']='AUTO'
        with self.assertRaisesRegex(FetchError,'identity does not match'):
            TCClient(StubHTTP(tc_json=json.dumps(raw).encode())).get_section(ECLI,30062,'FJ1')
        with self.assertRaises(ValueError):
            TCClient(StubHTTP()).get_section('ECLI:ES:TC:2024:1A',30062,'FJ1')

    def test_identifier_must_tc(self):
        with self.assertRaises(ValueError): TCClient(StubHTTP()).get_section(BOE_ID,30062,'FJ1')
    def test_document_numeric_only(self):
        with self.assertRaises(ValueError): TCClient(StubHTTP()).get_section(ECLI,True,'FJ1')
    def test_section_supported(self):
        with self.assertRaises(ValueError): TCClient(StubHTTP()).get_section(ECLI,30062,'ALL')


class NetworkSafetyTests(unittest.TestCase):
    def test_reject_arbitrary_host(self):
        for url in ('http://www.boe.es/datosabiertos/api/legislacion-consolidada/id/X',
                    'https://boe.es/datosabiertos/api/legislacion-consolidada/id/X',
                    'https://www.boe.es.evil.test/datosabiertos/api/legislacion-consolidada/id/X',
                    'https://hj.tribunalconstitucional.es:443/HJ/es/Resolucion/Show/123',
                    'https://hj.tribunalconstitucional.es/HJ/Resolucion/Api/json/1?x=y',
                    'https://hj.tribunalconstitucional.es/HJ/es/Resolucion/Show/30062',
                    'https://hj.tribunalconstitucional.es/HJ/Resolucion/Api/json/../../admin',
                    'https://www.poderjudicial.es/'):
            with self.subTest(url=url), self.assertRaises(FetchError): SecureHTTP.check_url(url)
    def test_accept_expected_urls(self):
        SecureHTTP.check_url('https://www.boe.es/datosabiertos/api/legislacion-consolidada/id/BOE-A-1978-31229/texto/indice')
        SecureHTTP.check_url('https://hj.tribunalconstitucional.es/HJ/Resolucion/Api/json/30062')

if __name__=='__main__':unittest.main()
