"""M5-B deterministic public-source capture tests; no external HTTP or legal labels."""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from keepmehonest_legal_es.m5_capture import (
    CaptureError, capture_cases, capture_plan, verify_capture, main,
)
from keepmehonest_legal_es.sources.transport import Retrieved
from test_m2_sources import StubHTTP, JSON_TC

CORPUS = Path(__file__).resolve().parents[2] / 'evals/legal_es/m5/pilot_candidates.json'


def corpus():
    return json.loads(CORPUS.read_text(encoding='utf-8'))


class M5CaptureTests(unittest.TestCase):
    def setUp(self):
        self.c = corpus()
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.dest = self.root / 'first-capture'

    def boe(self, ids=None, **kwargs):
        return capture_cases(self.c, ['PUB-M5-001'] if ids is None else ids, self.dest,
                             transport=kwargs.get('transport') or StubHTTP())

    def test_plan_accounts_for_33_distinct_retrieval_tasks(self):
        plan = capture_plan(self.c)
        self.assertEqual(plan['candidate_cases'], 36)
        self.assertEqual(plan['unique_source_section_clusters'], 13)
        self.assertEqual(plan['distinct_capture_tasks'], 33)
        self.assertEqual(plan['boe_date_scoped_tasks'], 31)
        self.assertEqual(plan['tc_section_tasks'], 2)
        self.assertEqual(plan['expert_gold_cases'], 0)
        self.assertFalse(plan['legal_accuracy_measured'])

    def test_capture_boe_freezes_both_raw_responses_and_replays(self):
        summary = self.boe()
        self.assertEqual(summary['task_count'], 1)
        self.assertEqual(summary['raw_responses'], 2)
        self.assertEqual(summary['rights_cleared'], 0)
        report = verify_capture(self.c, self.dest)
        self.assertEqual(report['sections_verified'], 1)
        self.assertEqual(report['raw_responses_verified'], 2)
        self.assertEqual(report['mode'], 'OFFLINE_VERIFIED_REPLAY')
        manifest = json.loads((self.dest / 'manifest.json').read_text())
        task = manifest['tasks'][0]
        self.assertEqual(task['identifier'], 'BOE-A-1978-31229')
        self.assertEqual(task['section_id'], 'a24')
        self.assertEqual(task['requested_as_of'], '2023-09-12')
        self.assertEqual(task['metadata']['effective_from'], '2023-01-02')
        self.assertEqual(task['metadata']['temporal_status'], 'CHECK_REQUIRED')
        self.assertFalse(task['official_publication_checked'])
        self.assertFalse(task['rights_reviewed'])
        self.assertEqual(task['retrieval_status'], 'FETCHED_RAW_UNREVIEWED')

    def test_exact_files_private_mode(self):
        self.boe()
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(self.dest.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((self.dest / 'manifest.json').stat().st_mode), 0o600)
        for file in self.dest.rglob('*'):
            if file.is_file():
                self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)

    def test_tc_capture_replay_requires_exact_hj_identity(self):
        result = capture_cases(self.c, ['PUB-M5-032'], self.dest, transport=StubHTTP())
        self.assertEqual(result['raw_responses'], 1)
        manifest = json.loads((self.dest / 'manifest.json').read_text())
        task = manifest['tasks'][0]
        self.assertEqual(task['section_id'], 'FJ1')
        self.assertEqual(task['hj_document_id'], 30062)
        self.assertEqual(task['metadata']['decision_date'], '2024-01-15')
        self.assertEqual(verify_capture(self.c, self.dest)['sections_verified'], 1)

    def test_two_same_tc_section_cases_deduplicate_without_semantic_inference(self):
        capture_cases(self.c, ['PUB-M5-032', 'PUB-M5-033'], self.dest, transport=StubHTTP())
        task = json.loads((self.dest/'manifest.json').read_text())['tasks'][0]
        self.assertEqual(task['case_ids'], ['PUB-M5-032','PUB-M5-033'])
        self.assertIsNone(task['requested_as_of'])
        self.assertEqual(verify_capture(self.c, self.dest)['tasks_verified'], 1)

    def test_bo_evidence_is_not_deduplicated_across_candidate_dates(self):
        capture_cases(self.c, ['PUB-M5-001', 'PUB-M5-002'], self.dest, transport=StubHTTP())
        task = json.loads((self.dest/'manifest.json').read_text())['tasks']
        self.assertEqual(len(task),2)
        self.assertEqual({x['requested_as_of'] for x in task}, {'2023-09-12','2023-10-10'})
        self.assertEqual(verify_capture(self.c, self.dest)['raw_responses_verified'], 4)

    def test_synthetic_article49_pre_and_post_change_are_distinct_versions(self):
        # Hypothetical wire responses, not actual authoritative amendment dates.
        from test_m2_sources import XML_INDEX, XML_BLOCK
        old_idx = XML_INDEX.replace(b'a24', b'a49').replace(b'culo 24', b'culo 49')
        old_block = XML_BLOCK.replace(b'a24', b'a49').replace(b'culo 24', b'culo 49')
        new_block = old_block.replace(b'20230101', b'20240216').replace(b'20230102', b'20240217')
        capture_cases(self.c, ['PUB-M5-007', 'PUB-M5-009'], self.dest,
                      transport=StubHTTP(index=old_idx, block=new_block))
        tasks = json.loads((self.dest/'manifest.json').read_text())['tasks']
        self.assertEqual([t['requested_as_of'] for t in tasks], ['2023-06-16', '2025-01-16'])
        self.assertEqual([t['metadata']['effective_from'] for t in tasks], ['1978-12-29', '2024-02-17'])
        self.assertEqual(verify_capture(self.c,self.dest)['sections_verified'],2)
        self.assertTrue(all(t['metadata']['consolidated_informational'] for t in tasks))

    def test_missing_boe_temporal_metadata_cannot_create_capture(self):
        from test_m2_sources import XML_BLOCK
        bad = XML_BLOCK.replace(b' fecha_vigencia="20230102"',b'')
        with self.assertRaisesRegex(Exception,'missing temporal'):
            self.boe(transport=StubHTTP(block=bad))
        self.assertFalse(self.dest.exists())

    def test_out_dir_must_not_exist(self):
        self.dest.mkdir()
        with self.assertRaisesRegex(CaptureError,'must not already exist'):
            self.boe()

    def test_unknown_ids_duplicates_and_over_limit_fail(self):
        for ids in (['PUB-M5-999'], [], ['PUB-M5-001']*2,
                    ['PUB-M5-001','PUB-M5-002','PUB-M5-003','PUB-M5-004']):
            with self.subTest(ids=ids), self.assertRaises(CaptureError):
                self.boe(ids)

    def test_missing_tc_fj_fails_without_partial_packet(self):
        with self.assertRaisesRegex(Exception,'not uniquely'):
            capture_cases(self.c,['PUB-M5-035'],self.dest,transport=StubHTTP())
        self.assertFalse(self.dest.exists())

    def test_fake_transport_misreported_url_fails_closed(self):
        class WrongURL(StubHTTP):
            def get(self, url, *, accept):
                got=super().get(url,accept=accept)
                return Retrieved('https://evil.example/',got.body,got.content_type,got.sha256,got.retrieved_at)
        with self.assertRaisesRegex(CaptureError,'mismatched URL'):
            self.boe(transport=WrongURL())
        self.assertFalse(self.dest.exists())

    def test_raw_mutation_cannot_be_replayed(self):
        self.boe()
        doc = json.loads((self.dest/'manifest.json').read_text())['tasks'][0]['raw'][0]
        f=self.dest/doc['path']
        f.write_bytes(f.read_bytes()+b'ALTERED')
        with self.assertRaisesRegex(CaptureError,'size mismatch'):
            verify_capture(self.c,self.dest)

    def test_same_size_tampering_detected_by_sha256(self):
        self.boe()
        doc=json.loads((self.dest/'manifest.json').read_text())['tasks'][0]['raw'][1]
        f=self.dest/doc['path']; data=f.read_bytes()
        f.write_bytes(data[:25]+bytes([data[25]^1])+data[26:])
        with self.assertRaisesRegex(CaptureError,'SHA-256 mismatch'):
            verify_capture(self.c,self.dest)

    def test_section_mutation_detected(self):
        self.boe()
        rec=json.loads((self.dest/'manifest.json').read_text())['tasks'][0]
        f=self.dest/rec['section_path']; data=f.read_bytes()
        f.write_bytes(data[:12]+bytes([data[12]^1])+data[13:])
        with self.assertRaisesRegex(CaptureError,'SHA-256 mismatch'):
            verify_capture(self.c,self.dest)

    def test_dishonest_section_hash_update_does_not_override_raw_replay(self):
        self.boe()
        mf=self.dest/'manifest.json';m=json.loads(mf.read_text());t=m['tasks'][0]
        f=self.dest/t['section_path'];data=f.read_bytes()+b' ADDED'
        f.write_bytes(data); t['section_size_bytes']=len(data); t['section_sha256']=sha256(data).hexdigest()
        mf.write_text(json.dumps(m))
        with self.assertRaisesRegex(CaptureError,'extracted section mismatches'):
            verify_capture(self.c,self.dest)

    def test_forged_clearance_is_not_allowed(self):
        self.boe()
        mf=self.dest/'manifest.json';m=json.loads(mf.read_text());m['rights_cleared']=1;mf.write_text(json.dumps(m))
        with self.assertRaisesRegex(CaptureError,'safety contract'):
            verify_capture(self.c,self.dest)

    def test_forged_independent_publication_check_rejected(self):
        self.boe()
        mf=self.dest/'manifest.json';m=json.loads(mf.read_text());m['tasks'][0]['official_publication_checked']=True
        mf.write_text(json.dumps(m))
        with self.assertRaisesRegex(CaptureError,'promotes unreviewed'):
            verify_capture(self.c,self.dest)

    def test_renamed_claimed_section_rejected(self):
        self.boe()
        mf=self.dest/'manifest.json';m=json.loads(mf.read_text());m['tasks'][0]['section_id']='a25'
        mf.write_text(json.dumps(m))
        with self.assertRaisesRegex(CaptureError,'locator changed'):
            verify_capture(self.c,self.dest)

    def test_corpus_digest_change_invalidates_capture(self):
        self.boe()
        self.c['cases'][0]['proposition']+=' Cambio de proposición para prueba.'
        with self.assertRaisesRegex(CaptureError,'pilot or safety contract'):
            verify_capture(self.c,self.dest)

    def test_absolute_capture_paths_only_and_symlink_parent_refused(self):
        with self.assertRaisesRegex(CaptureError,'absolute'):
            capture_cases(self.c,['PUB-M5-001'],Path('relative-capture'),transport=StubHTTP())
        (self.root/'link').symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(CaptureError,'parent'):
            capture_cases(self.c,['PUB-M5-001'],self.root/'link'/'capture',transport=StubHTTP())

    def test_symlinked_raw_file_denied(self):
        self.boe()
        m=json.loads((self.dest/'manifest.json').read_text())
        doc=m['tasks'][0]['raw'][0]
        f=self.dest/doc['path'];backup=self.root/'outside.bin';f.rename(backup);f.symlink_to(backup)
        with self.assertRaisesRegex(CaptureError,'symlink'):
            verify_capture(self.c,self.dest)

    def test_manifest_traversal_refused(self):
        self.boe()
        mf=self.dest/'manifest.json';m=json.loads(mf.read_text())
        m['tasks'][0]['raw'][0]['path']='raw/../manifest.json'
        mf.write_text(json.dumps(m))
        with self.assertRaises(CaptureError):
            verify_capture(self.c,self.dest)

    def test_offline_plan_cli_makes_no_requests(self):
        with patch('keepmehonest_legal_es.m5_capture.SecureHTTP.get',side_effect=AssertionError('NETWORK')):
            self.assertEqual(main(['--candidates',str(CORPUS)]),0)

    def test_cli_cannot_capture_without_explicit_network(self):
        self.assertEqual(main(['--candidates',str(CORPUS),'--capture',
                               '--case-id','PUB-M5-001','--output-dir',str(self.dest)]),2)
        self.assertFalse(self.dest.exists())

    def test_cli_verify_is_offline(self):
        self.boe()
        with patch('keepmehonest_legal_es.m5_capture.SecureHTTP.get',side_effect=AssertionError('NETWORK')):
            self.assertEqual(main(['--candidates',str(CORPUS),'--verify',
                                   '--capture-dir',str(self.dest)]),0)

    def test_manifest_cannot_use_unauthorized_network_url(self):
        self.boe()
        mf=self.dest/'manifest.json';m=json.loads(mf.read_text());m['tasks'][0]['raw'][0]['url']='https://evil.example/steal'
        mf.write_text(json.dumps(m))
        with self.assertRaises(Exception):
            verify_capture(self.c,self.dest)

    def test_tc_null_byte_in_legal_section_is_rejected(self):
        class UnsafeTC(StubHTTP):
            def get(self, url, *, accept):
                if accept == 'application/json':
                    payload = json.loads(JSON_TC)
                    payload['RESOLUCIONES_FUNDAMENTOS'][0]['TEXTO'] += "\x00"
                    body=json.dumps(payload).encode('utf8')
                    return Retrieved(url,body,'application/json',sha256(body).hexdigest(),
                                     '2026-11-04T00:00:00+00:00')
                return super().get(url,accept=accept)
        with self.assertRaisesRegex(CaptureError,'disallowed'):
            capture_cases(self.c,['PUB-M5-032'],self.dest,transport=UnsafeTC())
        self.assertFalse(self.dest.exists())

    def test_tc_mismatched_hj_id_fails(self):
        class WrongTC(StubHTTP):
            def get(self, url, *, accept):
                obj=json.loads(JSON_TC); obj['ID']=30063
                if accept=='application/json':
                    body=json.dumps(obj).encode('utf8')
                    return Retrieved(url,body,'application/json',sha256(body).hexdigest(),'2026-11-04T00:00:00+00:00')
                return super().get(url,accept=accept)
        with self.assertRaisesRegex(Exception,'identity does not match'):
            capture_cases(self.c,['PUB-M5-032'],self.dest,transport=WrongTC())
        self.assertFalse(self.dest.exists())


if __name__=='__main__':
    unittest.main()
