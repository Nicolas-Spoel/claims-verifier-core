"""M5-D technical-only freeze: only synthetic transport; zero expert/legal claims."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from keepmehonest_legal_es.m5_capture import capture_cases
from keepmehonest_legal_es.m5_seal import (
    SealError, CASE_CAPTURED, CASE_MISSING, SEAL_STATE,
    assemble, main, plan, verify_seal, _save_privately,
)
from test_m2_sources import StubHTTP

CORPUS = Path(__file__).resolve().parents[2] / 'evals/legal_es/m5/pilot_candidates.json'


class SealTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.corpus = json.loads(CORPUS.read_text(encoding='utf-8'))
        self.a = self.base / 'boe-001'
        self.b = self.base / 'tc-032'

    def captures(self):
        capture_cases(self.corpus, ['PUB-M5-001'], self.a, transport=StubHTTP())
        capture_cases(self.corpus, ['PUB-M5-032'], self.b, transport=StubHTTP())
        return [self.a, self.b]

    def test_plan_has_no_expert_gold_or_rights(self):
        p = plan(self.corpus)
        self.assertEqual(p['candidate_cases'], 36)
        self.assertEqual(p['expert_gold_cases'], 0)
        self.assertFalse(p['legal_accuracy_measured'])
        self.assertEqual(p['rights_cleared'], 0)

    def test_two_captures_replay_and_freeze_without_gold(self):
        roots = self.captures()
        seal = assemble(self.corpus, roots)
        self.assertEqual(seal['status'], SEAL_STATE)
        self.assertEqual(seal['captured_cases'], 2)
        self.assertEqual(seal['uncaptured_cases'], 34)
        self.assertEqual(seal['technically_replayed_tasks'], 2)
        self.assertEqual(seal['expert_gold_cases'], 0)
        self.assertEqual(seal['rights_cleared'], 0)
        self.assertFalse(seal['legal_accuracy_measured'])
        by_case = {c['case_id']: c for c in seal['cases']}
        self.assertEqual(by_case['PUB-M5-001']['capture_status'], CASE_CAPTURED)
        self.assertEqual(by_case['PUB-M5-032']['capture_status'], CASE_CAPTURED)
        self.assertEqual(by_case['PUB-M5-003']['capture_status'], CASE_MISSING)
        self.assertTrue(all(c['legal_support']=='NOT_ASSESSED' for c in seal['cases']))
        self.assertFalse('raw' in json.dumps(seal).lower() and 'document text' in json.dumps(seal).lower())
        r=verify_seal(self.corpus, list(reversed(roots)), seal)
        self.assertEqual(r['mode'], 'OFFLINE_M5D_TECHNICAL_SEAL_VERIFIED')
        self.assertEqual(r['captured_cases'], 2)

    def test_duplicate_capture_path_rejected(self):
        roots=self.captures()
        with self.assertRaisesRegex(SealError,'duplicate capture directory'):
            assemble(self.corpus,[roots[0],roots[0]])

    def test_missing_captures_cannot_be_sealed(self):
        with self.assertRaisesRegex(SealError,'needs 1-33'):
            assemble(self.corpus,[])

    def test_corpus_change_invalidates_old_seal(self):
        roots=self.captures()
        old=assemble(self.corpus,roots)
        changed=deepcopy(self.corpus)
        changed['cases'][0]['proposition']+=' Además, se alega otra cuestión.'
        with self.assertRaises(Exception):
            verify_seal(changed,roots,old)

    def test_manifest_file_tamper_invalidates_replay(self):
        roots=self.captures()
        seal=assemble(self.corpus, roots)
        raw=next(self.a.glob('raw/*'))
        raw.write_bytes(raw.read_bytes()+b'changed')
        with self.assertRaises(Exception):
            verify_seal(self.corpus,roots,seal)

    def test_self_hash_tampering_rejected(self):
        roots=self.captures()
        seal=assemble(self.corpus,roots)
        seal['captured_cases']=99
        with self.assertRaisesRegex(SealError,'seal digest mismatch'):
            verify_seal(self.corpus,roots,seal)

    def test_recomputed_hash_cannot_promote_gold(self):
        from keepmehonest_legal_es.m5_seal import _sha
        roots=self.captures()
        seal=assemble(self.corpus,roots)
        seal['expert_gold_cases']=1
        seal['seal_sha256']=_sha({k:v for k,v in seal.items() if k!='seal_sha256'})
        with self.assertRaisesRegex(SealError,'gold/rights/accuracy promotion'):
            verify_seal(self.corpus,roots,seal)

    def test_fake_rights_clearance_not_allowed(self):
        from keepmehonest_legal_es.m5_seal import _sha
        roots=self.captures()
        seal=assemble(self.corpus,roots)
        seal['rights_cleared']=2
        seal['seal_sha256']=_sha({k:v for k,v in seal.items() if k!='seal_sha256'})
        with self.assertRaisesRegex(SealError,'gold/rights/accuracy promotion'):
            verify_seal(self.corpus,roots,seal)

    def test_private_output_fails_existing_target(self):
        seal=assemble(self.corpus,self.captures())
        target=self.base/'sealed'
        _save_privately(target,seal)
        self.assertTrue((target/'technical_seal_PRIVATE.json').is_file())
        self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE((target/'technical_seal_PRIVATE.json').stat().st_mode),0o600)
        with self.assertRaisesRegex(SealError,'new absolute output'):
            _save_privately(target,seal)

    def test_no_network_from_m5d(self):
        roots=self.captures()
        with patch('keepmehonest_legal_es.sources.transport.SecureHTTP.get', side_effect=AssertionError('network call')):
            out=assemble(self.corpus,roots)
            verify_seal(self.corpus,roots,out)

    def test_symlink_raw_rejected(self):
        roots=self.captures()
        seal=assemble(self.corpus,roots)
        f=next(self.a.glob('raw/*'))
        good=f.read_bytes()
        f.unlink()
        linked=self.base/'replacement'
        linked.write_bytes(good)
        f.symlink_to(linked)
        with self.assertRaises(Exception):
            verify_seal(self.corpus,roots,seal)

    def test_cannot_mix_same_task_twice(self):
        roots=self.captures()
        another=self.base/'duplicate-boe'
        import shutil
        shutil.copytree(self.a,another)
        with self.assertRaisesRegex(SealError,'same snapshot task'):
            assemble(self.corpus,roots+[another])

    def test_cli_plan(self):
        self.assertEqual(main(['plan','--candidates',str(CORPUS)]),0)

    def test_cli_seal_then_verify(self):
        roots=self.captures()
        out=self.base/'sealed'
        args=['--candidates',str(CORPUS),'--capture-dir',str(roots[0]),'--capture-dir',str(roots[1])]
        self.assertEqual(main(['seal']+args+['--output-dir',str(out)]),0)
        self.assertEqual(main(['verify']+args+['--seal-file',str(out/'technical_seal_PRIVATE.json')]),0)


if __name__=='__main__':
    unittest.main()
