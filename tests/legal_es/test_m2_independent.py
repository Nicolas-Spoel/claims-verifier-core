"""Integration test: enabled when running inside the real fork with Core 0.1.1."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from keepmehonest_legal_es import LegalEvidence, Origin, SourceKind
from keepmehonest_legal_es.independent import verify_argument, _is_courtesy_only
from keepmehonest_legal_es.__main__ import main
from keepmehonest_legal_es.sources import FetchError

HAS_CORE = importlib.util.find_spec('claims_verifier') is not None
BOE='BOE-A-1978-31229'
CLAIM='La norma BOE-A-1978-31229 regula la tutela judicial efectiva.'


class CourtesyBoundaryTests(unittest.TestCase):
    def test_only_complete_courtesy_is_excluded(self):
        for message in ('Gracias por su atención.', 'Muchas gracias por su tiempo.', 'Saludos cordiales.'):
            self.assertTrue(_is_courtesy_only(message), message)

    def test_courtesy_plus_legal_statement_is_not_excluded(self):
        for message in ('Gracias por su atención: el artículo 24 CE está vigente.',
                        'Gracias por su atención a la sentencia ECLI:ES:TC:2024:1.',
                        'La norma BOE-A-1978-31229 regula la tutela judicial efectiva.'):
            self.assertFalse(_is_courtesy_only(message), message)


@unittest.skipUnless(HAS_CORE, 'requires full Core 0.1.1 checkout')
class IndependentTests(unittest.TestCase):
    def setUp(self):
        self.example=LegalEvidence(
            source=SourceKind.BOE, identifier=BOE, section_id='a24',
            text='Artículo 24. Todos tienen derecho a obtener tutela efectiva de los jueces y tribunales.',
            official_url='https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229#a24',
            title='Artículo 24, Constitución Española', origin=Origin.USER_SUPPLIED,
            version_date='1978-12-29',
        )

    def test_no_evidence_is_not_false(self):
        report=verify_argument(CLAIM, [])
        self.assertEqual(report['status'],'SOURCES_REQUIRED')
        self.assertEqual(report['coverage']['ordinary_court_search'],'NOT_PERFORMED_CENDOJ_DISABLED')
        self.assertEqual(report['legal_argument_quality'],'NOT_ASSESSED')
        self.assertEqual(report['coverage']['unresolved_explicit_identifiers'], [BOE])

    def test_no_network_for_local_review(self):
        with patch('keepmehonest_legal_es.sources.transport.SecureHTTP.get', side_effect=AssertionError('outbound call')):
            report=verify_argument(CLAIM, [self.example])
        self.assertEqual(report['status'],'READY_FOR_HUMAN_REVIEW')
        self.assertEqual(report['claims'][0]['legal_support'],'NOT_ASSESSED')
        self.assertEqual(report['claims'][0]['linked_cited_sources'][0]['identifier_check'],'MATCH')

    def test_no_checkable_claims_does_not_throw(self):
        report=verify_argument('Gracias por su atención.',[self.example])
        self.assertEqual(report['status'],'NO_CHECKABLE_CLAIMS')
        self.assertFalse(report['claims'])
        self.assertIn('standalone_courtesy', [s['reason'] for s in report['unchecked_segments']])

    def test_courtesy_does_not_hide_legal_claim(self):
        report = verify_argument('Gracias por su atención.\n' + CLAIM, [self.example])
        self.assertEqual(report['status'], 'READY_FOR_HUMAN_REVIEW')
        self.assertEqual(len(report['claims']), 1)
        self.assertEqual(report['claims'][0]['citations'], [BOE])
        self.assertIn('standalone_courtesy', [s['reason'] for s in report['unchecked_segments']])

    def test_courtesy_alone_without_sources_is_not_source_failure(self):
        report = verify_argument('Muchas gracias por su tiempo.', [])
        self.assertEqual(report['status'], 'NO_CHECKABLE_CLAIMS')
        self.assertEqual(report['claims'], [])

    def test_source_attempts_are_reported(self):
        attempt=[{'source':'TC','identifier':'ECLI:ES:TC:2024:1','status':'UNAVAILABLE'}]
        r=verify_argument(CLAIM,[self.example],attempted_sources=attempt)
        self.assertEqual(r['coverage']['source_attempts'],attempt)

    def test_duplicate_evidence_key_rejected(self):
        with self.assertRaises(ValueError): verify_argument(CLAIM, [self.example,self.example])

    def test_offline_cli(self):
        with TemporaryDirectory() as tmp:
            src=Path(tmp)/'input.txt'; src.write_text(CLAIM,encoding='utf-8')
            with io.StringIO() as buffer, contextlib.redirect_stdout(buffer):
                status=main(['--text-file',str(src)])
                output=buffer.getvalue()
            self.assertEqual(status,0)
            self.assertEqual(json.loads(output)['status'],'SOURCES_REQUIRED')

    def test_cli_requires_network_opt_in(self):
        with TemporaryDirectory() as tmp:
            src=Path(tmp)/'input.txt'; src.write_text(CLAIM,encoding='utf-8')
            with contextlib.redirect_stderr(io.StringIO()):
                status=main(['--text-file',str(src), '--boe', BOE+',24,2024-01-01'])
            self.assertEqual(status,2)

    def test_requested_fetch_failure_returns_nonzero_and_records_gap(self):
        with TemporaryDirectory() as tmp:
            src=Path(tmp)/'input.txt'; src.write_text(CLAIM,encoding='utf-8')
            with patch('keepmehonest_legal_es.__main__.BOEClient') as mock_client:
                mock_client.return_value.get_article.side_effect=FetchError('source blocked')
                with io.StringIO() as buffer, contextlib.redirect_stdout(buffer):
                    code=main(['--text-file',str(src), '--boe', BOE+',24,2024-01-01', '--allow-official-network'])
                    output=json.loads(buffer.getvalue())
            self.assertEqual(code,3)
            self.assertEqual(output['coverage']['source_attempts'][0]['status'],'UNAVAILABLE')
            self.assertEqual(output['status'],'SOURCES_REQUIRED')

    def test_evidence_origin_cannot_be_forged_in_cli(self):
        with TemporaryDirectory() as tmp:
            src=Path(tmp)/'input.txt'; src.write_text(CLAIM,encoding='utf-8')
            data=Path(tmp)/'evidence.json'
            payload={
                'source':'BOE','identifier':BOE,'section_id':'a24','text':self.example.text,
                'official_url':self.example.official_url,'title':self.example.title,
                'version_date':'1978-12-29','origin':'OFFICIAL_FETCH','retrieved_at':'2026-11-04T00:00:00+00:00'
            }
            data.write_text(json.dumps([payload]),encoding='utf-8')
            with io.StringIO() as buffer, contextlib.redirect_stdout(buffer):
                status=main(['--text-file',str(src),'--evidence-json',str(data)])
                output=json.loads(buffer.getvalue())
            self.assertEqual(status,0)
            self.assertEqual(output['evidence'][0]['origin'],'USER_SUPPLIED')

if __name__=='__main__':unittest.main()
